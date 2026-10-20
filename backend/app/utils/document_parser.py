"""Document upload validation and text extraction for ScholarSwarm AI.

Provides streaming upload validation, magic byte inspection, ZIP bomb mitigation,
page and complexity boundaries, and safe text extraction for PDF and DOCX files.
Raw document contents are processed entirely in memory and are never persisted to disk.
"""

import io
import re
from typing import BinaryIO, List, Optional, Tuple
import xml.etree.ElementTree as ET
import zipfile

from fastapi import UploadFile
from pypdf import PdfReader
from pypdf.errors import PyPdfError


# ============================================================================
# Security Limits and Constants
# ============================================================================

DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB upload cap
MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MiB uncompressed cap
MAX_DOCX_ENTRIES = 500  # Maximum number of entries in zip archive
MAX_COMPRESSION_RATIO = 100.0  # Max compression ratio for zip bomb defense
MAX_PDF_PAGES = 50  # Maximum allowable PDF pages for single document
MAX_EXTRACTED_TEXT_CHARS = 100_000  # Cap extracted text length
MIN_DOCUMENT_WORDS_WARNING = 50  # Threshold to trigger scan/low-text warning

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


# ============================================================================
# Exceptions
# ============================================================================

class DocumentParserError(Exception):
    """Base exception for document parsing and validation failures."""
    pass


class UploadTooLargeError(DocumentParserError):
    """Raised when uploaded file exceeds the maximum allowable size."""
    pass


class InvalidDocumentFormatError(DocumentParserError):
    """Raised when file does not match allowed PDF/DOCX magic bytes or structure."""
    pass


class DocumentComplexityError(DocumentParserError):
    """Raised when document complexity violates defensive limits (ZIP bomb, page count)."""
    pass


class DocumentParsingError(DocumentParserError):
    """Raised when an unrecoverable extraction or corruption error occurs."""
    pass


# ============================================================================
# Streaming Upload Reader (Enforced During Ingestion)
# ============================================================================

async def read_upload_file_safely(
    upload_file: UploadFile,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    chunk_size: int = 64 * 1024,
) -> bytes:
    """Read an asynchronous FastAPI UploadFile in chunks, aborting early if oversized.

    Guards against memory exhaustion by checking the cumulative byte count on each chunk
    rather than waiting until the entire payload is loaded into memory.
    """
    total_bytes = 0
    chunks: List[bytes] = []

    while True:
        chunk = await upload_file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadTooLargeError(
                f"File upload exceeds maximum allowable size of {max_bytes} bytes "
                f"({max_bytes // (1024 * 1024)} MiB)."
            )
        chunks.append(chunk)

    return b"".join(chunks)


def read_stream_safely(
    stream: BinaryIO,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    chunk_size: int = 64 * 1024,
) -> bytes:
    """Read a synchronous binary stream in chunks, aborting early if oversized."""
    total_bytes = 0
    chunks: List[bytes] = []

    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadTooLargeError(
                f"Stream exceeds maximum allowable size of {max_bytes} bytes "
                f"({max_bytes // (1024 * 1024)} MiB)."
            )
        chunks.append(chunk)

    return b"".join(chunks)


# ============================================================================
# Magic Bytes and Format Detection
# ============================================================================

