"""Unit and persistence tests for SQLite database operations.

Verifies table schema creation, session and event persistence, JSON serialization,
and foreign key constraint enforcement on temporary test databases.
"""

from datetime import date, datetime, timezone
import os
import sqlite3
import tempfile
import pytest

from backend.app.database import (
    check_db_health,
    create_session,
    delete_session,
    get_connection,
    get_opportunities,
    get_opportunity,
    get_pipeline_errors,
    get_pipeline_events,
    get_session,
    get_sop_draft,
    init_db,
    insert_opportunities,
    record_pipeline_error,
    record_pipeline_event,
    save_sop_draft,
    update_opportunity,
    update_session_profile,
    update_session_status,
)
from backend.app.schemas import (
    DeadlineEntry,
    DeadlineType,
    ResultGroup,
    SourceType,
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


# ============================================================================
# Phase 1: Opportunity CRUD, Cascades, Migrations & JSON Resilience
# ============================================================================

def test_insert_and_get_opportunities_full_roundtrip(temp_db: str):
    """Verify batch inserting and retrieving opportunity records with complete JSON field preservation."""
    create_session("sess-opp-01", status="running", db_path=temp_db)

    opp = {
        "opportunity_id": "opp-101",
        "session_id": "sess-opp-01",
        "verification_tier": "T4",
        "type": "scholarship",
        "institution": "ETH Zurich",
        "program_name": "Excellence Scholarship",
        "official_url": "https://ethz.ch/excellence",
        "canonical_url": "https://www.ethz.ch/en/studies/excellence",
        "source_type": "official_provider",
        "country": "Switzerland",
        "degree_level": "masters",
        "eligible_nationalities": ["Switzerland", "International"],
        "min_cgpa": 3.8,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.5",
        "gre_required": False,
        "funding_amount_text": "Full tuition waiver and living stipend",
        "funding_coverage": "full",
        "application_deadline": date(2026, 12, 15),
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-12-15",
                "deadline_time": "23:59",
                "timezone": "CET",
                "intake_cycle": "Fall 2027",
                "raw_text": "Scholarship application deadline: December 15, 2026 at 23:59 CET",
                "is_inferred_year": False,
            }
        ],
        "effective_scholarship_deadline": date(2026, 12, 15),
        "effective_admission_deadline": date(2027, 1, 15),
        "intake_session": "Fall 2027",
        "required_documents": ["Transcripts", "SOP", "CV", "2 Letters of Recommendation"],
        "application_instructions": "Submit via the online ETH e-apply portal.",
        "evidence_excerpt": "The Excellence Scholarship & Opportunity Programme covers the full study and living costs...",
        "source_url": "https://ethz.ch/excellence",
        "last_verified": datetime.now(timezone.utc),
        "page_accessible": True,
        "page_http_status": 200,
        "extraction_failed": False,
        "cycle_status": "current",
        "conflicting_info_flags": [],
        "admission_eligible": "eligible",
        "admission_ineligible_reasons": [],
        "scholarship_eligible": "eligible",
        "scholarship_ineligible_reasons": [],
        "missing_student_fields": [],
        "result_group": "confirmed_eligible",
        "rank": 1,
        "total_score": 96.5,
        "score_breakdown": {
            "field_alignment": 30.0,
            "funding_coverage": 25.0,
            "deadline_proximity": 20.0,
            "eligibility_clarity": 15.0,
            "data_completeness": 6.5,
        },
        "recommendation_rationale": "High-match fully funded opportunity with confirmed eligibility.",
        "confidence": "high",
    }

    insert_opportunities([opp], db_path=temp_db)

    results = get_opportunities("sess-opp-01", db_path=temp_db)
    assert len(results) == 1
    ret = results[0]

    assert ret["opportunity_id"] == "opp-101"
    assert ret["session_id"] == "sess-opp-01"
    assert ret["canonical_url"] == "https://www.ethz.ch/en/studies/excellence"
    assert ret["source_type"] == "official_provider"
    assert ret["eligible_nationalities"] == ["Switzerland", "International"]
    assert ret["gre_required"] is False
    assert ret["page_accessible"] is True
    assert ret["extraction_failed"] is False
    assert ret["result_group"] == "confirmed_eligible"
    assert ret["effective_scholarship_deadline"] == "2026-12-15"
    assert ret["effective_admission_deadline"] == "2027-01-15"
    assert len(ret["deadlines"]) == 1
    assert ret["deadlines"][0]["timezone"] == "CET"
    assert ret["deadlines"][0]["deadline_time"] == "23:59"
    assert ret["score_breakdown"]["field_alignment"] == 30.0
    assert ret["total_score"] == 96.5


