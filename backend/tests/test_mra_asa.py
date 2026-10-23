"""Focused unit and integration tests for Milestone 3: MRA and ASA agents.

Verifies:
1. MRA: Deterministic scoring, configurable weights, no points for unknown data,
   separate admission vs scholarship eligibility, strict T4 official-provider Top-5 rules,
   returning <5 when <5 qualify, exclusion of INELIGIBLE and EXPIRED opportunities.
2. ASA: Grounded SOP generation without hallucinations on sparse profiles,
   provenance tracking, targeted missing-info prompts, confirmed vs unconfirmed checklists.
3. Database persistence and end-to-end pipeline integration.
"""

from datetime import date, timedelta
import os
import tempfile
from typing import Any, Dict, List
import pytest

from backend.agents.asa import generate_sop_draft
from backend.agents.mra import _score_opportunity, load_scoring_weights, rank_opportunities
from backend.app.database import (
    create_session,
    get_opportunities,
    get_session,
    get_sop_draft,
    init_db,
    insert_opportunities,
)
from backend.app.schemas import (
    CycleStatus,
    DegreeLevel,
    EligibilityStatus,
    FundingCoverage,
    ResultGroup,
    SkillEntry,
    SourceType,
    StudentProfile,
    VerificationTier,
)


@pytest.fixture
def temp_db():
    """Create and tear down a temporary SQLite database for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


# ============================================================================
# MRA Unit Tests
# ============================================================================

def test_mra_load_scoring_weights():
    """Verify scoring weights load properly and sum to 1.0."""
    weights = load_scoring_weights()
    assert isinstance(weights, dict)
    assert "field_alignment" in weights
    assert "funding_coverage" in weights
    assert "deadline_proximity" in weights
    assert "eligibility_clarity" in weights
    assert "data_completeness" in weights
    assert round(sum(weights.values()), 2) == 1.0


def test_mra_scoring_never_awards_points_for_unknown_info():
    """Verify unknown funding, unknown deadline, and unknown fields award 0 eligibility points."""
    weights = load_scoring_weights()
    profile = StudentProfile(
        session_id="sess-mra-unknown",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
    )

    opp_unknown = {
        "opportunity_id": "opp-unk",
        "institution": "Unknown University",
        "program_name": "General Masters",
        "funding_coverage": "unknown",  # Unknown funding
        "application_deadline": None,   # Unknown deadline
        "effective_scholarship_deadline": None,
        "cycle_status": "uncertain",
        "admission_eligible": "unknown",
        "scholarship_eligible": "unknown",
        "missing_student_fields": ["cgpa", "nationality", "english_test_score"],
        "verification_tier": "T1",
        "source_type": "unknown",
    }

    result = _score_opportunity(opp_unknown, profile, weights)
    breakdown = result["score_breakdown"]

    # Unknown funding must be 0
    assert breakdown["funding_coverage"] == 0.0
    # Unknown deadline must be 0
    assert breakdown["deadline_proximity"] == 0.0
    # Heavy penalty for missing fields & unknown eligibility
    assert breakdown["eligibility_clarity"] == 0.0
    # T1 unverified completeness score
    assert breakdown["data_completeness"] == 0.0
    assert result["total_score"] < 25.0
    assert result["confidence"] == "low"


def test_mra_scoring_deterministic():
    """Verify scoring is strictly deterministic given the same inputs."""
    weights = load_scoring_weights()
    profile = StudentProfile(
        session_id="sess-mra-det",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.9,
        cgpa_scale=4.0,
        skills_extracted=[SkillEntry(skill="Python", confidence="explicit")],
    )

    future_dl = (date.today() + timedelta(days=60)).isoformat()
    opp = {
        "opportunity_id": "opp-det",
        "institution": "Oxford University",
        "program_name": "MSc in Computer Science",
        "degree_level": "masters",
        "funding_coverage": "full",
        "effective_scholarship_deadline": future_dl,
        "cycle_status": "current",
        "admission_eligible": "eligible",
        "scholarship_eligible": "eligible",
        "missing_student_fields": [],
        "evidence_excerpt": "Full scholarship covering all tuition and living stipend for Computer Science.",
        "deadlines": [{"deadline_type": "scholarship", "raw_text": "Dec 1"}],
        "verification_tier": "T4",
        "source_type": "official_provider",
    }

    res1 = _score_opportunity(opp, profile, weights)
    res2 = _score_opportunity(opp, profile, weights)
    assert res1 == res2
    assert res1["total_score"] > 80.0
    assert res1["confidence"] == "high"


def test_mra_strict_top_5_only_t4_official_provider(temp_db: str):
    """Verify ONLY T4 official-provider opportunities enter Top-5, returning <5 if fewer qualify."""
    profile = StudentProfile(
        session_id="sess-top5-test",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.8,
        cgpa_scale=4.0,
    )
    create_session("sess-top5-test", status="completed", db_path=temp_db)

    future_dl = (date.today() + timedelta(days=90)).isoformat()
    past_dl = (date.today() - timedelta(days=30)).isoformat()

    # Candidate pool:
    # 1: T4 Official Provider - Confirmed Eligible (Should be Rank 1)
    # 2: T4 Official Provider - Potentially Eligible (Should be Rank 2)
    # 3: T3 Secondary Source - Potentially Eligible (Should have rank = None; cannot enter Top 5!)
    # 4: T2 Discovered - Potentially Eligible (Should have rank = None)
    # 5: T4 Official Provider - INELIGIBLE (Should have rank = None; excluded!)
    # 6: T4 Official Provider - EXPIRED (Should have rank = None; excluded!)
    candidates = [
        {
            "opportunity_id": "opp-t4-confirmed",
            "session_id": "sess-top5-test",
            "institution": "Cambridge",
            "program_name": "Gates Cambridge",
            "verification_tier": "T4",
            "source_type": "official_provider",
            "result_group": "confirmed_eligible",
            "admission_eligible": "eligible",
            "scholarship_eligible": "eligible",
            "cycle_status": "current",
            "funding_coverage": "full",
            "effective_scholarship_deadline": future_dl,
            "evidence_excerpt": "Full funding covers fees and maintenance.",
        },
        {
            "opportunity_id": "opp-t4-potential",
            "session_id": "sess-top5-test",
            "institution": "Oxford",
            "program_name": "Clarendon Fund",
            "verification_tier": "T4",
            "source_type": "official_provider",
            "result_group": "potentially_eligible",
            "admission_eligible": "eligible",
            "scholarship_eligible": "unknown",
            "cycle_status": "current",
            "funding_coverage": "full",
            "effective_scholarship_deadline": future_dl,
            "evidence_excerpt": "Clarendon awards major graduate scholarships.",
        },
        {
            "opportunity_id": "opp-t3-secondary",
            "session_id": "sess-top5-test",
            "institution": "DAAD Germany",
            "program_name": "Helmut Schmidt",
            "verification_tier": "T3",  # NOT T4
            "source_type": "reliable_secondary",  # NOT official_provider
            "result_group": "potentially_eligible",
            "admission_eligible": "eligible",
            "scholarship_eligible": "eligible",
            "cycle_status": "current",
            "funding_coverage": "full",
            "effective_scholarship_deadline": future_dl,
            "evidence_excerpt": "DAAD secondary portal listing.",
        },
        {
            "opportunity_id": "opp-t2-portal",
            "session_id": "sess-top5-test",
            "institution": "Aggregator Site",
            "program_name": "Some Scholarship",
            "verification_tier": "T2",
            "source_type": "aggregator",
            "result_group": "potentially_eligible",
            "cycle_status": "current",
            "funding_coverage": "partial",
        },
        {
            "opportunity_id": "opp-t4-ineligible",
            "session_id": "sess-top5-test",
            "institution": "Stanford",
            "program_name": "Stanford Knight-Hennessy",
            "verification_tier": "T4",
            "source_type": "official_provider",
            "result_group": "ineligible",  # Ineligible
            "admission_eligible": "ineligible",
            "admission_ineligible_reasons": ["GPA below threshold"],
            "scholarship_eligible": "ineligible",
            "cycle_status": "current",
            "funding_coverage": "full",
            "effective_scholarship_deadline": future_dl,
        },
        {
            "opportunity_id": "opp-t4-expired",
            "session_id": "sess-top5-test",
            "institution": "ETH Zurich",
            "program_name": "ETH ESOP",
            "verification_tier": "T4",
            "source_type": "official_provider",
            "result_group": "expired",  # Expired
            "cycle_status": "expired",
            "effective_scholarship_deadline": past_dl,
        },
    ]

    ranked = rank_opportunities(candidates, profile, "sess-top5-test", db_path=temp_db)

    # 1. Exactly 2 opportunities qualify for Top-5 recommendations (opp-t4-confirmed, opp-t4-potential)
    recommended = [o for o in ranked if o.get("rank") is not None and o.get("rank") <= 5]
    assert len(recommended) == 2, f"Expected 2 recommended, got {len(recommended)}"

    # Check rank 1
    assert recommended[0]["opportunity_id"] == "opp-t4-confirmed"
    assert recommended[0]["rank"] == 1
    assert recommended[0]["verification_tier"] == "T4"
    assert recommended[0]["source_type"] == "official_provider"
    assert recommended[0]["result_group"] == "confirmed_eligible"

    # Check rank 2
    assert recommended[1]["opportunity_id"] == "opp-t4-potential"
    assert recommended[1]["rank"] == 2
    assert recommended[1]["verification_tier"] == "T4"
    assert recommended[1]["source_type"] == "official_provider"
    assert recommended[1]["result_group"] == "potentially_eligible"

    # Check excluded opportunities
    opp_dict = {o["opportunity_id"]: o for o in ranked}
    assert opp_dict["opp-t3-secondary"]["rank"] is None
    assert opp_dict["opp-t2-portal"]["rank"] is None
    assert opp_dict["opp-t4-ineligible"]["rank"] is None
    assert opp_dict["opp-t4-expired"]["rank"] is None


def test_mra_handles_empty_candidates_and_sparse_profile(temp_db: str):
    """Verify MRA safely handles empty opportunity list and sparse student profile."""
    sparse_profile = StudentProfile(
        session_id="sess-sparse",
        field_of_study="Physics",
        target_degree=DegreeLevel.PHD,
    )
    create_session("sess-sparse", status="completed", db_path=temp_db)

    # Empty candidates
    res = rank_opportunities([], sparse_profile, "sess-sparse", db_path=temp_db)
    assert res == []


# ============================================================================
# ASA Unit Tests
# ============================================================================

def test_asa_generates_grounded_sop_with_full_profile(temp_db: str):
    """Verify ASA generates an SOP citing actual profile attributes without fabrication."""
    profile = StudentProfile(
        session_id="sess-asa-full",
        name="Elena Rostova",
        field_of_study="Artificial Intelligence",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.92,
        cgpa_scale=4.0,
        work_experience_years=3.0,
        ielts_score=8.0,
        skills_extracted=[
            SkillEntry(skill="Deep Learning", confidence="explicit"),
            SkillEntry(skill="Natural Language Processing", confidence="explicit"),
        ],
        github_repos=[
            {"name": "Neural-Translation-Toolkit", "description": "PyTorch transformer library", "stars": 45}
        ],
    )
    create_session("sess-asa-full", status="completed", db_path=temp_db)

    opportunity = {
        "opportunity_id": "opp-oxford",
        "institution": "University of Oxford",
        "program_name": "MSc in Advanced Computer Science",
        "verification_tier": "T4",
        "source_type": "official_provider",
        "official_url": "https://www.ox.ac.uk/admissions/graduate/courses/msc-advanced-computer-science",
        "funding_coverage": "full",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.5",
        "effective_scholarship_deadline": "2026-12-01",
        "evidence_excerpt": "Full scholarships available for eligible applicants with first-class degrees.",
    }

    draft = generate_sop_draft(opportunity, profile, "sess-asa-full", db_path=temp_db)

    assert draft["session_id"] == "sess-asa-full"
    assert draft["opportunity_id"] == "opp-oxford"
    assert draft["institution"] == "University of Oxford"
    assert draft["word_count"] > 100

    # Verify grounding
    sop = draft["sop_text"]
    assert "Elena Rostova" in sop
    assert "Deep Learning" in sop or "Artificial Intelligence" in sop
    assert "Neural-Translation-Toolkit" in sop
    assert "3.92/4.0" in sop
    assert "3.0 years of professional experience" in sop

    # Verify cited profile elements
    citations = draft["cited_profile_elements"]
    assert any("Elena Rostova" in c for c in citations)
    assert any("3.92/4.0" in c for c in citations)
    assert any("Neural-Translation-Toolkit" in c for c in citations)

    # Verify checklist distinguishes confirmed deadlines and requirements
    # Verify checklist distinguishes confirmed deadlines and requirements
    checklist = draft["suggested_revisions"]
    assert any("[CONFIRMED REQUIREMENT]" in item and "2026-12-01" in item for item in checklist)
    assert any("[CONFIRMED REQUIREMENT]" in item and "3.7/4.0" in item for item in checklist)
    assert any("[CONFIRMED REQUIREMENT]" in item and "IELTS" in item for item in checklist)


def test_asa_never_hallucinates_on_sparse_profile(temp_db: str):
    """Verify ASA handles missing CGPA, repos, and work exp without inventing facts."""
    sparse_profile = StudentProfile(
        session_id="sess-asa-sparse",
        field_of_study="Cybersecurity",
        target_degree=DegreeLevel.MASTERS,
    )
    create_session("sess-asa-sparse", status="completed", db_path=temp_db)

    opportunity = {
        "opportunity_id": "opp-sparse-target",
        "institution": "Technical University of Munich",
        "program_name": "MSc Informatics",
        "verification_tier": "T3",
        "source_type": "reliable_secondary",
        "official_url": "https://www.in.tum.de",
    }

    draft = generate_sop_draft(opportunity, sparse_profile, "sess-asa-sparse", db_path=temp_db)

    sop = draft["sop_text"]
    # Must NOT invent any GPA
    assert "GPA" not in sop
    # Must NOT invent specific repository names
    assert "repository '" not in sop
    # Must NOT invent work experience
    assert "years of professional experience" not in sop

    # Must contain prominent notice for partially verified T3 source
    assert "[NOTICE:" in sop

    # Must generate targeted missing-info prompts for missing fields
    prompts = draft["missing_info_prompts"]
    assert any("GPA and grading scale" in p for p in prompts)
    assert any("internships" in p or "industry roles" in p for p in prompts)

    # Must reflect unconfirmed deadline in checklist
    revisions = draft["suggested_revisions"]
    assert any("[NEEDS VERIFICATION]" in r and "deadline" in r.lower() for r in revisions)


def test_asa_draft_database_persistence(temp_db: str):
    """Verify SOP draft can be saved and retrieved accurately via database CRUD."""
    create_session("sess-db-sop", status="completed", db_path=temp_db)

    profile = StudentProfile(
        session_id="sess-db-sop",
        name="Tariq Mansoor",
        field_of_study="Data Science",
        target_degree=DegreeLevel.MASTERS,
    )

    opp = {
        "opportunity_id": "opp-persist",
        "session_id": "sess-db-sop",
        "institution": "Edinburgh University",
        "program_name": "MSc Data Science",
        "official_url": "https://www.ed.ac.uk/data-science",
        "verification_tier": "T4",
        "source_type": "official_provider",
    }
    insert_opportunities([opp], db_path=temp_db)

    draft = generate_sop_draft(opp, profile, "sess-db-sop", db_path=temp_db)
    
    # Retrieve from database
    retrieved = get_sop_draft(session_id="sess-db-sop", db_path=temp_db)
    assert retrieved is not None
    assert retrieved["draft_id"] == draft["draft_id"]
    assert retrieved["institution"] == "Edinburgh University"
    assert retrieved["word_count"] == draft["word_count"]
    assert len(retrieved["missing_info_prompts"]) > 0
    assert len(retrieved["suggested_revisions"]) > 0


# ============================================================================
# Focused Scenario Tests (Issues 1, 4, 5)
# ============================================================================

def test_scenario_a_mra_canada_only_excludes_europe_from_top_recommendations(temp_db: str):
    """Scenario A: When student selects Canada only, Europe opportunities must never be in Top-5."""
    profile_canada = StudentProfile(
        session_id="sess-scen-a",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Canada"],
        cgpa=3.85,
        cgpa_scale=4.0,
    )
    create_session("sess-scen-a", status="completed", db_path=temp_db)

    # 1 Europe opportunity (UK) and 1 Canada opportunity
    opp_uk = {
        "opportunity_id": "opp-oxford",
        "session_id": "sess-scen-a",
        "institution": "University of Oxford",
        "program_name": "Clarendon Fund Scholarship",
        "country": "United Kingdom",
        "verification_tier": "T4",
        "source_type": "official_provider",
        "result_group": "confirmed_eligible",
        "effective_scholarship_deadline": (date.today() + timedelta(days=90)).isoformat(),
        "total_score": 95.0,
    }
    opp_ca = {
        "opportunity_id": "opp-mcgill",
        "session_id": "sess-scen-a",
        "institution": "McGill University",
        "program_name": "McCall MacBain Scholarship",
        "country": "Canada",
        "verification_tier": "T4",
        "source_type": "official_provider",
        "result_group": "confirmed_eligible",
        "effective_scholarship_deadline": (date.today() + timedelta(days=90)).isoformat(),
        "total_score": 90.0,
    }

    ranked = rank_opportunities([opp_uk, opp_ca], profile_canada, "sess-scen-a", db_path=temp_db)

    # McGill (Canada) must receive Rank 1
    ca_ranked = next(o for o in ranked if o["opportunity_id"] == "opp-mcgill")
    assert ca_ranked["rank"] == 1

    # Oxford (UK) must NOT receive a Top-5 recommendation rank
    uk_ranked = next(o for o in ranked if o["opportunity_id"] == "opp-oxford")
    assert uk_ranked["rank"] is None


def test_scenario_b_mra_canada_and_germany_allows_both_destinations(temp_db: str):
    """Scenario B: When student selects Canada and Germany, opportunities from either can qualify."""
    profile_multi = StudentProfile(
        session_id="sess-scen-b",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Canada", "Germany"],
        cgpa=3.85,
        cgpa_scale=4.0,
    )
    create_session("sess-scen-b", status="completed", db_path=temp_db)

    opp_de = {
        "opportunity_id": "opp-daad",
        "session_id": "sess-scen-b",
        "institution": "DAAD",
        "program_name": "Helmut-Schmidt Programme",
        "country": "Germany",
        "verification_tier": "T4",
        "source_type": "official_provider",
        "result_group": "confirmed_eligible",
        "effective_scholarship_deadline": (date.today() + timedelta(days=90)).isoformat(),
        "total_score": 92.0,
    }
    opp_ca = {
        "opportunity_id": "opp-mcgill",
        "session_id": "sess-scen-b",
        "institution": "McGill University",
        "program_name": "McCall MacBain Scholarship",
        "country": "Canada",
        "verification_tier": "T4",
        "source_type": "official_provider",
        "result_group": "confirmed_eligible",
        "effective_scholarship_deadline": (date.today() + timedelta(days=90)).isoformat(),
        "total_score": 90.0,
    }

    ranked = rank_opportunities([opp_de, opp_ca], profile_multi, "sess-scen-b", db_path=temp_db)
    top_ranks = [o for o in ranked if o["rank"] is not None]
    assert len(top_ranks) == 2
    # Study destinations are clearly preserved
    countries_ranked = {o["country"] for o in top_ranks}
    assert "Germany" in countries_ranked
    assert "Canada" in countries_ranked


def test_scenario_f_checklist_unknown_ielts_is_request_not_failure(temp_db: str):
    """Scenario F: Unknown IELTS information becomes an information request, not a confirmed failure."""
    profile_no_ielts = StudentProfile(
        session_id="sess-scen-f",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.85,
        cgpa_scale=4.0,
        ielts_score=None,  # English score unknown!
    )
    create_session("sess-scen-f", status="completed", db_path=temp_db)

    opp_with_ielts = {
        "opportunity_id": "opp-ielts-req",
        "session_id": "sess-scen-f",
        "institution": "McGill University",
        "program_name": "Master of Computer Science",
        "official_url": "https://mcgill.ca/cs",
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "effective_scholarship_deadline": "2026-12-15",
        "cycle_status": "current",
        "required_documents": ["Official Transcript"],
    }

    draft = generate_sop_draft(opp_with_ielts, profile_no_ielts, "sess-scen-f", db_path=temp_db)
    revisions = draft["suggested_revisions"]

    # Must say: "English proficiency score not provided; check whether a test is required"
    assert any(
        "English proficiency score not provided" in r and "[NEEDS VERIFICATION]" in r
        for r in revisions
    )

    # Must NOT label it as an ineligibility failure
    assert not any("failed English requirement" in r.lower() for r in revisions)
    assert not any("ineligible" in r.lower() for r in revisions)

    # Required document is confirmed
    assert any("[CONFIRMED REQUIREMENT]" in r and "Official Transcript" in r for r in revisions)

    # Unsupported document (e.g. GRE) is NOT listed as a confirmed requirement
    assert not any("[CONFIRMED REQUIREMENT]" in r and "GRE" in r for r in revisions)

