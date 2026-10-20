"""FastAPI entry point for ScholarSwarm AI backend.

Exposes application health diagnostics, document ingestion pipeline, session management,
and incremental pipeline event polling.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
import uuid

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
import starlette.formparsers
from starlette.datastructures import UploadFile

from backend.agents.spa import extract_student_profile
from backend.app.database import (
    check_db_health,
    create_session,
    get_pipeline_events,
    get_session,
    init_db,
    record_pipeline_error,
    record_pipeline_event,
)
from backend.app.schemas import (
    AgentRole,
    DegreeLevel,
    HealthResponse,
    StudentProfile,
)
from backend.app.utils.document_parser import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DocumentComplexityError,
    DocumentParsingError,
    InvalidDocumentFormatError,
    UploadTooLargeError,
    extract_document_text,
    read_upload_file_safely,
)


# ============================================================================
# Upload Spooling & Privacy Configuration
# ============================================================================

# Configure Starlette's multipart spooling threshold to match the 10 MiB limit.
# For all requests within the 10 MiB limit, UploadFile data remains strictly
# in memory in SpooledTemporaryFile and does not roll over to disk.
starlette.formparsers.MultiPartParser.spool_max_size = DEFAULT_MAX_UPLOAD_BYTES


# ============================================================================
# Request Size Limiter Middleware
# ============================================================================

class RequestSizeLimitMiddleware:
    """ASGI middleware that enforces upload size limits at the transport boundary.

    Guards against oversized requests even when Content-Length is missing, invalid, or misleading
    (e.g., chunked transfer encoding) by monitoring cumulative stream chunks as they arrive.
    Rejects oversized requests with HTTP 413 before multipart parsing can allocate excessive memory.

    Limitation: If an application endpoint begins streaming an HTTP response (sending http.response.start)
    before fully consuming the request body, and subsequent body chunks exceed max_bytes, the middleware
    cannot alter the already-committed HTTP status code to 413. In accordance with the ASGI specification,
    the middleware suppresses duplicate response start messages and safely terminates the stream without
    sending a second response.
    """

    def __init__(self, app: Any, max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Early Content-Length check if header is present
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    content_length = int(value.decode("ascii"))
                    if content_length > self.max_bytes:
                        response = Response(
                            content=json.dumps({
                                "detail": f"Request body exceeds maximum allowable limit of {self.max_bytes} bytes ({self.max_bytes // (1024 * 1024)} MiB)."
                            }),
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            media_type="application/json",
                        )
                        await response(scope, receive, send)
                        return
                except ValueError:
                    pass
                break

        # 2. Cumulative streaming receive check with response start tracking
        bytes_received = 0
        response_started = False

        async def tracked_send(message: Dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive() -> Dict[str, Any]:
            nonlocal bytes_received
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                bytes_received += len(chunk)
                if bytes_received > self.max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Request stream exceeded maximum allowable limit of {self.max_bytes} bytes ({self.max_bytes // (1024 * 1024)} MiB) while reading.",
                    )
            return message

        try:
            await self.app(scope, limited_receive, tracked_send)
        except HTTPException as exc:
            if not response_started:
                response = Response(
                    content=json.dumps({"detail": exc.detail}),
                    status_code=exc.status_code,
                    media_type="application/json",
                )
                await response(scope, receive, send)
            else:
                # Response headers have already been sent; sending a second response start
                # violates the ASGI specification. Safely return to terminate the stream.
                return
        except RuntimeError as exc:
            if response_started and "response already started" in str(exc).lower():
                # Downstream framework caught the exception but could not send a 413
                # because the response had already started. Safely terminate the stream.
                return
            raise


# ============================================================================
# Application Lifecycle & Instantiation
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on application startup."""
    init_db()
    yield