def test_get_opportunities_tier_and_group_filtering(temp_db: str):
    """Verify filtering opportunities by verification tier and result group."""
    create_session("sess-filt-01", status="running", db_path=temp_db)

    base = {
        "session_id": "sess-filt-01",
        "institution": "University of Toronto",
        "program_name": "CS M.Sc.",
        "official_url": "https://utoronto.ca/cs",
    }
    opps = [
        dict(base, opportunity_id="o-1", verification_tier="T1", result_group="potentially_eligible"),
        dict(base, opportunity_id="o-2", verification_tier="T4", result_group="confirmed_eligible"),
        dict(base, opportunity_id="o-3", verification_tier="T4", result_group="ineligible"),
    ]
    insert_opportunities(opps, db_path=temp_db)

    # Filter by tier T4
    t4_opps = get_opportunities("sess-filt-01", tier="T4", db_path=temp_db)
    assert len(t4_opps) == 2
    assert {o["opportunity_id"] for o in t4_opps} == {"o-2", "o-3"}

    # Filter by result_group confirmed_eligible
    confirmed = get_opportunities("sess-filt-01", result_group="confirmed_eligible", db_path=temp_db)
    assert len(confirmed) == 1
    assert confirmed[0]["opportunity_id"] == "o-2"

    # Filter by both tier T4 and group ineligible
    ineligible = get_opportunities("sess-filt-01", tier="T4", result_group="ineligible", db_path=temp_db)
    assert len(ineligible) == 1
    assert ineligible[0]["opportunity_id"] == "o-3"

    # Filter with non-matching filter returns empty list
    none_match = get_opportunities("sess-filt-01", tier="T3", db_path=temp_db)
    assert len(none_match) == 0


def test_get_opportunity_single(temp_db: str):
    """Verify single opportunity retrieval by opportunity_id."""
    create_session("sess-single-01", status="running", db_path=temp_db)
    insert_opportunities([
        {
            "opportunity_id": "opp-target-001",
            "session_id": "sess-single-01",
            "institution": "McGill",
            "program_name": "AI Fellowship",
            "official_url": "https://mcgill.ca/ai",
            "verification_tier": "T2",
            "result_group": "potentially_eligible",
        }
    ], db_path=temp_db)

    opp = get_opportunity("opp-target-001", db_path=temp_db)
    assert opp is not None
    assert opp["institution"] == "McGill"
    assert opp["verification_tier"] == "T2"

    missing = get_opportunity("opp-nonexistent", db_path=temp_db)
    assert missing is None


def test_update_opportunity(temp_db: str):
    """Verify updating existing opportunity record attributes."""
    create_session("sess-upd-01", status="running", db_path=temp_db)
    insert_opportunities([
        {
            "opportunity_id": "opp-upd-001",
            "session_id": "sess-upd-01",
            "institution": "Stanford",
            "program_name": "Knight-Hennessy",
            "official_url": "https://knight-hennessy.stanford.edu",
            "verification_tier": "T1",
            "result_group": "potentially_eligible",
        }
    ], db_path=temp_db)

    # Perform update
    update_data = {
        "opportunity_id": "opp-upd-001",
        "verification_tier": "T4",
        "canonical_url": "https://knight-hennessy.stanford.edu/apply",
        "source_type": "official_provider",
        "country": "United States",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "deadlines": [{"deadline_type": "scholarship", "raw_text": "Oct 8"}],
        "effective_scholarship_deadline": date(2026, 10, 8),
        "cycle_status": "current",
        "admission_eligible": "eligible",
        "scholarship_eligible": "eligible",
        "result_group": "confirmed_eligible",
        "rank": 1,
        "total_score": 94.0,
        "score_breakdown": {"field_alignment": 30.0},
        "recommendation_rationale": "Elite fellowship match",
        "confidence": "high",
    }
    updated = update_opportunity(update_data, db_path=temp_db)
    assert updated is True

    opp = get_opportunity("opp-upd-001", db_path=temp_db)
    assert opp is not None
    assert opp["verification_tier"] == "T4"
    assert opp["canonical_url"] == "https://knight-hennessy.stanford.edu/apply"
    assert opp["effective_scholarship_deadline"] == "2026-10-08"
    assert opp["result_group"] == "confirmed_eligible"
    assert opp["rank"] == 1
    assert opp["total_score"] == 94.0

    # Non-existent opportunity update returns False
    res_fake = update_opportunity({"opportunity_id": "opp-fake"}, db_path=temp_db)
    assert res_fake is False


