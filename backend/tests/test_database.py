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