app = FastAPI(
    title="ScholarSwarm AI Backend",
    description="Multi-Agent Scholarship Discovery and Verification Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

# Enforce streaming request size limit before routing/body parsing
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=DEFAULT_MAX_UPLOAD_BYTES)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="Application Health Check",
    description="Validates service health and SQLite database connectivity via SELECT 1.",
)
def get_health(response: Response) -> HealthResponse:
    """Execute connectivity check against SQLite persistence layer.

    Returns HTTP 200 with status=healthy when database responds.
    Returns HTTP 503 with status=unhealthy when database connectivity fails.
    """
    is_healthy, db_status = check_db_health()
    now = datetime.now(timezone.utc)

    if is_healthy:
        response.status_code = status.HTTP_200_OK
        return HealthResponse(
            status="healthy",
            database="connected",
            version="0.1.0",
            timestamp=now,
        )

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="unhealthy",
        database="disconnected",
        version="0.1.0",
        timestamp=now,
    )


# ============================================================================
# Session & Ingestion Endpoints (Milestone 1B)
# ============================================================================

def _parse_countries(pref: Any) -> List[str]:
    """Normalize preferred countries from JSON list, list, or comma-separated string."""
    if not pref:
        return []
    if isinstance(pref, list):
        return [str(c).strip() for c in pref if str(c).strip()]
    clean = str(pref).strip()
    if clean.startswith("["):
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, list):
                return [str(c).strip() for c in parsed if str(c).strip()]
        except json.JSONDecodeError:
            pass
    return [c.strip() for c in clean.split(",") if c.strip()]