def test_save_and_get_sop_draft(temp_db: str):
    """Verify persisting, updating, and retrieving Statement of Purpose drafts."""
    create_session("sess-sop-01", status="running", db_path=temp_db)
    insert_opportunities([
        {
            "opportunity_id": "opp-sop-01",
            "session_id": "sess-sop-01",
            "institution": "CMU",
            "program_name": "Robotics",
            "official_url": "https://ri.cmu.edu",
        }
    ], db_path=temp_db)

    draft = {
        "draft_id": "draft-001",
        "session_id": "sess-sop-01",
        "opportunity_id": "opp-sop-01",
        "institution": "CMU",
        "program_name": "Robotics",
        "sop_text": "My research passion lies in autonomous quadruped navigation...",
        "word_count": 480,
        "cited_profile_elements": ["Robot Localization Repo", "ROS 2 experience", "3.9 CGPA"],
        "missing_info_prompts": ["What specific faculty lab at CMU are you applying to?"],
        "suggested_revisions": ["Provide clearer bridge from undergraduate project to CMU lab."],
    }

    saved = save_sop_draft(draft, db_path=temp_db)
    assert saved["draft_id"] == "draft-001"
    assert saved["word_count"] == 480

    retrieved = get_sop_draft("sess-sop-01", "opp-sop-01", db_path=temp_db)
    assert retrieved is not None
    assert retrieved["institution"] == "CMU"
    assert len(retrieved["cited_profile_elements"]) == 3
    assert len(retrieved["missing_info_prompts"]) == 1

    # Update draft (UPSERT)
    draft["word_count"] = 520
    draft["sop_text"] = "Updated draft text with faculty citations..."
    save_sop_draft(draft, db_path=temp_db)

    ret_updated = get_sop_draft("sess-sop-01", db_path=temp_db)
    assert ret_updated is not None
    assert ret_updated["word_count"] == 520
    assert "Updated draft text" in ret_updated["sop_text"]


def test_delete_session_cascades_foreign_keys(temp_db: str):
    """Verify that deleting a session deletes all child opportunities, SOP drafts, events, and errors via cascade."""
    session_id = "sess-casc-01"
    create_session(session_id, status="running", db_path=temp_db)

    # 1. Attach opportunity
    insert_opportunities([{
        "opportunity_id": "opp-casc-1",
        "session_id": session_id,
        "institution": "MIT",
        "program_name": "Media Lab",
        "official_url": "https://media.mit.edu",
    }], db_path=temp_db)

    # 2. Attach SOP draft
    save_sop_draft({
        "draft_id": "sop-casc-1",
        "session_id": session_id,
        "institution": "MIT",
        "program_name": "Media Lab",
        "sop_text": "SOP text content",
        "word_count": 200,
    }, db_path=temp_db)

    # 3. Attach pipeline event
    record_pipeline_event("evt-casc-1", session_id, "SPA", "step_init", "Initialized", db_path=temp_db)

    # 4. Attach pipeline error
    record_pipeline_error("err-casc-1", session_id, "EEVA", "Timeout", "Timed out", db_path=temp_db)

    # Confirm records exist
    assert get_session(session_id, db_path=temp_db) is not None
    assert len(get_opportunities(session_id, db_path=temp_db)) == 1
    assert get_sop_draft(session_id, db_path=temp_db) is not None
    assert len(get_pipeline_events(session_id, db_path=temp_db)) == 1
    assert len(get_pipeline_errors(session_id, db_path=temp_db)) == 1

    # Delete session
    deleted = delete_session(session_id, db_path=temp_db)
    assert deleted is True

    # Assert session and ALL child records were cascade-deleted
    assert get_session(session_id, db_path=temp_db) is None
    assert len(get_opportunities(session_id, db_path=temp_db)) == 0
    assert get_sop_draft(session_id, db_path=temp_db) is None
    assert len(get_pipeline_events(session_id, db_path=temp_db)) == 0
    assert len(get_pipeline_errors(session_id, db_path=temp_db)) == 0