def detect_document_format(data: bytes, filename: Optional[str] = None) -> str:
    """Validate magic bytes and determine whether document is PDF or DOCX.

    Fails closed if the format is unsupported, spoofed, or ambiguous.
    """
    if len(data) < 4:
        raise InvalidDocumentFormatError("File payload is empty or too small to be a valid document.")

    # Check PDF magic bytes
    if data.startswith(PDF_MAGIC):
        return "pdf"

    # Check DOCX (ZIP archive containing [Content_Types].xml)
    if data.startswith(ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                namelist = zf.namelist()
                if "[Content_Types].xml" in namelist and any(
                    name.startswith("word/") for name in namelist
                ):
                    return "docx"
        except zipfile.BadZipFile as exc:
            raise InvalidDocumentFormatError(f"Corrupt or invalid ZIP structure: {exc}") from exc

        raise InvalidDocumentFormatError(
            "ZIP archive does not appear to be a valid DOCX document (missing [Content_Types].xml or word/ structure)."
        )

    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[-1].lower()

    raise InvalidDocumentFormatError(
        f"Unsupported or unrecognized file format. Only PDF and DOCX files are permitted. "
        f"(Provided extension: '{ext}' but signature does not match PDF or DOCX)."
    )


# ============================================================================
# PDF Extraction with Safety Limits
# ============================================================================

def parse_pdf(data: bytes) -> Tuple[str, List[str]]:
    """Extract text from PDF bytes with page limits and error handling."""
    warnings: List[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentParsingError(
                "PDF document is encrypted or password-protected; cannot extract text without credentials."
            )
        page_count = len(reader.pages)
    except DocumentParsingError:
        raise
    except (PyPdfError, ValueError, Exception) as exc:
        raise DocumentParsingError(f"Failed to parse PDF document: {exc}") from exc

    if page_count > MAX_PDF_PAGES:
        raise DocumentComplexityError(
            f"PDF exceeds maximum allowable limit of {MAX_PDF_PAGES} pages (found {page_count})."
        )

    text_parts: List[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            extracted = page.extract_text()
            if extracted:
                text_parts.append(extracted.strip())
        except Exception as exc:
            warnings.append(f"Unable to extract text from PDF page {idx + 1}: {exc}")

    full_text = "\n\n".join(text_parts).strip()
    return full_text, warnings


# ============================================================================
# DOCX Extraction with ZIP Bomb Defense
# ============================================================================

def parse_docx(data: bytes) -> Tuple[str, List[str]]:
    """Extract text from DOCX bytes with strict ZIP bomb and XML defenses."""
    warnings: List[str] = []

    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
    except zipfile.BadZipFile as exc:
        raise DocumentParsingError(f"Failed to open DOCX archive: {exc}") from exc

    with zf:
        infolist = zf.infolist()
        if len(infolist) > MAX_DOCX_ENTRIES:
            raise DocumentComplexityError(
                f"DOCX archive exceeds maximum allowable file entries ({len(infolist)} > {MAX_DOCX_ENTRIES})."
            )

        total_uncompressed = 0
        total_compressed = len(data)

        for info in infolist:
            total_uncompressed += info.file_size
            if info.file_size > 1024 * 1024:
                ratio = info.file_size / max(info.compress_size, 1)
                # If an individual entry expands by > 100x and is > 1MB, flag as zip bomb
                if ratio > MAX_COMPRESSION_RATIO:
                    raise DocumentComplexityError(
                        f"DOCX entry '{info.filename}' exhibits suspicious compression ratio ({ratio:.1f}x)."
                    )

        if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise DocumentComplexityError(
                f"DOCX archive total uncompressed size ({total_uncompressed} bytes) "
                f"exceeds maximum safety limit of {MAX_DOCX_UNCOMPRESSED_BYTES} bytes."
            )

        if "word/document.xml" not in zf.namelist():
            raise DocumentParsingError("Invalid DOCX archive: missing 'word/document.xml'.")

        try:
            xml_bytes = zf.read("word/document.xml")
        except Exception as exc:
            raise DocumentParsingError(f"Could not read 'word/document.xml': {exc}") from exc

    # Parse XML safely and extract paragraph text
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise DocumentParsingError(f"Failed to parse document XML: {exc}") from exc

    paragraphs: List[str] = []
    for elem in root.iter():
        if elem.tag.endswith("p"):
            text_pieces = [t.text for t in elem.iter() if t.tag.endswith("t") and t.text]
            if text_pieces:
                paragraph_text = "".join(text_pieces).strip()
                if paragraph_text:
                    paragraphs.append(paragraph_text)

    full_text = "\n\n".join(paragraphs).strip()
    return full_text, warnings


# ============================================================================
# Main Extraction Pipeline
# ============================================================================

def extract_document_text(
    data: bytes, filename: Optional[str] = None
) -> Tuple[str, List[str]]:
    """Validate format and extract text from in-memory document bytes.

    Returns:
        (extracted_text, warnings)
    """
    format_type = detect_document_format(data, filename)

    if format_type == "pdf":
        text, warnings = parse_pdf(data)
    elif format_type == "docx":
        text, warnings = parse_docx(data)
    else:
        raise InvalidDocumentFormatError(f"Unhandled document format: {format_type}")

    # Check for empty or scanned document (< 50 words)
    words = re.findall(r"\b\w+\b", text)
    if len(words) < MIN_DOCUMENT_WORDS_WARNING:
        warnings.append(
            f"Document yielded minimal text ({len(words)} words); document may be a scanned image, "
            "empty, or require OCR (OCR is disabled in this milestone)."
        )

    # Check extracted text size limit
    if len(text) > MAX_EXTRACTED_TEXT_CHARS:
        text = text[:MAX_EXTRACTED_TEXT_CHARS]
        warnings.append(
            f"Extracted text exceeded maximum length of {MAX_EXTRACTED_TEXT_CHARS} characters "
            "and was truncated."
        )

    return text, warnings
