"""Unit and security tests for document upload validation and text extraction.

Verifies streaming upload limits, magic byte format detection, PDF/DOCX parsing,
ZIP bomb defenses, complexity boundaries, and scan detection.
All fixtures are synthesized in memory; no temporary files or network calls are made.
"""

import io
from typing import AsyncGenerator
import zipfile

import pytest
from pypdf import PdfWriter

from backend.app.utils.document_parser import (
    DEFAULT_MAX_UPLOAD_BYTES,
    MAX_DOCX_ENTRIES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
    MAX_PDF_PAGES,
    DocumentComplexityError,
    DocumentParsingError,
    InvalidDocumentFormatError,
    UploadTooLargeError,
    detect_document_format,
    extract_document_text,
    parse_docx,
    parse_pdf,
    read_stream_safely,
    read_upload_file_safely,
)


def create_minimal_pdf_bytes(text_snippet: str = "ScholarSwarm Test Resume Content") -> bytes:
    """Create a minimal valid PDF byte string containing the specified text."""
    escaped_text = text_snippet.replace("(", "\\(").replace(")", "\\)")
    content_stream = f"BT /F1 12 Tf 72 712 Td ({escaped_text}) Tj ET"
    content_bytes = content_stream.encode("latin-1")
    length = len(content_bytes)

    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"5 0 obj << /Length " + str(length).encode("ascii") + b" >> stream\n"
        + content_bytes + b"\nendstream\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000244 00000 n \n"
        b"0000000318 00000 n \n"
        b"trailer << /Size 6 /Root 1 0 R >>\n"
        b"startxref\n450\n%%EOF\n"
    )
    return pdf


