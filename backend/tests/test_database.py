"""Unit and persistence tests for SQLite database operations.

Verifies table schema creation, session and event persistence, JSON serialization,
and foreign key constraint enforcement on temporary test databases.
"""

import os
import sqlite3
import tempfile
import pytest

from backend.app.database import (
    check_db_health,
    create_session,
    get_connection,
    get_pipeline_events,
    get_session,
    init_db,
    record_pipeline_event,
    update_session_status,
)


@pytest.fixture
def temp_db():
    """Create an isolated temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


def test_init_db_creates_expected_tables(temp_db: str):
    """Verify all required tables exist after initialization."""
    conn = get_connection(temp_db)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        expected = {"sessions", "opportunities", "sop_drafts", "pipeline_events", "pipeline_errors"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"
    finally:
        conn.close()


def test_foreign_keys_enforced(temp_db: str):
    """Verify SQLite foreign key constraints are enabled and enforced."""
    conn = get_connection(temp_db)
    try:
        # Check pragma
        cursor = conn.execute("PRAGMA foreign_keys;")
        assert cursor.fetchone()[0] == 1

        # Attempt inserting into opportunities with nonexistent session_id
        with pytest.raises(sqlite3.IntegrityError):
            with conn:
                conn.execute(
                    """
                    INSERT INTO opportunities (
                        opportunity_id, session_id, verification_tier, type, institution,
                        program_name, official_url, source_url
                    ) VALUES (
                        'opp-001', 'nonexistent-session', 'T1', 'scholarship', 'MIT',
                        'EECS', 'https://mit.edu', 'https://mit.edu'
                    );
                    """
                )
    finally:
        conn.close()


def test_session_lifecycle(temp_db: str):
    """Verify session creation, JSON profile serialization, retrieval, and status updates."""
    profile_data = {
        "name": "Jane Doe",
        "nationality": "Canada",
        "cgpa": 3.9,
        "cgpa_scale": 4.0,
        "field_of_study": "Bioengineering",
    }
    session = create_session(
        session_id="test-sess-100",
        status="pending",
        student_profile=profile_data,
        db_path=temp_db,
    )
    assert session["session_id"] == "test-sess-100"
    assert session["status"] == "pending"

    # Retrieve and check profile deserialization
    retrieved = get_session("test-sess-100", db_path=temp_db)
    assert retrieved is not None
    assert retrieved["status"] == "pending"
    assert retrieved["student_profile"]["name"] == "Jane Doe"
    assert retrieved["student_profile"]["cgpa"] == 3.9

    # Update status to completed
    update_session_status("test-sess-100", "completed", db_path=temp_db)
    updated = get_session("test-sess-100", db_path=temp_db)
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None


def test_pipeline_event_persistence(temp_db: str):
    """Verify pipeline event logging, JSON serialization, and chronological ordering."""
    create_session("sess-evt-01", status="running", db_path=temp_db)

    # Record two events
    record_pipeline_event(
        event_id="e-1",
        session_id="sess-evt-01",
        agent="SPA",
        event_type="profile_extracted",
        message="Profile extracted from resume.pdf",
        payload={"skills_found": 5},
        db_path=temp_db,
    )
    record_pipeline_event(
        event_id="e-2",
        session_id="sess-evt-01",
        agent="ORA",
        event_type="search_completed",
        message="Discovered 12 opportunity candidates",
        payload={"candidates_count": 12},
        db_path=temp_db,
    )

    events = get_pipeline_events("sess-evt-01", db_path=temp_db)
    assert len(events) == 2
    assert events[0]["agent"] == "SPA"
    assert events[0]["payload"]["skills_found"] == 5
    assert events[1]["agent"] == "ORA"
    assert events[1]["payload"]["candidates_count"] == 12


def test_check_db_health(temp_db: str):
    """Verify check_db_health reports connected on functioning database."""
    is_healthy, status = check_db_health(temp_db)
    assert is_healthy is True
    assert status == "connected"


def test_update_session_profile(temp_db: str):
    """Verify updating student profile JSON on existing session."""
    create_session("sess-update-01", status="running", db_path=temp_db)
    from backend.app.database import update_session_profile
    new_profile = {"name": "Updated Name", "cgpa": 3.8, "cgpa_scale": 4.0}
    update_session_profile("sess-update-01", new_profile, db_path=temp_db)

    session = get_session("sess-update-01", db_path=temp_db)
    assert session is not None
    assert session["student_profile"]["name"] == "Updated Name"
    assert session["student_profile"]["cgpa"] == 3.8


def test_pipeline_events_since_id_filtering(temp_db: str):
    """Verify since_id filters out previously retrieved events."""
    create_session("sess-filter-01", status="running", db_path=temp_db)

    record_pipeline_event("e-10", "sess-filter-01", "SPA", "step_1", "Step 1 done", db_path=temp_db)
    record_pipeline_event("e-20", "sess-filter-01", "ORA", "step_2", "Step 2 done", db_path=temp_db)
    record_pipeline_event("e-30", "sess-filter-01", "EEVA", "step_3", "Step 3 done", db_path=temp_db)

    # All events
    all_evts = get_pipeline_events("sess-filter-01", db_path=temp_db)
    assert len(all_evts) == 3

    # Events since e-10
    since_10 = get_pipeline_events("sess-filter-01", since_id="e-10", db_path=temp_db)
    assert len(since_10) == 2
    assert [e["event_id"] for e in since_10] == ["e-20", "e-30"]

    # Events since e-20
    since_20 = get_pipeline_events("sess-filter-01", since_id="e-20", db_path=temp_db)
    assert len(since_20) == 1
    assert since_20[0]["event_id"] == "e-30"

    # Events since latest e-30
    since_30 = get_pipeline_events("sess-filter-01", since_id="e-30", db_path=temp_db)
    assert len(since_30) == 0


def test_create_session_completed_sets_timestamp(temp_db: str):
    """Verify creating a session directly with status completed populates completed_at timestamp."""
    session = create_session("sess-comp-01", status="completed", db_path=temp_db)
    assert session["status"] == "completed"
    assert session["completed_at"] is not None

    retrieved = get_session("sess-comp-01", db_path=temp_db)
    assert retrieved is not None
    assert retrieved["status"] == "completed"
    assert retrieved["completed_at"] is not None


def test_pipeline_errors_persistence(temp_db: str):
    """Verify error logging and retrieval in pipeline_errors table."""
    from backend.app.database import get_pipeline_errors, record_pipeline_error

    create_session("sess-err-01", status="failed", db_path=temp_db)
    err = record_pipeline_error(
        error_id="err-1",
        session_id="sess-err-01",
        agent="SPA",
        error_type="DocumentParsingError",
        message="Corrupt PDF payload",
        recoverable=False,
        db_path=temp_db,
    )
    assert err["error_id"] == "err-1"
    assert err["recoverable"] is False

    errors = get_pipeline_errors("sess-err-01", db_path=temp_db)
    assert len(errors) == 1
    assert errors[0]["agent"] == "SPA"
    assert errors[0]["error_type"] == "DocumentParsingError"
    assert errors[0]["message"] == "Corrupt PDF payload"