def test_database_migration_on_milestone_1b_schema():
    """Verify that init_db safely migrates a pre-existing Milestone 1B database missing the Phase 1 columns."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        # Create an exact Milestone 1B schema (WITHOUT the 6 new Phase 1 columns)
        conn = sqlite3.connect(path)
        with conn:
            conn.executescript("""
            CREATE TABLE sessions (
                session_id      TEXT PRIMARY KEY,
                status          TEXT NOT NULL,
                student_profile TEXT,
                created_at      TEXT NOT NULL,
                completed_at    TEXT
            );

            CREATE TABLE opportunities (
                opportunity_id          TEXT PRIMARY KEY,
                session_id              TEXT NOT NULL,
                verification_tier       TEXT NOT NULL,
                type                    TEXT NOT NULL,
                institution             TEXT NOT NULL,
                program_name            TEXT NOT NULL,
                official_url            TEXT NOT NULL,
                country                 TEXT,
                degree_level            TEXT,
                eligible_nationalities  TEXT,
                min_cgpa                REAL,
                cgpa_scale              REAL,
                english_test            TEXT,
                english_min_score       TEXT,
                gre_required            INTEGER,
                funding_amount_text     TEXT,
                funding_coverage        TEXT DEFAULT 'unknown',
                application_deadline    TEXT,
                intake_session          TEXT,
                required_documents      TEXT,
                application_instructions TEXT,
                evidence_excerpt        TEXT,
                source_url              TEXT NOT NULL,
                last_verified           TEXT,
                page_accessible         INTEGER DEFAULT 0,
                page_http_status        INTEGER,
                page_fetch_timestamp    TEXT,
                extraction_failed       INTEGER DEFAULT 0,
                cycle_status            TEXT DEFAULT 'uncertain',
                conflicting_info_flags  TEXT,
                admission_eligible      TEXT DEFAULT 'unknown',
                admission_ineligible_reasons TEXT,
                scholarship_eligible    TEXT DEFAULT 'unknown',
                scholarship_ineligible_reasons TEXT,
                missing_student_fields  TEXT,
                rank                    INTEGER,
                total_score             REAL,
                score_breakdown         TEXT,
                recommendation_rationale TEXT,
                confidence              TEXT
            );
            """)
            # Insert existing Milestone 1B session and opportunity
            conn.execute("INSERT INTO sessions (session_id, status, created_at) VALUES ('legacy-sess-1', 'completed', '2026-10-01T00:00:00Z');")
            conn.execute("""
                INSERT INTO opportunities (
                    opportunity_id, session_id, verification_tier, type, institution, program_name, official_url, source_url
                ) VALUES ('legacy-opp-1', 'legacy-sess-1', 'T1', 'scholarship', 'Harvard', 'Fellowship', 'https://harvard.edu', 'https://harvard.edu');
            """)
        conn.close()

        # Run init_db migration
        init_db(path)

        # Verify all 6 columns now exist in schema
        conn = get_connection(path)
        try:
            cursor = conn.execute("PRAGMA table_info(opportunities);")
            cols = {row["name"] for row in cursor.fetchall()}
            for expected_col in (
                "canonical_url", "source_type", "deadlines",
                "effective_scholarship_deadline", "effective_admission_deadline", "result_group",
                "is_mock", "search_provider"
            ):
                assert expected_col in cols, f"Migration failed to add {expected_col}"

            # Verify existing record is intact and accessible
            opp = get_opportunity("legacy-opp-1", db_path=path)
            assert opp is not None
            assert opp["institution"] == "Harvard"
            assert opp["result_group"] == "potentially_eligible"  # Verified default
            assert opp["source_type"] == "unknown"                 # Verified safe default for unknown legacy provenance

            # Verify updating the migrated opportunity with new fields succeeds
            update_opportunity({
                "opportunity_id": "legacy-opp-1",
                "canonical_url": "https://www.harvard.edu/fellowship/apply",
                "result_group": "confirmed_eligible",
            }, db_path=path)

            opp_upd = get_opportunity("legacy-opp-1", db_path=path)
            assert opp_upd["canonical_url"] == "https://www.harvard.edu/fellowship/apply"
            assert opp_upd["result_group"] == "confirmed_eligible"
        finally:
            conn.close()

    finally:
        if os.path.exists(path):
            os.remove(path)


def test_malformed_json_fallback_resilience(temp_db: str):
    """Verify that corrupt JSON in the database is handled gracefully with safe defaults without crashing."""
    create_session("sess-corrupt-01", status="running", db_path=temp_db)

    # Insert raw corrupted JSON strings directly into SQLite
    conn = get_connection(temp_db)
    try:
        with conn:
            conn.execute("""
                INSERT INTO opportunities (
                    opportunity_id, session_id, verification_tier, type, institution, program_name,
                    official_url, source_url, eligible_nationalities, deadlines, score_breakdown
                ) VALUES (
                    'opp-corrupt-1', 'sess-corrupt-01', 'T1', 'scholarship', 'Test Uni', 'Test Program',
                    'https://test.edu', 'https://test.edu', '{corrupt-json-array', '[unclosed-deadlines', 'not-json-dict'
                );
            """)
    finally:
        conn.close()

    # get_opportunities should deserialize corrupt fields safely without raising JSONDecodeError
    opps = get_opportunities("sess-corrupt-01", db_path=temp_db)
    assert len(opps) == 1
    corrupt_opp = opps[0]
    assert corrupt_opp["eligible_nationalities"] == []
    assert corrupt_opp["deadlines"] == []
    assert corrupt_opp["score_breakdown"] is None