def create_minimal_docx_bytes(paragraphs: list[str]) -> bytes:
    """Create a minimal valid DOCX byte string with the specified paragraphs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml is required for DOCX format validation
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '</Types>',
        )
        # Construct word/document.xml with paragraph runs
        xml_paras = "".join(
            f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
        )
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{xml_paras}</w:body></w:document>"
        )
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


# ============================================================================
# Format Detection & Spoofing Tests
# ============================================================================

def test_detect_document_format_valid_pdf():
    pdf_bytes = create_minimal_pdf_bytes("PDF text")
    assert detect_document_format(pdf_bytes, "resume.pdf") == "pdf"


def test_detect_document_format_valid_docx():
    docx_bytes = create_minimal_docx_bytes(["DOCX paragraph"])
    assert detect_document_format(docx_bytes, "cv.docx") == "docx"


def test_detect_document_format_rejects_empty():
    with pytest.raises(InvalidDocumentFormatError, match="too small"):
        detect_document_format(b"")


def test_detect_document_format_rejects_spoofed_pdf_extension():
    # File named .pdf but containing arbitrary text
    spoofed = b"This is not a PDF file at all, just plain text."
    with pytest.raises(InvalidDocumentFormatError, match="signature does not match"):
        detect_document_format(spoofed, "fake.pdf")


def test_detect_document_format_rejects_arbitrary_zip_as_docx():
    # A valid ZIP file that is NOT a DOCX (lacks [Content_Types].xml and word/)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes.txt", "Some text file in a zip archive")
    non_docx_zip = buf.getvalue()

    with pytest.raises(InvalidDocumentFormatError, match="does not appear to be a valid DOCX"):
        detect_document_format(non_docx_zip, "archive.docx")


# ============================================================================
# Streaming Upload Size Limit Tests
# ============================================================================

def test_read_stream_safely_allows_within_limit():
    stream = io.BytesIO(b"A" * 1024)
    result = read_stream_safely(stream, max_bytes=2048)
    assert len(result) == 1024


def test_read_stream_safely_aborts_when_limit_exceeded():
    stream = io.BytesIO(b"A" * 5000)
    with pytest.raises(UploadTooLargeError, match="Stream exceeds maximum allowable size"):
        read_stream_safely(stream, max_bytes=4000, chunk_size=1024)


@pytest.mark.anyio
async def test_read_upload_file_safely_aborts_during_stream():
    class MockUploadFile:
        def __init__(self, data: bytes, chunk_size: int = 1024):
            self._stream = io.BytesIO(data)
            self._chunk_size = chunk_size

        async def read(self, size: int = -1) -> bytes:
            return self._stream.read(size if size > 0 else self._chunk_size)

    # 15 KiB file with a 10 KiB cap
    payload = b"X" * 15 * 1024
    mock_upload = MockUploadFile(payload, chunk_size=4096)

    with pytest.raises(UploadTooLargeError, match="File upload exceeds maximum allowable size"):
        await read_upload_file_safely(mock_upload, max_bytes=10 * 1024, chunk_size=4096)


# ============================================================================
# PDF Parsing & Complexity Tests
# ============================================================================

def test_extract_text_from_pdf():
    pdf_bytes = create_minimal_pdf_bytes("Alice Smith, Computer Science Researcher")
    text, warnings = extract_document_text(pdf_bytes, "resume.pdf")
    assert "Alice Smith" in text
    assert "Computer Science" in text


def test_parse_pdf_rejects_corrupted_data():
    corrupted = b"%PDF-1.4\ncorrupted trailer and xref broken data"
    with pytest.raises(DocumentParsingError, match="Failed to parse PDF document"):
        parse_pdf(corrupted)


def test_parse_pdf_enforces_max_page_limit():
    writer = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 5):
        writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    oversized_pdf = buf.getvalue()

    with pytest.raises(DocumentComplexityError, match="PDF exceeds maximum allowable limit of 50 pages"):
        parse_pdf(oversized_pdf)


# ============================================================================
# DOCX Parsing & ZIP Bomb Defense Tests
# ============================================================================

def test_extract_text_from_docx():
    paragraphs = [
        "Jane Doe",
        "Email: jane.doe@example.com",
        "Technical Skills: Python, Docker, PyTorch",
    ]
    docx_bytes = create_minimal_docx_bytes(paragraphs)
    text, warnings = extract_document_text(docx_bytes, "resume.docx")
    assert "Jane Doe" in text
    assert "jane.doe@example.com" in text
    assert "PyTorch" in text


def test_parse_docx_rejects_missing_document_xml():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/settings.xml", "<settings/>")
    corrupt_docx = buf.getvalue()

    with pytest.raises(DocumentParsingError, match="missing 'word/document.xml'"):
        parse_docx(corrupt_docx)


def test_parse_docx_rejects_excessive_zip_entries():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document><w:body/></w:document>")
        for i in range(MAX_DOCX_ENTRIES + 10):
            zf.writestr(f"word/media/image_{i}.png", b"fake image")
    bomb_docx = buf.getvalue()

    with pytest.raises(DocumentComplexityError, match="exceeds maximum allowable file entries"):
        parse_docx(bomb_docx)


def test_parse_docx_rejects_excessive_uncompressed_size(monkeypatch):
    docx_bytes = create_minimal_docx_bytes(["Valid paragraph"])
    orig_infolist = zipfile.ZipFile.infolist

    def fake_infolist(self):
        infos = orig_infolist(self)
        fake_info = zipfile.ZipInfo("word/huge_text.xml")
        fake_info.file_size = MAX_DOCX_UNCOMPRESSED_BYTES + 1024
        fake_info.compress_size = (MAX_DOCX_UNCOMPRESSED_BYTES + 1024) // 2  # ratio 2.0x, below ratio limit
        return infos + [fake_info]

    monkeypatch.setattr(zipfile.ZipFile, "infolist", fake_infolist)
    with pytest.raises(DocumentComplexityError, match="total uncompressed size .* exceeds maximum safety limit"):
        parse_docx(docx_bytes)


def test_parse_docx_rejects_suspicious_compression_ratio(monkeypatch):
    docx_bytes = create_minimal_docx_bytes(["Valid paragraph"])
    orig_infolist = zipfile.ZipFile.infolist

    def fake_infolist(self):
        infos = orig_infolist(self)
        fake_info = zipfile.ZipInfo("word/bomb.xml")
        fake_info.file_size = 5 * 1024 * 1024  # 5 MiB
        fake_info.compress_size = 500          # 500 bytes -> 10,000x ratio
        return infos + [fake_info]

    monkeypatch.setattr(zipfile.ZipFile, "infolist", fake_infolist)
    with pytest.raises(DocumentComplexityError, match="exhibits suspicious compression ratio"):
        parse_docx(docx_bytes)


# ============================================================================
# Minimal Text & Scan Warning Tests
# ============================================================================

def test_extract_document_text_warns_on_short_or_scanned_document():
    # Only 5 words
    short_pdf = create_minimal_pdf_bytes("Brief note only five words.")
    text, warnings = extract_document_text(short_pdf, "scanned_doc.pdf")
    assert any("minimal text" in w.lower() for w in warnings)


def test_parse_pdf_rejects_encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secure_password")
    buf = io.BytesIO()
    writer.write(buf)
    encrypted_pdf = buf.getvalue()

    with pytest.raises(DocumentParsingError, match="encrypted or password-protected"):
        parse_pdf(encrypted_pdf)