@app.post(
    "/api/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Create Research Session & Ingest Documents or Profile",
    description="Accepts either multipart/form-data with resume/transcript files or application/json with student profile data. Runs the deterministic Student Profile Agent (SPA), creates the session record with terminal status 'completed', and emits initialization events.",
)
async def create_research_session(request: Request) -> Dict[str, Any]:
    """Ingest resume/transcript files or direct profile and initialize student research session."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    content_type = request.headers.get("content-type", "").lower()

    # ========================================================================
    # Branch A: Pure application/json Submission
    # ========================================================================
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed JSON payload: {exc}",
            ) from exc

        if not isinstance(body, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON body must be an object.",
            )

        field_of_study = body.get("field_of_study")
        target_degree = body.get("target_degree")

        if not field_of_study or not isinstance(field_of_study, str) or not field_of_study.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="field_of_study is required and must be a non-empty string.",
            )

        if not target_degree or not isinstance(target_degree, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_degree is required.",
            )

        try:
            target_degree_enum = DegreeLevel(target_degree.lower().strip())
        except (ValueError, AttributeError):
            valid_degrees = [d.value for d in DegreeLevel]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_degree '{target_degree}'. Allowed values: {valid_degrees}",
            )

        countries = _parse_countries(body.get("preferred_countries"))

        # Build StudentProfile from direct_profile nested object or top-level fields
        profile_data = body.get("direct_profile")
        if isinstance(profile_data, dict):
            profile_dict_input = profile_data.copy()
        else:
            profile_dict_input = body.copy()

        profile_dict_input["session_id"] = session_id
        profile_dict_input["field_of_study"] = field_of_study.strip()
        profile_dict_input["target_degree"] = target_degree_enum.value
        if countries:
            profile_dict_input["preferred_countries"] = countries

        try:
            profile = StudentProfile(**profile_dict_input)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid student profile data: {exc}",
            ) from exc

        # Persist session with terminal status 'completed'
        profile_dict = profile.model_dump(mode="json")
        session_record = create_session(
            session_id=session_id,
            status="completed",
            student_profile=profile_dict,
        )

        # Emit events
        evt1_id = f"evt_{uuid.uuid4().hex[:10]}"
        record_pipeline_event(
            event_id=evt1_id,
            session_id=session_id,
            agent=AgentRole.SYSTEM.value,
            event_type="session_initialized",
            message="Session created from direct profile submission.",
            payload={"field_of_study": field_of_study, "target_degree": target_degree_enum.value},
        )

        evt2_id = f"evt_{uuid.uuid4().hex[:10]}"
        student_label = profile.name or "Applicant"
        record_pipeline_event(
            event_id=evt2_id,
            session_id=session_id,
            agent=AgentRole.SPA.value,
            event_type="profile_extracted",
            message=f"Student Profile registered for {student_label}.",
            payload={"student_name": profile.name, "skills_count": len(profile.skills_extracted)},
        )

        evt3_id = f"evt_{uuid.uuid4().hex[:10]}"
        record_pipeline_event(
            event_id=evt3_id,
            session_id=session_id,
            agent=AgentRole.SYSTEM.value,
            event_type="ingestion_completed",
            message="Student profile ingestion completed successfully.",
            payload={"status": "completed"},
        )

        return session_record

    # ========================================================================
    # Branch B: multipart/form-data File Upload Submission
    # ========================================================================
    try:
        form = await request.form()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse form data: {exc}",
        ) from exc

    field_of_study = form.get("field_of_study")
    target_degree = form.get("target_degree")
    preferred_countries_raw = form.get("preferred_countries")
    github_url = form.get("github_url")
    direct_profile_raw = form.get("direct_profile")

    raw_resume = form.get("resume_file")
    raw_transcript = form.get("transcript_file")

    resume_file: Optional[UploadFile] = raw_resume if isinstance(raw_resume, UploadFile) else None
    transcript_file: Optional[UploadFile] = raw_transcript if isinstance(raw_transcript, UploadFile) else None

    # Collect all UploadFile handles in form to guarantee complete resource disposal
    all_upload_files: List[UploadFile] = [
        val for _, val in form.multi_items() if isinstance(val, UploadFile)
    ]

    # Enclose all post-parsing form operations in try/finally to guarantee resource cleanup
    try:
        # Validate required form fields
        if not field_of_study or not str(field_of_study).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="field_of_study is required and cannot be empty.",
            )

        if not target_degree or not str(target_degree).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target_degree is required.",
            )

        try:
            target_degree_enum = DegreeLevel(str(target_degree).lower().strip())
        except (ValueError, AttributeError):
            valid_degrees = [d.value for d in DegreeLevel]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid target_degree '{target_degree}'. Allowed values: {valid_degrees}",
            )

        countries = _parse_countries(preferred_countries_raw)

        if not resume_file and not transcript_file and not direct_profile_raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one document (resume_file) or direct_profile must be provided.",
            )

        if direct_profile_raw:
            try:
                p_data = json.loads(str(direct_profile_raw))
                p_data["session_id"] = session_id
                p_data["field_of_study"] = str(field_of_study).strip()
                p_data["target_degree"] = target_degree_enum.value
                if countries:
                    p_data["preferred_countries"] = countries
                profile = StudentProfile(**p_data)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid direct_profile data: {exc}",
                ) from exc
        else:
            extracted_texts: List[str] = []
            document_warnings: List[str] = []

            if resume_file:
                try:
                    resume_bytes = await read_upload_file_safely(resume_file)
                except UploadTooLargeError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=str(exc),
                    ) from exc

                try:
                    resume_text, warnings = extract_document_text(
                        resume_bytes, filename=resume_file.filename
                    )
                    extracted_texts.append(resume_text)
                    document_warnings.extend(warnings)
                except (InvalidDocumentFormatError, DocumentComplexityError, DocumentParsingError) as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Resume processing error: {exc}",
                    ) from exc

            if transcript_file:
                try:
                    transcript_bytes = await read_upload_file_safely(transcript_file)
                except UploadTooLargeError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=str(exc),
                    ) from exc

                try:
                    transcript_text, warnings = extract_document_text(
                        transcript_bytes, filename=transcript_file.filename
                    )
                    extracted_texts.append(transcript_text)
                    document_warnings.extend(warnings)
                except (InvalidDocumentFormatError, DocumentComplexityError, DocumentParsingError) as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Transcript processing error: {exc}",
                    ) from exc

            combined_doc_text = "\n\n".join(extracted_texts)

            # Run deterministic Student Profile Agent (SPA)
            try:
                profile = extract_student_profile(
                    session_id=session_id,
                    document_text=combined_doc_text,
                    field_of_study=str(field_of_study).strip(),
                    target_degree=target_degree_enum,
                    preferred_countries=countries,
                    github_url=str(github_url) if github_url else None,
                    document_warnings=document_warnings,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"SPA profile extraction failed: {exc}",
                ) from exc

    except HTTPException as exc:
        # On ingestion failure, record session failure state consistently without leaking raw text
        if (
            exc.status_code != status.HTTP_413_CONTENT_TOO_LARGE
            and any(phrase in str(exc.detail) for phrase in ("Resume processing error", "Transcript processing error", "SPA profile extraction failed"))
        ):
            create_session(session_id=session_id, status="failed")
            err_id = f"err_{uuid.uuid4().hex[:10]}"
            record_pipeline_error(
                error_id=err_id,
                session_id=session_id,
                agent=AgentRole.SPA.value,
                error_type="IngestionError",
                message=str(exc.detail),
                recoverable=False,
            )
            evt_fail_id = f"evt_{uuid.uuid4().hex[:10]}"
            record_pipeline_event(
                event_id=evt_fail_id,
                session_id=session_id,
                agent=AgentRole.SPA.value,
                event_type="ingestion_failed",
                message=f"Document parsing failed: {exc.detail}",
                payload={"error_type": "IngestionError"},
            )
        raise exc

    finally:
        # Guarantee closure and disposal of all uploaded file resources
        for uf in all_upload_files:
            try:
                await uf.close()
            except Exception:
                pass

    # Persist session with terminal status 'completed'
    profile_dict = profile.model_dump(mode="json")
    session_record = create_session(
        session_id=session_id,
        status="completed",
        student_profile=profile_dict,
    )

    # Emit initial pipeline lifecycle events
    evt1_id = f"evt_{uuid.uuid4().hex[:10]}"
    record_pipeline_event(
        event_id=evt1_id,
        session_id=session_id,
        agent=AgentRole.SYSTEM.value,
        event_type="session_initialized",
        message="Session created and ingestion pipeline completed.",
        payload={"field_of_study": str(field_of_study), "target_degree": target_degree_enum.value},
    )

    evt2_id = f"evt_{uuid.uuid4().hex[:10]}"
    student_label = profile.name or "Applicant"
    record_pipeline_event(
        event_id=evt2_id,
        session_id=session_id,
        agent=AgentRole.SPA.value,
        event_type="profile_extracted",
        message=f"Student Profile Agent parsed profile for {student_label} with {len(profile.skills_extracted)} skills.",
        payload={
            "student_name": profile.name,
            "skills_count": len(profile.skills_extracted),
            "github_repos_count": len(profile.github_repos),
            "cgpa": profile.cgpa,
            "cgpa_scale": profile.cgpa_scale,
            "warnings_count": len(profile.parse_warnings),
        },
    )

    evt3_id = f"evt_{uuid.uuid4().hex[:10]}"
    record_pipeline_event(
        event_id=evt3_id,
        session_id=session_id,
        agent=AgentRole.SYSTEM.value,
        event_type="ingestion_completed",
        message="Ingestion pipeline and SPA execution finished.",
        payload={"status": "completed"},
    )

    return session_record


@app.get(
    "/api/sessions/{session_id}",
    summary="Retrieve Session Details & Profile",
    description="Fetches session state, status, timestamps, and validated StudentProfile.",
)
def get_session_details(session_id: str) -> Dict[str, Any]:
    """Retrieve session record by session_id."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return session


@app.get(
    "/api/sessions/{session_id}/events",
    summary="Poll Pipeline Events",
    description="Retrieve chronological pipeline events for a session, with cursor-based since_id filtering.",
)
def get_session_events(
    session_id: str,
    since_id: Optional[str] = Query(None, description="Cursor for delta polling; returns events after since_id"),
) -> List[Dict[str, Any]]:
    """Poll pipeline events for UI updates."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )

    return get_pipeline_events(session_id=session_id, since_id=since_id)
