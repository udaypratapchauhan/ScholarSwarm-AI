"""SQLite persistence module for ScholarSwarm AI.

Initializes declarative database schemas, enforces foreign keys, provides JSON
serialization for structured collections, and supports health diagnostics.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
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
    """Initialize SQLite database tables, constraints, and indexes."""
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
                -- Ranking
                rank                    INTEGER,
                total_score             REAL,
                score_breakdown         TEXT, -- JSON object
                recommendation_rationale TEXT,
                confidence              TEXT
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
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new session record."""
    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat()
    profile_json = json.dumps(student_profile) if student_profile else None
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, status, student_profile, created_at)
                VALUES (?, ?, ?, ?);
                """,
                (session_id, status, profile_json, now_str),
            )
        return {
            "session_id": session_id,
            "status": status,
            "student_profile": student_profile,
            "created_at": now_str,
            "completed_at": None,
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
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all pipeline events for a session in chronological order."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT * FROM pipeline_events
            WHERE session_id = ?
            ORDER BY created_at ASC;
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
