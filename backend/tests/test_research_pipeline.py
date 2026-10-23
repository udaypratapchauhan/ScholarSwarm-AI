"""End-to-end integration tests for Scholarship Research Pipeline API.

Validates the full four-agent orchestrator:
ORA (Discovery) -> EEVA (Verification) -> MRA (Ranking) -> ASA (SOP Draft).
"""

from fastapi.testclient import TestClient
import pytest

from backend.app.database import create_session, init_db
from backend.app.main import app
from backend.app.schemas import DegreeLevel, StudentProfile


import os
import tempfile

@pytest.fixture
def temp_db():
    """Create and tear down a temporary SQLite database for pipeline tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture(autouse=True)
def setup_test_db(temp_db: str, monkeypatch: pytest.MonkeyPatch):
    """Ensure clean test database for research pipeline tests."""
    monkeypatch.setattr("backend.app.database.DEFAULT_DB_PATH", temp_db)


def test_research_pipeline_end_to_end(temp_db: str):
    """Test full multi-agent research pipeline end-to-end via FastAPI test client."""
    client = TestClient(app)

    # 1. Create a student session with rich profile
    session_id = "sess-pipeline-test-01"
    profile = {
        "session_id": session_id,
        "name": "Amina Al-Mansoor",
        "email": "amina@example.edu",
        "field_of_study": "Computer Science",
        "target_degree": "masters",
        "nationality": "Lebanon",
        "preferred_countries": ["United Kingdom", "Germany"],
        "cgpa": 3.85,
        "cgpa_scale": 4.0,
        "work_experience_years": 2.0,
        "skills_extracted": [
            {"skill": "Computer Science", "confidence": "explicit"},
            {"skill": "Artificial Intelligence", "confidence": "explicit"},
            {"skill": "Machine Learning", "confidence": "explicit"},
        ],
        "github_repos": [
            {"name": "Multilingual Clinical NLP", "description": "Developed healthcare LLM fine-tunes.", "stars": 12}
        ],
    }

    create_session(
        session_id=session_id,
        status="completed",
        student_profile=profile,
        db_path=temp_db,
    )

    # 2. Trigger research pipeline
    res_post = client.post(f"/api/sessions/{session_id}/research")
    assert res_post.status_code == 200, res_post.text
    data = res_post.json()
    assert data["session_id"] == session_id
    assert data["status"] == "completed"
    assert data["opportunity_count"] > 0
    # In mock mode, unverified records cannot receive T4 or Top-5 recommendation ranks
    assert data["top_5_count"] == 0
    assert data["sop_generated"] is True

    # 3. Retrieve evaluated opportunities
    res_opps = client.get(f"/api/sessions/{session_id}/opportunities")
    assert res_opps.status_code == 200
    opps = res_opps.json()
    assert len(opps) > 0

    # Verify candidate opportunity properties
    first_opp = opps[0]
    assert first_opp["is_mock"] is True
    assert first_opp["verification_tier"] != "T4"
    assert first_opp["total_score"] is not None
    assert "field_alignment" in first_opp["score_breakdown"]
    assert first_opp["evidence_excerpt"] is not None

    # Verify filtering by tier: mock opportunities are discovered at T1
    res_t1 = client.get(f"/api/sessions/{session_id}/opportunities?tier=T1")
    assert res_t1.status_code == 200
    t1_opps = res_t1.json()
    for o in t1_opps:
        assert o["verification_tier"] == "T1"

    # 4. Retrieve synthesized SOP draft
    res_sop = client.get(f"/api/sessions/{session_id}/sop")
    assert res_sop.status_code == 200
    sop = res_sop.json()
    assert sop["session_id"] == session_id
    opp_ids = [o["opportunity_id"] for o in opps]
    assert sop["opportunity_id"] in opp_ids
    matched_opp = next(o for o in opps if o["opportunity_id"] == sop["opportunity_id"])
    assert sop["institution"] == matched_opp["institution"]
    assert "Computer Science" in sop["sop_text"]
    assert sop["word_count"] > 50
    assert len(sop["cited_profile_elements"]) > 0
    assert len(sop["missing_info_prompts"]) > 0
    assert len(sop["suggested_revisions"]) > 0

    # 5. Check events emitted during research
    res_events = client.get(f"/api/sessions/{session_id}/events")
    assert res_events.status_code == 200
    events = res_events.json()
    agent_roles = {e["agent"] for e in events}
    assert "ORA" in agent_roles
    assert "EEVA" in agent_roles
    assert "MRA" in agent_roles
    assert "ASA" in agent_roles


def test_research_pipeline_session_not_found():
    """Verify 404 is returned when attempting research or fetching results for unknown session."""
    client = TestClient(app)

    res1 = client.post("/api/sessions/non-existent-sess/research")
    assert res1.status_code == 404

    res2 = client.get("/api/sessions/non-existent-sess/opportunities")
    assert res2.status_code == 404

    res3 = client.get("/api/sessions/non-existent-sess/sop")
    assert res3.status_code == 404
