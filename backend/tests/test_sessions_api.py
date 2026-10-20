"""Deterministic integration tests for the Session and Event Polling API endpoints.

Tests session creation with PDF/DOCX uploads and pure application/json inputs,
lifecycle status ('completed'/'failed') and timestamp persistence,
actual streaming upload size limit enforcement without mocks,
session retrieval, and incremental event polling with since_id.
All database operations use isolated temporary SQLite databases.
"""

import io
import json
import os
import tempfile
from typing import Dict, Any
import zipfile
from fastapi.testclient import TestClient
import pytest

from backend.app.database import (
    DEFAULT_DB_PATH,
    get_connection,
    get_pipeline_errors,
    get_session,
    init_db,
    record_pipeline_event,
)
from backend.app.main import RequestSizeLimitMiddleware, app


@pytest.fixture
def isolated_db(monkeypatch):
    """Provide an isolated temporary database for API tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr("backend.app.database.DEFAULT_DB_PATH", path)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def client(isolated_db):
    """Create test client operating against the isolated temporary database."""
    with TestClient(app) as test_client:
        yield test_client


def make_pdf_bytes(content: str) -> bytes:
    escaped = content.replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 712 Td ({escaped}) Tj ET".encode("latin-1")
    length = len(stream)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n"
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"5 0 obj << /Length " + str(length).encode("ascii") + b" >> stream\n"
        + stream + b"\nendstream\nendobj\n"
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


def make_docx_bytes(paragraphs: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '</Types>',
        )
        xml_paras = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{xml_paras}</w:body></w:document>"
        )
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


# ============================================================================
# Session Creation Tests (POST /api/sessions)
# ============================================================================

def test_create_session_with_pdf(client: TestClient):
    pdf_content = (
        "Name: David Miller\n"
        "Email: david@mit.edu\n"
        "Bachelor of Science in Physics\n"
        "Cumulative GPA: 3.88/4.0\n"
        "Technical Skills: Python, MATLAB, Docker\n"
        "IELTS overall band score: 7.5\n"
    )
    pdf_bytes = make_pdf_bytes(pdf_content)

    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Quantum Computing",
            "target_degree": "masters",
            "preferred_countries": "USA, Germany",
        },
        files={"resume_file": ("resume.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    # Truthful terminal status and timestamp
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    assert data["created_at"] is not None

    profile = data["student_profile"]
    assert profile is not None
    assert profile["name"] == "David Miller"
    assert profile["email"] == "david@mit.edu"
    assert profile["cgpa"] == 3.88
    assert profile["cgpa_scale"] == 4.0
    assert profile["ielts_score"] == 7.5
    assert profile["field_of_study"] == "Quantum Computing"
    assert profile["target_degree"] == "masters"


def test_create_session_with_docx(client: TestClient):
    paragraphs = [
        "Name: Sarah Connor",
        "Email: sarah@resistance.org",
        "Technical Skills: Python, Linux, Cybersecurity",
        "CGPA: 3.9/4.0",
    ]
    docx_bytes = make_docx_bytes(paragraphs)

    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Cybersecurity",
            "target_degree": "phd",
        },
        files={"resume_file": ("resume.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    profile = data["student_profile"]
    assert profile["name"] == "Sarah Connor"
    assert profile["target_degree"] == "phd"


def test_create_session_with_direct_profile_form(client: TestClient):
    direct_json = json.dumps({
        "name": "Direct Form Student",
        "email": "direct@student.edu",
        "cgpa": 3.75,
        "cgpa_scale": 4.0,
    })

    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Robotics",
            "target_degree": "undergraduate",
            "direct_profile": direct_json,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    assert data["student_profile"]["name"] == "Direct Form Student"


# ============================================================================
# API Contract: Pure application/json Tests
# ============================================================================

def test_create_session_with_pure_json(client: TestClient):
    json_payload = {
        "field_of_study": "Artificial Intelligence",
        "target_degree": "masters",
        "preferred_countries": ["Canada", "Switzerland"],
        "name": "Ada Lovelace",
        "email": "ada@computing.org",
        "cgpa": 3.95,
        "cgpa_scale": 4.0,
        "ielts_score": 8.5,
    }

    response = client.post(
        "/api/sessions",
        json=json_payload,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    profile = data["student_profile"]
    assert profile["name"] == "Ada Lovelace"
    assert profile["email"] == "ada@computing.org"
    assert profile["cgpa"] == 3.95
    assert profile["field_of_study"] == "Artificial Intelligence"
    assert profile["target_degree"] == "masters"


def test_create_session_pure_json_missing_fields(client: TestClient):
    # Missing required field_of_study
    response = client.post(
        "/api/sessions",
        json={"target_degree": "masters"},
    )
    assert response.status_code == 400
    assert "field_of_study is required" in response.json()["detail"]


def test_create_session_pure_json_invalid_degree(client: TestClient):
    response = client.post(
        "/api/sessions",
        json={"field_of_study": "AI", "target_degree": "invalid_degree_level"},
    )
    assert response.status_code == 400
    assert "Invalid target_degree" in response.json()["detail"]


# ============================================================================
# Validation Failures and Lifecycle Status Tests
# ============================================================================

def test_create_session_rejects_missing_document_and_direct_profile(client: TestClient):
    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Data Science",
            "target_degree": "masters",
        },
    )
    assert response.status_code == 400
    assert "At least one document" in response.json()["detail"]


def test_create_session_rejects_invalid_degree_enum(client: TestClient):
    pdf_bytes = make_pdf_bytes("Some minimal content")
    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Law",
            "target_degree": "invalid_degree_level",
        },
        files={"resume_file": ("resume.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 400
    assert "Invalid target_degree" in response.json()["detail"]


def test_create_session_failure_persists_failed_status_and_error(client: TestClient, isolated_db: str):
    # Upload corrupted file that causes parser failure
    fake_pdf = b"NOT_A_REAL_PDF_FILE"
    response = client.post(
        "/api/sessions",
        data={
            "field_of_study": "Physics",
            "target_degree": "masters",
        },
        files={"resume_file": ("resume.pdf", fake_pdf, "application/pdf")},
    )
    assert response.status_code == 400
    assert "Resume processing error" in response.json()["detail"]

    # Verify that a session was persisted with status failed and completed_at is set
    conn = get_connection(isolated_db)
    try:
        cursor = conn.execute("SELECT session_id, status, completed_at FROM sessions ORDER BY rowid DESC LIMIT 1;")
        row = cursor.fetchone()
        assert row is not None
        assert row["status"] == "failed"
        assert row["completed_at"] is not None
        failed_session_id = row["session_id"]
    finally:
        conn.close()

    # Verify error was logged in pipeline_errors table without leaking raw document text
    errors = get_pipeline_errors(failed_session_id, db_path=isolated_db)
    assert len(errors) == 1
    assert errors[0]["agent"] == "SPA"
    assert "Resume processing error" in errors[0]["message"]


# ============================================================================
# Request Size Limiter & Streaming Tests (Real Transport Path, No Mocks)
# ============================================================================

def test_request_size_limit_rejects_oversized_content_length(client: TestClient):
    """Enforces 413 immediately if Content-Length exceeds allowable limit."""
    response = client.post(
        "/api/sessions",
        headers={"Content-Length": str(15 * 1024 * 1024)},
    )
    assert response.status_code == 413
    assert "exceeds maximum allowable limit" in response.json()["detail"]


def test_request_size_limit_streaming_receive_aborts_during_read(client: TestClient):
    """Enforces 413 while streaming chunks even when Content-Length is absent or low."""
    # Find the RequestSizeLimitMiddleware instance in the active middleware stack
    curr = client.app.middleware_stack
    middleware_found = None
    while curr:
        if isinstance(curr, RequestSizeLimitMiddleware):
            middleware_found = curr
            break
        curr = getattr(curr, "app", None)

    assert middleware_found is not None, "RequestSizeLimitMiddleware not found in stack"

    original_limit = middleware_found.max_bytes
    try:
        # Lower limit dynamically to 500 bytes for this test
        middleware_found.max_bytes = 500

        # Send multipart form upload with 1500 bytes and a misleading Content-Length of 400
        response = client.post(
            "/api/sessions",
            data={"field_of_study": "Computer Science", "target_degree": "masters"},
            files={"resume_file": ("resume.pdf", b"X" * 1500, "application/pdf")},
            headers={"Content-Length": "400"},
        )
        assert response.status_code == 413
        assert "exceeded maximum allowable limit of 500 bytes" in response.json()["detail"]
    finally:
        middleware_found.max_bytes = original_limit


# ============================================================================
# Session Retrieval Tests (GET /api/sessions/{session_id})
# ============================================================================

def test_get_session_details_existing(client: TestClient):
    pdf_bytes = make_pdf_bytes("Name: Robert Downey\nEmail: rd@stark.com\nGPA: 3.95/4.0")
    create_resp = client.post(
        "/api/sessions",
        data={"field_of_study": "Mechanical Engineering", "target_degree": "masters"},
        files={"resume_file": ("resume.pdf", pdf_bytes, "application/pdf")},
    )
    session_id = create_resp.json()["session_id"]

    get_resp = client.get(f"/api/sessions/{session_id}")
    assert get_resp.status_code == 200
    session_data = get_resp.json()
    assert session_data["session_id"] == session_id
    assert session_data["status"] == "completed"
    assert session_data["completed_at"] is not None
    assert session_data["student_profile"]["name"] == "Robert Downey"


def test_get_session_details_not_found(client: TestClient):
    response = client.get("/api/sessions/nonexistent_session_id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ============================================================================
# Pipeline Event Polling Tests (GET /api/sessions/{session_id}/events)
# ============================================================================

def test_poll_pipeline_events_with_since_id(client: TestClient):
    # 1. Create session (creates initial SYSTEM, SPA, and completed events)
    pdf_bytes = make_pdf_bytes("Name: Peter Parker\nEmail: spidey@mit.edu\nGPA: 3.8/4.0")
    create_resp = client.post(
        "/api/sessions",
        data={"field_of_study": "Biophysics", "target_degree": "phd"},
        files={"resume_file": ("resume.pdf", pdf_bytes, "application/pdf")},
    )
    session_id = create_resp.json()["session_id"]

    # 2. Get initial events
    events_resp = client.get(f"/api/sessions/{session_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 3
    evt1 = events[0]
    evt2 = events[1]
    evt3 = events[2]
    assert evt1["agent"] == "SYSTEM"
    assert evt1["event_type"] == "session_initialized"
    assert evt2["agent"] == "SPA"
    assert evt2["event_type"] == "profile_extracted"
    assert evt3["agent"] == "SYSTEM"
    assert evt3["event_type"] == "ingestion_completed"

    # 3. Poll with since_id = evt1["event_id"]
    delta_resp = client.get(f"/api/sessions/{session_id}/events?since_id={evt1['event_id']}")
    assert delta_resp.status_code == 200
    delta_events = delta_resp.json()
    assert len(delta_events) == len(events) - 1
    assert delta_events[0]["event_id"] == evt2["event_id"]

    # 4. Poll with latest event_id (should return empty list)
    latest_evt_id = events[-1]["event_id"]
    empty_resp = client.get(f"/api/sessions/{session_id}/events?since_id={latest_evt_id}")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []


def test_poll_events_session_not_found(client: TestClient):
    response = client.get("/api/sessions/unknown_session/events")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# ============================================================================
# Upload Resource Closure on Early Failures
# ============================================================================

def test_uploaded_file_closed_on_early_missing_field_failure(client: TestClient, monkeypatch):
    """Verify UploadFile.close is called when form validation fails before processing."""
    from starlette.datastructures import UploadFile as StarletteUploadFile
    closed_files = []
    original_close = StarletteUploadFile.close

    async def tracking_close(self):
        closed_files.append(self.filename)
        return await original_close(self)

    monkeypatch.setattr(StarletteUploadFile, "close", tracking_close)

    pdf_bytes = make_pdf_bytes("Applicant resume content")
    # Omit field_of_study (causes early validation error at lines 362-366)
    response = client.post(
        "/api/sessions",
        data={"target_degree": "masters"},
        files={"resume_file": ("resume_to_close.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 400
    assert "field_of_study is required" in response.json()["detail"]
    assert "resume_to_close.pdf" in closed_files


def test_uploaded_file_closed_on_invalid_target_degree_failure(client: TestClient, monkeypatch):
    """Verify UploadFile.close is called when target_degree enum validation fails."""
    from starlette.datastructures import UploadFile as StarletteUploadFile
    closed_files = []
    original_close = StarletteUploadFile.close

    async def tracking_close(self):
        closed_files.append(self.filename)
        return await original_close(self)

    monkeypatch.setattr(StarletteUploadFile, "close", tracking_close)

    pdf_bytes = make_pdf_bytes("Applicant resume content")
    response = client.post(
        "/api/sessions",
        data={"field_of_study": "Robotics", "target_degree": "unsupported_degree"},
        files={"resume_file": ("resume_invalid_degree.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 400
    assert "Invalid target_degree" in response.json()["detail"]
    assert "resume_invalid_degree.pdf" in closed_files


# ============================================================================
# Middleware Response Start Boundary Tests
# ============================================================================

@pytest.mark.anyio
async def test_middleware_does_not_send_duplicate_response_if_started():
    """Verify middleware safely returns without sending a second response if response already started."""
    from fastapi import HTTPException

    sent_messages = []

    async def mock_send(message):
        sent_messages.append(message)

    # Downstream app that starts response, then triggers size limit exception
    async def downstream_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        # Next read exceeds limit
        await receive()

    # Receive that triggers HTTPException(413)
    async def mock_receive():
        return {"type": "http.request", "body": b"A" * 1000}

    middleware = RequestSizeLimitMiddleware(downstream_app, max_bytes=500)
    scope = {"type": "http", "method": "POST", "headers": []}

    # Execute middleware
    await middleware(scope, mock_receive, mock_send)

    # Verify that only the initial http.response.start was sent, NOT a duplicate 413
    start_messages = [m for m in sent_messages if m.get("type") == "http.response.start"]
    assert len(start_messages) == 1
    assert start_messages[0]["status"] == 200


@pytest.mark.anyio
async def test_early_response_streaming_handles_runtime_error_cleanly():
    """Verify middleware safely terminates without duplicate response start when downstream raises RuntimeError."""
    sent_messages = []

    async def mock_send(message):
        sent_messages.append(message)

    async def downstream_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("Caught handled exception, but response already started.")

    async def mock_receive():
        return {"type": "http.request", "body": b"A" * 10}

    middleware = RequestSizeLimitMiddleware(downstream_app, max_bytes=500)
    scope = {"type": "http", "method": "POST", "headers": []}

    await middleware(scope, mock_receive, mock_send)

    start_messages = [m for m in sent_messages if m.get("type") == "http.response.start"]
    assert len(start_messages) == 1
    assert start_messages[0]["status"] == 200


def test_uploaded_file_closed_on_success(client: TestClient, monkeypatch):
    """Verify that all UploadFile handles are closed on successful session creation."""
    from starlette.datastructures import UploadFile as StarletteUploadFile
    closed_files = []
    orig_close = StarletteUploadFile.close

    async def tracking_close(self):
        closed_files.append(self.filename)
        return await orig_close(self)

    monkeypatch.setattr(StarletteUploadFile, "close", tracking_close)

    pdf_bytes = make_pdf_bytes("Name: Success User\nEmail: success@test.edu\nGPA: 3.9/4.0")
    response = client.post(
        "/api/sessions",
        data={"field_of_study": "Robotics", "target_degree": "masters"},
        files={"resume_file": ("resume_success.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 201
    assert "resume_success.pdf" in closed_files


def test_uploaded_file_closed_on_document_parsing_failure(client: TestClient, monkeypatch):
    """Verify that UploadFile handles are closed when document validation fails."""
    from starlette.datastructures import UploadFile as StarletteUploadFile
    closed_files = []
    orig_close = StarletteUploadFile.close

    async def tracking_close(self):
        closed_files.append(self.filename)
        return await orig_close(self)

    monkeypatch.setattr(StarletteUploadFile, "close", tracking_close)

    response = client.post(
        "/api/sessions",
        data={"field_of_study": "Robotics", "target_degree": "masters"},
        files={"resume_file": ("corrupt.pdf", b"NOT_A_PDF", "application/pdf")},
    )
    assert response.status_code == 400
    assert "corrupt.pdf" in closed_files


def test_multipart_spool_remains_in_memory_under_spool_max_size(client: TestClient):
    """Verify that Starlette MultiPartParser uses in-memory SpooledTemporaryFile without disk rollover."""
    import starlette.formparsers
    from backend.app.utils.document_parser import DEFAULT_MAX_UPLOAD_BYTES

    assert starlette.formparsers.MultiPartParser.spool_max_size == DEFAULT_MAX_UPLOAD_BYTES

    spool = tempfile.SpooledTemporaryFile(max_size=starlette.formparsers.MultiPartParser.spool_max_size)
    spool.write(b"A" * (2 * 1024 * 1024))  # 2 MiB
    assert isinstance(spool._file, io.BytesIO), "Spooled temporary file rolled over to disk!"
    spool.close()


def test_request_size_limit_chunked_body_missing_content_length(client: TestClient):
    """Enforces 413 on chunked request bodies without Content-Length that exceed max_bytes."""
    curr = client.app.middleware_stack
    middleware_found = None
    while curr:
        if isinstance(curr, RequestSizeLimitMiddleware):
            middleware_found = curr
            break
        curr = getattr(curr, "app", None)

    assert middleware_found is not None
    original_limit = middleware_found.max_bytes
    try:
        middleware_found.max_bytes = 500

        def chunk_gen():
            yield b"field_of_study=AI&target_degree=masters&"
            yield b"data=" + b"Z" * 600

        response = client.post(
            "/api/sessions",
            content=chunk_gen(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413
        assert "exceeded maximum allowable limit of 500 bytes" in response.json()["detail"]
    finally:
        middleware_found.max_bytes = original_limit


def test_request_size_limit_invalid_content_length_header(client: TestClient):
    """Enforces 413 via streaming receive when Content-Length header is invalid (non-integer)."""
    curr = client.app.middleware_stack
    middleware_found = None
    while curr:
        if isinstance(curr, RequestSizeLimitMiddleware):
            middleware_found = curr
            break
        curr = getattr(curr, "app", None)

    assert middleware_found is not None
    original_limit = middleware_found.max_bytes
    try:
        middleware_found.max_bytes = 500
        response = client.post(
            "/api/sessions",
            data={"field_of_study": "AI", "target_degree": "masters"},
            files={"resume_file": ("r.pdf", b"X" * 1500, "application/pdf")},
            headers={"Content-Length": "not-an-integer"},
        )
        assert response.status_code == 413
        assert "exceeded maximum allowable limit of 500 bytes" in response.json()["detail"]
    finally:
        middleware_found.max_bytes = original_limit


def test_request_size_limit_allows_normal_request_within_limit(client: TestClient):
    """Allows normal request whose body is within limit."""
    response = client.post(
        "/api/sessions",
        json={"field_of_study": "Mathematics", "target_degree": "masters"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "completed"


def test_poll_pipeline_events_session_isolation(client: TestClient):
    """Verify event polling isolates events between different sessions."""
    pdf_bytes1 = make_pdf_bytes("Name: Student One\nGPA: 3.8/4.0")
    pdf_bytes2 = make_pdf_bytes("Name: Student Two\nGPA: 3.9/4.0")

    resp1 = client.post(
        "/api/sessions",
        data={"field_of_study": "Physics", "target_degree": "masters"},
        files={"resume_file": ("r1.pdf", pdf_bytes1, "application/pdf")},
    )
    resp2 = client.post(
        "/api/sessions",
        data={"field_of_study": "Chemistry", "target_degree": "phd"},
        files={"resume_file": ("r2.pdf", pdf_bytes2, "application/pdf")},
    )

    s1_id = resp1.json()["session_id"]
    s2_id = resp2.json()["session_id"]

    evts1 = client.get(f"/api/sessions/{s1_id}/events").json()
    evts2 = client.get(f"/api/sessions/{s2_id}/events").json()

    assert all(e["session_id"] == s1_id for e in evts1)
    assert all(e["session_id"] == s2_id for e in evts2)
    s1_ids = {e["event_id"] for e in evts1}
    s2_ids = {e["event_id"] for e in evts2}
    assert s1_ids.isdisjoint(s2_ids)


def test_poll_pipeline_events_unknown_since_id(client: TestClient):
    """Verify polling with an unknown since_id returns an empty list without error."""
    pdf_bytes = make_pdf_bytes("Name: Student Three\nGPA: 3.7/4.0")
    resp = client.post(
        "/api/sessions",
        data={"field_of_study": "Biology", "target_degree": "masters"},
        files={"resume_file": ("r3.pdf", pdf_bytes, "application/pdf")},
    )
    s_id = resp.json()["session_id"]
    evts = client.get(f"/api/sessions/{s_id}/events?since_id=nonexistent_event_999").json()
    assert evts == []


def test_poll_pipeline_events_cross_session_since_id(client: TestClient):
    """Verify using a since_id from another session returns empty list and does not leak events."""
    resp1 = client.post(
        "/api/sessions",
        json={"field_of_study": "Math", "target_degree": "masters"},
    )
    resp2 = client.post(
        "/api/sessions",
        json={"field_of_study": "CS", "target_degree": "phd"},
    )
    s1_id = resp1.json()["session_id"]
    s2_id = resp2.json()["session_id"]

    s1_evts = client.get(f"/api/sessions/{s1_id}/events").json()
    first_s1_evt = s1_evts[0]["event_id"]

    # Poll session 2 with session 1's event_id as since_id
    cross_evts = client.get(f"/api/sessions/{s2_id}/events?since_id={first_s1_evt}").json()
    assert cross_evts == []
