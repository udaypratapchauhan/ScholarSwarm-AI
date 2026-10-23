"""SQLite persistence module for ScholarSwarm AI.

Initializes declarative database schemas, enforces foreign keys, provides JSON
serialization for structured collections, and supports health diagnostics.
"""

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_DB_PATH = os.environ.get("DATABASE_PATH", "scholarswarm.db")


# Global simulation hook for health check unit testing
_SIMULATE_DB_FAILURE = False


def set_simulate_db_failure(simulate: bool) -> None:
    """Toggle simulated database failure for health check testing."""
    global _SIMULATE_DB_FAILURE
    _SIMULATE_DB_FAILURE = simulate


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create a SQLite connection with foreign keys enabled and row factory set."""
    if _SIMULATE_DB_FAILURE:
        raise sqlite3.OperationalError("Simulated database failure for testing.")

    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize SQLite database tables, constraints, indexes, and apply conditional migrations."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript("""
            -- Sessions Table
            CREATE TABLE IF NOT EXISTS sessions (
                session_id      TEXT PRIMARY KEY,
                status          TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
                student_profile TEXT, -- JSON serialized StudentProfile
                created_at      TEXT NOT NULL,
                completed_at    TEXT
            );

            -- Opportunities Table
            CREATE TABLE IF NOT EXISTS opportunities (
                opportunity_id          TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                verification_tier       TEXT NOT NULL CHECK(verification_tier IN ('T1', 'T2', 'T3', 'T4')),
                type                    TEXT NOT NULL,
                institution             TEXT NOT NULL,
                program_name            TEXT NOT NULL,
                official_url            TEXT NOT NULL,
                canonical_url           TEXT,
                source_type             TEXT DEFAULT 'unknown',
                country                 TEXT,
                degree_level            TEXT,
                -- Requirements
                eligible_nationalities  TEXT, -- JSON list
                min_cgpa                REAL,
                cgpa_scale              REAL,
                english_test            TEXT,
                english_min_score       TEXT,
                gre_required            INTEGER,
                funding_amount_text     TEXT,
                funding_coverage        TEXT DEFAULT 'unknown',
                application_deadline    TEXT,
                deadlines               TEXT, -- JSON list of DeadlineEntry dicts
                effective_scholarship_deadline TEXT,
                effective_admission_deadline   TEXT,
                intake_session          TEXT,
                required_documents      TEXT, -- JSON list
                application_instructions TEXT,
                -- Grounding & Evidence
                evidence_excerpt        TEXT,
                source_url              TEXT NOT NULL,
                last_verified           TEXT,
                page_accessible         INTEGER DEFAULT 0,
                page_http_status        INTEGER,
                page_fetch_timestamp    TEXT,
                extraction_failed       INTEGER DEFAULT 0,
                cycle_status            TEXT DEFAULT 'uncertain',
                conflicting_info_flags  TEXT, -- JSON list
                -- Eligibility
                admission_eligible      TEXT DEFAULT 'unknown',
                admission_ineligible_reasons TEXT, -- JSON list
                scholarship_eligible    TEXT DEFAULT 'unknown',
                scholarship_ineligible_reasons TEXT, -- JSON list
                missing_student_fields  TEXT, -- JSON list
                -- Result Group & Ranking
                result_group            TEXT DEFAULT 'potentially_eligible',
                rank                    INTEGER,
                total_score             REAL,
                score_breakdown         TEXT, -- JSON object
                recommendation_rationale TEXT,
                confidence              TEXT,
                is_mock                 INTEGER DEFAULT 1,
                search_provider         TEXT DEFAULT 'mock',
                scale_conversion_required INTEGER DEFAULT 0,
                scale_conversion_explanation TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_opp_session ON opportunities(session_id);
            CREATE INDEX IF NOT EXISTS idx_opp_tier ON opportunities(verification_tier);

            -- SOP Drafts Table
            CREATE TABLE IF NOT EXISTS sop_drafts (
                draft_id                TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                opportunity_id          TEXT REFERENCES opportunities(opportunity_id) ON DELETE SET NULL,
                institution             TEXT NOT NULL,
                program_name            TEXT NOT NULL,
                sop_text                TEXT NOT NULL,
                word_count              INTEGER NOT NULL,
                cited_profile_elements  TEXT, -- JSON list
                missing_info_prompts    TEXT, -- JSON list
                suggested_revisions     TEXT, -- JSON list
                generated_at            TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sop_session ON sop_drafts(session_id);

            -- Pipeline Events Table (Append-only for frontend polling)
            CREATE TABLE IF NOT EXISTS pipeline_events (
                event_id        TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                agent           TEXT NOT NULL,
                event_type      TEXT NOT NULL,
                message         TEXT NOT NULL,
                payload         TEXT, -- JSON object
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_session ON pipeline_events(session_id);

            -- Pipeline Errors Table (Append-only diagnostics)
            CREATE TABLE IF NOT EXISTS pipeline_errors (
                error_id        TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                agent           TEXT NOT NULL,
                error_type      TEXT NOT NULL,
                message         TEXT NOT NULL,
                recoverable     INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_errors_session ON pipeline_errors(session_id);
            """)

            # Dynamic, non-destructive migration for databases created under previous milestones
            cursor = conn.execute("PRAGMA table_info(opportunities);")
            existing_cols = {row["name"] for row in cursor.fetchall()}
            migrations = [
                ("canonical_url", "TEXT"),
                ("source_type", "TEXT DEFAULT 'unknown'"),
                ("deadlines", "TEXT"),
                ("effective_scholarship_deadline", "TEXT"),
                ("effective_admission_deadline", "TEXT"),
                ("result_group", "TEXT DEFAULT 'potentially_eligible'"),
                ("is_mock", "INTEGER DEFAULT 1"),
                ("search_provider", "TEXT DEFAULT 'mock'"),
                ("scale_conversion_required", "INTEGER DEFAULT 0"),
                ("scale_conversion_explanation", "TEXT"),
            ]
            for col_name, col_def in migrations:
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col_name} {col_def};")

            # Index on result_group after column migration is guaranteed
            conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_group ON opportunities(result_group);")
    finally:
        conn.close()


def check_db_health(db_path: Optional[str] = None) -> Tuple[bool, str]:
    """Execute a simple query to verify database connectivity.

    Scope: Verifies that SQLite engine connects, reads via SELECT 1, and responds.
    Returns (True, "connected") if healthy, or (False, error_message) on failure.
    """
    try:
        conn = get_connection(db_path)
        try:
            cursor = conn.execute("SELECT 1;")
            result = cursor.fetchone()
            if result and result[0] == 1:
                return True, "connected"
            return False, "Unexpected query result"
        finally:
            conn.close()
    except Exception as exc:
        return False, str(exc)


# ============================================================================
# Session Operations
# ============================================================================

def create_session(
    session_id: str,
    status: str = "pending",
    student_profile: Optional[Dict[str, Any]] = None,
    completed_at: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new session record. Automatically sets completed_at if status is completed/failed."""
    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat()
    final_completed = completed_at
    if final_completed is None and status in ("completed", "failed"):
        final_completed = now_str

    profile_json = json.dumps(student_profile) if student_profile else None
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, status, student_profile, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (session_id, status, profile_json, now_str, final_completed),
            )
        return {
            "session_id": session_id,
            "status": status,
            "student_profile": student_profile,
            "created_at": now_str,
            "completed_at": final_completed,
        }
    finally:
        conn.close()


def get_session(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve session record by ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?;", (session_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "status": row["status"],
            "student_profile": json.loads(row["student_profile"]) if row["student_profile"] else None,
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
    finally:
        conn.close()


def update_session_status(
    session_id: str, status: str, db_path: Optional[str] = None
) -> None:
    """Update session status and record completion timestamp if applicable."""
    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat() if status in ("completed", "failed") else None
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions
                SET status = ?, completed_at = COALESCE(?, completed_at)
                WHERE session_id = ?;
                """,
                (status, now_str, session_id),
            )
    finally:
        conn.close()


def update_session_profile(
    session_id: str,
    student_profile: Dict[str, Any],
    db_path: Optional[str] = None,
) -> None:
    """Update session student profile JSON."""
    conn = get_connection(db_path)
    profile_json = json.dumps(student_profile)
    try:
        with conn:
            conn.execute(
                """
                UPDATE sessions
                SET student_profile = ?
                WHERE session_id = ?;
                """,
                (profile_json, session_id),
            )
    finally:
        conn.close()


def delete_session(session_id: str, db_path: Optional[str] = None) -> bool:
    """Delete a session record by ID; cascades to all child records via foreign keys."""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE session_id = ?;", (session_id,)
            )
            return cursor.rowcount > 0
    finally:
        conn.close()



# ============================================================================
# Pipeline Events Operations
# ============================================================================

def record_pipeline_event(
    event_id: str,
    session_id: str,
    agent: str,
    event_type: str,
    message: str,
    payload: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a structured event for the polling dashboard."""
    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload or {})
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO pipeline_events (event_id, session_id, agent, event_type, message, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (event_id, session_id, agent, event_type, message, payload_json, now_str),
            )
        return {
            "event_id": event_id,
            "session_id": session_id,
            "agent": agent,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
            "created_at": now_str,
        }
    finally:
        conn.close()


def get_pipeline_events(
    session_id: str,
    since_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve pipeline events for a session, optionally filtered after since_id."""
    conn = get_connection(db_path)
    try:
        if since_id:
            cursor = conn.execute(
                """
                SELECT * FROM pipeline_events
                WHERE session_id = ?
                  AND rowid > (
                      SELECT rowid FROM pipeline_events
                      WHERE event_id = ? AND session_id = ?
                  )
                ORDER BY rowid ASC;
                """,
                (session_id, since_id, session_id),
            )
        else:
            cursor = conn.execute(
                """
                SELECT * FROM pipeline_events
                WHERE session_id = ?
                ORDER BY rowid ASC;
                """,
                (session_id,),
            )
        events = []
        for row in cursor.fetchall():
            events.append({
                "event_id": row["event_id"],
                "session_id": row["session_id"],
                "agent": row["agent"],
                "event_type": row["event_type"],
                "message": row["message"],
                "payload": json.loads(row["payload"]) if row["payload"] else {},
                "created_at": row["created_at"],
            })
        return events
    finally:
        conn.close()


# ============================================================================
# Pipeline Errors Operations
# ============================================================================

def record_pipeline_error(
    error_id: str,
    session_id: str,
    agent: str,
    error_type: str,
    message: str,
    recoverable: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist a structured error record for diagnostics."""
    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO pipeline_errors (error_id, session_id, agent, error_type, message, recoverable, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (error_id, session_id, agent, error_type, message, 1 if recoverable else 0, now_str),
            )
        return {
            "error_id": error_id,
            "session_id": session_id,
            "agent": agent,
            "error_type": error_type,
            "message": message,
            "recoverable": recoverable,
            "created_at": now_str,
        }
    finally:
        conn.close()


def get_pipeline_errors(
    session_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all logged pipeline errors for a session."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT * FROM pipeline_errors
            WHERE session_id = ?
            ORDER BY rowid ASC;
            """,
            (session_id,),
        )
        errors = []
        for row in cursor.fetchall():
            errors.append({
                "error_id": row["error_id"],
                "session_id": row["session_id"],
                "agent": row["agent"],
                "error_type": row["error_type"],
                "message": row["message"],
                "recoverable": bool(row["recoverable"]),
                "created_at": row["created_at"],
            })
        return errors
    finally:
        conn.close()


# ============================================================================
# Serialization Helpers
# ============================================================================

def _enum_val(val: Any) -> Any:
    """Extract primitive string/number from Enum or return val as-is."""
    return val.value if hasattr(val, "value") else val


def _safe_json_dumps(val: Any, default_val: str = "[]") -> str:
    """Serialize value to JSON with defensive fallback."""
    if val is None:
        return default_val
    if isinstance(val, str):
        val_clean = val.strip()
        if (val_clean.startswith("[") and val_clean.endswith("]")) or (
            val_clean.startswith("{") and val_clean.endswith("}")
        ):
            return val_clean
    try:
        return json.dumps(val)
    except (TypeError, ValueError):
        return default_val


def _safe_json_loads(val: Any, default_factory: Any) -> Any:
    """Deserialize JSON string into Python structure with defensive fallback."""
    if val is None:
        return default_factory()
    if isinstance(val, (list, dict)):
        return val
    try:
        loaded = json.loads(val)
        return loaded if loaded is not None else default_factory()
    except (json.JSONDecodeError, TypeError, ValueError):
        return default_factory()


def _serialize_deadlines(deadlines_val: Any) -> str:
    """Serialize deadline entries list preserving all fields."""
    if not deadlines_val:
        return json.dumps([])
    serialized = []
    for d in deadlines_val:
        if hasattr(d, "model_dump"):
            serialized.append(d.model_dump(mode="json"))
        elif isinstance(d, dict):
            d_copy = dict(d)
            for k in ("deadline_date",):
                if isinstance(d_copy.get(k), (date, datetime)):
                    d_copy[k] = d_copy[k].isoformat()
            if hasattr(d_copy.get("deadline_type"), "value"):
                d_copy["deadline_type"] = d_copy["deadline_type"].value
            serialized.append(d_copy)
    return json.dumps(serialized)


# ============================================================================
# Opportunity CRUD Operations
# ============================================================================

def insert_opportunities(
    opportunities: List[Dict[str, Any]], db_path: Optional[str] = None
) -> None:
    """Batch insert opportunity records with validated JSON serialization."""
    if not opportunities:
        return

    conn = get_connection(db_path)
    records = []
    for opp in opportunities:
        app_dl = opp.get("application_deadline")
        if isinstance(app_dl, (date, datetime)):
            app_dl = app_dl.isoformat()

        eff_schol_dl = opp.get("effective_scholarship_deadline")
        if isinstance(eff_schol_dl, (date, datetime)):
            eff_schol_dl = eff_schol_dl.isoformat()

        eff_adm_dl = opp.get("effective_admission_deadline")
        if isinstance(eff_adm_dl, (date, datetime)):
            eff_adm_dl = eff_adm_dl.isoformat()

        last_v = opp.get("last_verified")
        if isinstance(last_v, (date, datetime)):
            last_v = last_v.isoformat()

        fetch_ts = opp.get("page_fetch_timestamp")
        if isinstance(fetch_ts, (date, datetime)):
            fetch_ts = fetch_ts.isoformat()

        gre_req = opp.get("gre_required")
        gre_int = None
        if gre_req is not None:
            gre_int = 1 if gre_req else 0

        page_acc = 1 if opp.get("page_accessible") else 0
        ext_failed = 1 if opp.get("extraction_failed") else 0

        sb = opp.get("score_breakdown")
        sb_json = json.dumps(sb) if sb is not None else None

        nat = opp.get("eligible_nationalities")
        nat_json = json.dumps(nat) if nat is not None else None

        records.append((
            opp["opportunity_id"],
            opp["session_id"],
            _enum_val(opp.get("verification_tier", "T1")),
            _enum_val(opp.get("type", "scholarship")),
            opp["institution"],
            opp["program_name"],
            opp["official_url"],
            opp.get("canonical_url"),
            _enum_val(opp.get("source_type", "unknown")),
            opp.get("country"),
            _enum_val(opp.get("degree_level")),
            nat_json,
            opp.get("min_cgpa"),
            opp.get("cgpa_scale"),
            opp.get("english_test"),
            opp.get("english_min_score"),
            gre_int,
            opp.get("funding_amount_text"),
            _enum_val(opp.get("funding_coverage", "unknown")),
            app_dl,
            _serialize_deadlines(opp.get("deadlines")),
            eff_schol_dl,
            eff_adm_dl,
            opp.get("intake_session"),
            _safe_json_dumps(opp.get("required_documents"), default_val="[]"),
            opp.get("application_instructions"),
            opp.get("evidence_excerpt"),
            opp.get("source_url", opp["official_url"]),
            last_v,
            page_acc,
            opp.get("page_http_status"),
            fetch_ts,
            ext_failed,
            _enum_val(opp.get("cycle_status", "uncertain")),
            _safe_json_dumps(opp.get("conflicting_info_flags"), default_val="[]"),
            _enum_val(opp.get("admission_eligible", "unknown")),
            _safe_json_dumps(opp.get("admission_ineligible_reasons"), default_val="[]"),
            _enum_val(opp.get("scholarship_eligible", "unknown")),
            _safe_json_dumps(opp.get("scholarship_ineligible_reasons"), default_val="[]"),
            _safe_json_dumps(opp.get("missing_student_fields"), default_val="[]"),
            _enum_val(opp.get("result_group", "potentially_eligible")),
            opp.get("rank"),
            opp.get("total_score"),
            sb_json,
            opp.get("recommendation_rationale"),
            opp.get("confidence"),
            1 if opp.get("is_mock", True) else 0,
            opp.get("search_provider", "mock"),
            1 if opp.get("scale_conversion_required") else 0,
            opp.get("scale_conversion_explanation"),
        ))

    insert_sql = """
    INSERT INTO opportunities (
        opportunity_id, session_id, verification_tier, type, institution, program_name,
        official_url, canonical_url, source_type, country, degree_level,
        eligible_nationalities, min_cgpa, cgpa_scale, english_test, english_min_score,
        gre_required, funding_amount_text, funding_coverage, application_deadline,
        deadlines, effective_scholarship_deadline, effective_admission_deadline,
        intake_session, required_documents, application_instructions,
        evidence_excerpt, source_url, last_verified, page_accessible,
        page_http_status, page_fetch_timestamp, extraction_failed, cycle_status,
        conflicting_info_flags, admission_eligible, admission_ineligible_reasons,
        scholarship_eligible, scholarship_ineligible_reasons, missing_student_fields,
        result_group, rank, total_score, score_breakdown, recommendation_rationale,
        confidence, is_mock, search_provider, scale_conversion_required, scale_conversion_explanation
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    );
    """
    try:
        with conn:
            conn.executemany(insert_sql, records)
    finally:
        conn.close()


def _row_to_opportunity_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert SQLite row to clean deserialized opportunity dictionary."""
    d = dict(row)
    # Deserialize JSON fields
    d["eligible_nationalities"] = _safe_json_loads(d.get("eligible_nationalities"), list) if d.get("eligible_nationalities") is not None else None
    d["required_documents"] = _safe_json_loads(d.get("required_documents"), list)
    d["conflicting_info_flags"] = _safe_json_loads(d.get("conflicting_info_flags"), list)
    d["admission_ineligible_reasons"] = _safe_json_loads(d.get("admission_ineligible_reasons"), list)
    d["scholarship_ineligible_reasons"] = _safe_json_loads(d.get("scholarship_ineligible_reasons"), list)
    d["missing_student_fields"] = _safe_json_loads(d.get("missing_student_fields"), list)
    d["deadlines"] = _safe_json_loads(d.get("deadlines"), list)
    d["score_breakdown"] = _safe_json_loads(d.get("score_breakdown"), lambda: None) if d.get("score_breakdown") is not None else None

    # Cast integer booleans and provenance
    d["gre_required"] = bool(d["gre_required"]) if d.get("gre_required") is not None else None
    d["page_accessible"] = bool(d.get("page_accessible", 0))
    d["extraction_failed"] = bool(d.get("extraction_failed", 0))
    d["is_mock"] = bool(d.get("is_mock", 1))
    d["search_provider"] = d.get("search_provider") or "mock"
    d["scale_conversion_required"] = bool(d.get("scale_conversion_required", 0))
    d["scale_conversion_explanation"] = d.get("scale_conversion_explanation")
    return d


def get_opportunities(
    session_id: str,
    tier: Optional[str] = None,
    result_group: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve opportunities for a session with optional tier and group filters."""
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM opportunities WHERE session_id = ?"
        params: List[Any] = [session_id]
        if tier:
            query += " AND verification_tier = ?"
            params.append(tier)
        if result_group:
            query += " AND result_group = ?"
            params.append(result_group)
        query += " ORDER BY CASE WHEN rank IS NULL THEN 1 ELSE 0 END, rank ASC, total_score DESC, opportunity_id ASC;"

        cursor = conn.execute(query, params)
        return [_row_to_opportunity_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_opportunity(
    opportunity_id: str, db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve a single opportunity by its ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM opportunities WHERE opportunity_id = ?;", (opportunity_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_opportunity_dict(row)
    finally:
        conn.close()


ALLOWED_OPPORTUNITY_UPDATE_FIELDS = frozenset({
    "verification_tier", "type", "institution", "program_name", "official_url",
    "canonical_url", "source_type", "country", "degree_level",
    "eligible_nationalities", "min_cgpa", "cgpa_scale", "english_test",
    "english_min_score", "gre_required", "funding_amount_text", "funding_coverage",
    "application_deadline", "deadlines", "effective_scholarship_deadline",
    "effective_admission_deadline", "intake_session", "required_documents",
    "application_instructions", "evidence_excerpt", "source_url", "last_verified",
    "page_accessible", "page_http_status", "page_fetch_timestamp",
    "extraction_failed", "cycle_status", "conflicting_info_flags",
    "admission_eligible", "admission_ineligible_reasons", "scholarship_eligible",
    "scholarship_ineligible_reasons", "missing_student_fields", "result_group",
    "rank", "total_score", "score_breakdown", "recommendation_rationale", "confidence",
    "is_mock", "search_provider", "scale_conversion_required", "scale_conversion_explanation",
})


def update_opportunity(
    opportunity: Dict[str, Any], db_path: Optional[str] = None
) -> bool:
    """Update an existing opportunity record with dynamic field updating."""
    opp_id = opportunity.get("opportunity_id")
    if not opp_id:
        raise ValueError("opportunity_id is required to update an opportunity.")

    fields = []
    params = []
    for k, v in opportunity.items():
        if k == "opportunity_id" or k not in ALLOWED_OPPORTUNITY_UPDATE_FIELDS:
            continue

        if k in (
            "application_deadline",
            "effective_scholarship_deadline",
            "effective_admission_deadline",
            "last_verified",
            "page_fetch_timestamp",
        ):
            val = v.isoformat() if isinstance(v, (date, datetime)) else v
        elif k == "gre_required":
            val = (1 if v else 0) if v is not None else None
        elif k in ("page_accessible", "extraction_failed", "is_mock", "scale_conversion_required"):
            val = 1 if v else 0
        elif k == "search_provider":
            val = str(v) if v is not None else "mock"
        elif k == "deadlines":
            val = _serialize_deadlines(v)
        elif k in ("eligible_nationalities", "score_breakdown"):
            val = json.dumps(v) if v is not None else None
        elif k in (
            "required_documents",
            "conflicting_info_flags",
            "admission_ineligible_reasons",
            "scholarship_ineligible_reasons",
            "missing_student_fields",
        ):
            val = _safe_json_dumps(v, default_val="[]")
        else:
            val = _enum_val(v)

        fields.append(f"{k} = ?")
        params.append(val)

    if not fields:
        # Check if record exists
        return get_opportunity(opp_id, db_path=db_path) is not None

    params.append(opp_id)
    sql = f"UPDATE opportunities SET {', '.join(fields)} WHERE opportunity_id = ?;"
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount > 0
    finally:
        conn.close()



# ============================================================================
# SOP Drafts CRUD Operations
# ============================================================================

def save_sop_draft(
    draft: Dict[str, Any], db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Persist or update an SOP draft record."""
    conn = get_connection(db_path)
    now_str = draft.get("generated_at")
    if not now_str:
        now_str = datetime.now(timezone.utc).isoformat()
    elif isinstance(now_str, (date, datetime)):
        now_str = now_str.isoformat()

    sql = """
    INSERT INTO sop_drafts (
        draft_id, session_id, opportunity_id, institution, program_name,
        sop_text, word_count, cited_profile_elements, missing_info_prompts,
        suggested_revisions, generated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(draft_id) DO UPDATE SET
        session_id = excluded.session_id,
        opportunity_id = excluded.opportunity_id,
        institution = excluded.institution,
        program_name = excluded.program_name,
        sop_text = excluded.sop_text,
        word_count = excluded.word_count,
        cited_profile_elements = excluded.cited_profile_elements,
        missing_info_prompts = excluded.missing_info_prompts,
        suggested_revisions = excluded.suggested_revisions,
        generated_at = excluded.generated_at;
    """
    cpe_json = _safe_json_dumps(draft.get("cited_profile_elements"), default_val="[]")
    mip_json = _safe_json_dumps(draft.get("missing_info_prompts"), default_val="[]")
    sr_json = _safe_json_dumps(draft.get("suggested_revisions"), default_val="[]")

    params = (
        draft["draft_id"],
        draft["session_id"],
        draft.get("opportunity_id"),
        draft["institution"],
        draft["program_name"],
        draft["sop_text"],
        draft["word_count"],
        cpe_json,
        mip_json,
        sr_json,
        now_str,
    )
    try:
        with conn:
            conn.execute(sql, params)
        return {
            "draft_id": draft["draft_id"],
            "session_id": draft["session_id"],
            "opportunity_id": draft.get("opportunity_id"),
            "institution": draft["institution"],
            "program_name": draft["program_name"],
            "sop_text": draft["sop_text"],
            "word_count": draft["word_count"],
            "cited_profile_elements": _safe_json_loads(cpe_json, list),
            "missing_info_prompts": _safe_json_loads(mip_json, list),
            "suggested_revisions": _safe_json_loads(sr_json, list),
            "generated_at": now_str,
        }
    finally:
        conn.close()


def get_sop_draft(
    session_id: str,
    opportunity_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve an SOP draft by session_id and optional opportunity_id."""
    conn = get_connection(db_path)
    try:
        if opportunity_id:
            cursor = conn.execute(
                """
                SELECT * FROM sop_drafts
                WHERE session_id = ? AND opportunity_id = ?
                ORDER BY generated_at DESC LIMIT 1;
                """,
                (session_id, opportunity_id),
            )
        else:
            cursor = conn.execute(
                """
                SELECT * FROM sop_drafts
                WHERE session_id = ?
                ORDER BY generated_at DESC LIMIT 1;
                """,
                (session_id,),
            )
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["cited_profile_elements"] = _safe_json_loads(d.get("cited_profile_elements"), list)
        d["missing_info_prompts"] = _safe_json_loads(d.get("missing_info_prompts"), list)
        d["suggested_revisions"] = _safe_json_loads(d.get("suggested_revisions"), list)
        return d
    finally:
        conn.close()
