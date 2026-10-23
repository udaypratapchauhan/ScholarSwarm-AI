"""Focused unit tests for Milestone 2: ORA and EEVA agents.

Verifies:
1. ORA: Query generation, URL normalization, deduplication, search provider fallback, mock tagging.
2. EEVA: Official source classification, separate admission vs scholarship eligibility,
   missing student field tracking, T1-T4 evidence tiering, and strict CONFIRMED_ELIGIBLE rules.
"""

from datetime import date, timedelta
import os
import pytest

from backend.agents.eeva import _classify_source, verify_opportunities
from backend.agents.ora import _normalize_url, discover_opportunities
from backend.app.database import create_session, init_db
import tempfile

@pytest.fixture
def temp_db():
    """Create and tear down a temporary SQLite database for ORA/EEVA tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    if os.path.exists(path):
        os.remove(path)
from backend.app.schemas import (
    CycleStatus,
    DegreeLevel,
    EligibilityStatus,
    ResultGroup,
    SkillEntry,
    SourceType,
    StudentProfile,
    VerificationTier,
)
from backend.app.utils.search import SearchResult, search_scholarships


def test_ora_url_normalization_and_deduplication():
    """Verify ORA normalizes URLs by stripping trailing slashes, fragments, and queries."""
    u1 = "https://www.ox.ac.uk/clarendon/"
    u2 = "HTTPS://WWW.OX.AC.UK/CLARENDON"
    u3 = "https://www.ox.ac.uk/clarendon?utm_source=scholarship#apply"
    
    assert _normalize_url(u1) == "https://www.ox.ac.uk/clarendon"
    assert _normalize_url(u2) == "https://www.ox.ac.uk/clarendon"
    assert _normalize_url(u3) == "https://www.ox.ac.uk/clarendon"


def test_ora_discovery_and_mock_tagging(temp_db: str):
    """Verify ORA generates queries, discovers candidates, tags mock results, and starts at T1/unknown."""
    profile = StudentProfile(
        session_id="sess-ora-01",
        field_of_study="Robotics",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Germany", "Switzerland"],
        nationality="India",
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-ora-01", status="completed", student_profile=profile.model_dump(mode="json"), db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-ora-01", db_path=temp_db, max_candidates=5)
    assert len(candidates) > 0
    
    # ORA must not claim pre-verification: all candidates must enter at T1 and unknown source_type
    for cand in candidates:
        assert cand["verification_tier"] == "T1"
        assert cand["source_type"] == "unknown"
        assert "official_url" in cand
        assert "is_mock" in cand
        assert cand["is_mock"] is True  # Mock provider used in test
        assert cand["search_provider"] == "mock"


def test_eeva_source_classification():
    """Verify EEVA classifies sources based on domain trust."""
    assert _classify_source("https://ox.ac.uk/scholarship") == SourceType.OFFICIAL_PROVIDER
    assert _classify_source("https://cs.stanford.edu/admissions") == SourceType.OFFICIAL_PROVIDER
    assert _classify_source("https://cam.ac.uk/gates") == SourceType.OFFICIAL_PROVIDER
    assert _classify_source("https://www.daad.de/en/study") == SourceType.RELIABLE_SECONDARY
    assert _classify_source("https://www.campusfrance.org/eiffel") == SourceType.RELIABLE_SECONDARY
    assert _classify_source("https://www.scholarshipportal.com/view") == SourceType.AGGREGATOR
    assert _classify_source("https://random-student-blog.com/top-10") == SourceType.UNKNOWN


def test_eeva_separate_admission_and_scholarship_eligibility(temp_db: str):
    """Verify EEVA evaluates admission and scholarship eligibility independently."""
    profile = StudentProfile(
        session_id="sess-eeva-01",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        nationality="Canada",
        cgpa=2.8,  # Below 3.5 minimum requirement
        cgpa_scale=4.0,
    )
    create_session("sess-eeva-01", status="completed", db_path=temp_db)

    candidate = {
        "opportunity_id": "opp-test-split-1",
        "session_id": "sess-eeva-01",
        "institution": "Test University",
        "program_name": "MSc Computer Science Merit Award",
        "official_url": "https://university.edu/award",
        "degree_level": "masters",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "eligible_nationalities": ["All"],
        "evidence_excerpt": "Requires minimum 3.5 CGPA for university admission. Open to all nationalities.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=90)).isoformat(),
            "raw_text": "Deadline in 90 days",
        }],
    }

    verified = verify_opportunities([candidate], profile, "sess-eeva-01", db_path=temp_db)
    assert len(verified) == 1
    v = verified[0]

    # Admission eligibility is INELIGIBLE due to CGPA
    assert v["admission_eligible"] == EligibilityStatus.INELIGIBLE.value
    assert any("CGPA" in r for r in v["admission_ineligible_reasons"])

    # Scholarship eligibility is ELIGIBLE because nationality & degree match
    assert v["scholarship_eligible"] == EligibilityStatus.ELIGIBLE.value

    # Precedence: Admission failure makes overall result INELIGIBLE
    assert v["result_group"] == ResultGroup.INELIGIBLE.value


def test_eeva_missing_fields_preserves_unknown_eligibility(temp_db: str):
    """Verify EEVA does not invent missing facts or convert unknown into confirmed eligibility."""
    profile = StudentProfile(
        session_id="sess-eeva-02",
        field_of_study="Physics",
        target_degree=DegreeLevel.MASTERS,
        # CGPA omitted!
    )
    create_session("sess-eeva-02", status="completed", db_path=temp_db)

    candidate = {
        "opportunity_id": "opp-test-unk-1",
        "session_id": "sess-eeva-02",
        "institution": "Oxford University",
        "program_name": "Physics Fellowship",
        "official_url": "https://ox.ac.uk/physics-fellowship",
        "degree_level": "masters",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "evidence_excerpt": "Minimum 3.7 CGPA required.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=60)).isoformat(),
            "raw_text": "Closes in 60 days",
        }],
    }

    verified = verify_opportunities([candidate], profile, "sess-eeva-02", db_path=temp_db)
    v = verified[0]

    # Must be marked UNKNOWN, not ELIGIBLE
    assert v["admission_eligible"] == EligibilityStatus.UNKNOWN.value
    assert "cgpa" in v["missing_student_fields"]

    # Incomplete evidence cannot qualify for CONFIRMED_ELIGIBLE
    assert v["result_group"] == ResultGroup.POTENTIALLY_ELIGIBLE.value


def test_eeva_confirmed_eligible_strictly_enforces_t4_and_official_source(temp_db: str):
    """Verify that an aggregator can NEVER be classified as CONFIRMED_ELIGIBLE even if criteria match."""
    profile = StudentProfile(
        session_id="sess-eeva-03",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        nationality="India",
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-eeva-03", status="completed", db_path=temp_db)

    # Opportunity from an aggregator directory
    candidate = {
        "opportunity_id": "opp-agg-1",
        "session_id": "sess-eeva-03",
        "institution": "Some University",
        "program_name": "CS Scholarship",
        "official_url": "https://www.scholarshipportal.com/some-scholarship",
        "degree_level": "masters",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "eligible_nationalities": ["All"],
        "evidence_excerpt": "Aggregator listing snippet",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=45)).isoformat(),
            "raw_text": "Open for 45 days",
        }],
    }

    verified = verify_opportunities([candidate], profile, "sess-eeva-03", db_path=temp_db)
    v = verified[0]

    assert v["source_type"] == SourceType.AGGREGATOR.value
    # Aggregator is NOT Tier T4 and NOT OFFICIAL_PROVIDER, so it CANNOT be CONFIRMED_ELIGIBLE
    assert v["result_group"] == ResultGroup.POTENTIALLY_ELIGIBLE.value
    assert v["result_group"] != ResultGroup.CONFIRMED_ELIGIBLE.value


def test_eeva_scale_mismatch_prevents_unauthorized_auto_conversion(temp_db: str):
    """Verify that incompatible grading scales (10.0 vs 4.0) do not perform linear math."""
    profile_10pt = StudentProfile(
        session_id="sess-eeva-scale-mismatch",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        nationality="India",
        cgpa=8.5,
        cgpa_scale=10.0,
    )
    create_session("sess-eeva-scale-mismatch", status="completed", db_path=temp_db)

    # Opportunity requiring 3.5 on a 4.0 scale
    cand_4pt = {
        "opportunity_id": "opp-scale-diff",
        "session_id": "sess-eeva-scale-mismatch",
        "institution": "Stanford University",
        "program_name": "CS Masters",
        "official_url": "https://stanford.edu/cs-masters",
        "degree_level": "masters",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "eligible_nationalities": ["All"],
        "evidence_excerpt": "Minimum 3.5/4.0 CGPA required for admission.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=90)).isoformat(),
            "raw_text": "Deadline in 90 days",
        }],
    }

    verified = verify_opportunities([cand_4pt], profile_10pt, "sess-eeva-scale-mismatch", db_path=temp_db)
    v = verified[0]

    # Must be UNKNOWN (not converted or falsely confirmed)
    assert v["admission_eligible"] == EligibilityStatus.UNKNOWN.value
    assert "official_cgpa_conversion" in v["missing_student_fields"]
    assert any("mismatch" in r.lower() for r in v["admission_ineligible_reasons"])


def test_eeva_10_point_scale_compatible_evaluation(temp_db: str):
    """Verify that when both student and opportunity use 10.0 scale, direct comparison works."""
    profile_pass = StudentProfile(
        session_id="sess-10pt-pass",
        field_of_study="Data Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=8.8,
        cgpa_scale=10.0,
    )
    profile_fail = StudentProfile(
        session_id="sess-10pt-fail",
        field_of_study="Data Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=7.5,
        cgpa_scale=10.0,
    )
    create_session("sess-10pt-pass", status="completed", db_path=temp_db)
    create_session("sess-10pt-fail", status="completed", db_path=temp_db)

    cand_10pt = {
        "opportunity_id": "opp-10pt-req",
        "session_id": "sess-10pt-pass",
        "institution": "Technical University",
        "program_name": "MSc Data Science",
        "official_url": "https://tum.de/data-science",
        "degree_level": "masters",
        "min_cgpa": 8.0,
        "cgpa_scale": 10.0,
        "eligible_nationalities": ["All"],
        "evidence_excerpt": "Minimum 8.0/10.0 CGPA required.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=60)).isoformat(),
            "raw_text": "Deadline in 60 days",
        }],
    }

    v_pass = verify_opportunities([cand_10pt], profile_pass, "sess-10pt-pass", db_path=temp_db)[0]
    assert v_pass["admission_eligible"] == EligibilityStatus.ELIGIBLE.value

    v_fail = verify_opportunities([cand_10pt], profile_fail, "sess-10pt-fail", db_path=temp_db)[0]
    assert v_fail["admission_eligible"] == EligibilityStatus.INELIGIBLE.value
    assert any("8.0" in r for r in v_fail["admission_ineligible_reasons"])


def test_eeva_unknown_scale_evaluation(temp_db: str):
    """Verify that unconfirmed/unknown student scale flags missing cgpa_scale."""
    profile_unknown_scale = StudentProfile(
        session_id="sess-unk-scale",
        field_of_study="Robotics",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.85,
        cgpa_scale=None,  # Scale unknown!
    )
    create_session("sess-unk-scale", status="completed", db_path=temp_db)

    cand = {
        "opportunity_id": "opp-req-gpa",
        "session_id": "sess-unk-scale",
        "institution": "ETH Zurich",
        "program_name": "Robotics Masters",
        "official_url": "https://ethz.ch/robotics",
        "degree_level": "masters",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "evidence_excerpt": "Requires 3.5 GPA.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=60)).isoformat(),
            "raw_text": "Closes in 60 days",
        }],
    }

    v = verify_opportunities([cand], profile_unknown_scale, "sess-unk-scale", db_path=temp_db)[0]
    assert v["admission_eligible"] == EligibilityStatus.UNKNOWN.value
    assert "cgpa_scale" in v["missing_student_fields"]


def test_eeva_preserves_mock_and_live_provenance(temp_db: str):
    """Verify EEVA faithfully carries is_mock and search_provider flags from ORA."""
    profile = StudentProfile(
        session_id="sess-prov",
        field_of_study="CS",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-prov", status="completed", db_path=temp_db)

    mock_cand = {
        "opportunity_id": "opp-mock-prov",
        "session_id": "sess-prov",
        "institution": "Mock Univ",
        "program_name": "Mock Award",
        "official_url": "https://university.edu/mock",
        "is_mock": True,
        "search_provider": "mock",
    }
    live_cand = {
        "opportunity_id": "opp-live-prov",
        "session_id": "sess-prov",
        "institution": "Live Univ",
        "program_name": "Live Award",
        "official_url": "https://university.edu/live",
        "is_mock": False,
        "search_provider": "tavily",
    }

    verified = verify_opportunities([mock_cand, live_cand], profile, "sess-prov", db_path=temp_db)
    assert verified[0]["is_mock"] is True
    assert verified[0]["search_provider"] == "mock"
    assert verified[1]["is_mock"] is False
    assert verified[1]["search_provider"] == "tavily"


def test_eeva_t4_strict_enforcement_never_awarded_solely_from_mock_pool(temp_db: str):
    """Verify that a candidate cannot achieve T4 without grounded evidence and official provider status."""
    profile = StudentProfile(
        session_id="sess-t4-rules",
        field_of_study="CS",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-t4-rules", status="completed", db_path=temp_db)

    # Missing evidence excerpt
    cand_no_evidence = {
        "opportunity_id": "opp-no-ev",
        "session_id": "sess-t4-rules",
        "institution": "Oxford",
        "program_name": "Clarendon",
        "official_url": "https://ox.ac.uk/clarendon",
        "evidence_excerpt": None,  # No evidence!
        "is_mock": True,
    }
    v = verify_opportunities([cand_no_evidence], profile, "sess-t4-rules", db_path=temp_db)[0]
    # Without grounded evidence, it can never be T4
    assert v["verification_tier"] != VerificationTier.T4.value


# ============================================================================
# Focused Scenario Regression Tests (Scenarios A, C, D, E)
# ============================================================================

def test_scenario_a_ora_canada_only_discovery_and_eeva_exclusion(temp_db: str):
    """Scenario A: Canada-only student profile must not include European scholarships in primary recommendations."""
    profile_ca = StudentProfile(
        session_id="sess-scen-a-eeva",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Canada"],
        cgpa=3.85,
        cgpa_scale=4.0,
    )
    create_session("sess-scen-a-eeva", status="completed", student_profile=profile_ca.model_dump(mode="json"), db_path=temp_db)

    # 1. ORA Discovery: should only return Canadian scholarships when Canada is requested
    cands = discover_opportunities(profile_ca, "sess-scen-a-eeva", db_path=temp_db)
    for c in cands:
        assert c.get("country") == "Canada" or "canada" in c.get("program_name", "").lower()

    # 2. EEVA: European opportunity must be marked INELIGIBLE when student selected Canada
    cand_eu = {
        "opportunity_id": "opp-erasmus",
        "session_id": "sess-scen-a-eeva",
        "institution": "European Commission",
        "program_name": "Erasmus Mundus Scholarship",
        "country": "European Union",
        "official_url": "https://www.eacea.ec.europa.eu/scholarships",
        "degree_level": "masters",
        "evidence_excerpt": "EU-funded scholarship across Europe.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=60)).isoformat(),
            "raw_text": "Closes in 60 days",
        }],
    }
    verified_eu = verify_opportunities([cand_eu], profile_ca, "sess-scen-a-eeva", db_path=temp_db)[0]
    assert verified_eu["admission_eligible"] == EligibilityStatus.INELIGIBLE.value
    assert verified_eu["scholarship_eligible"] == EligibilityStatus.INELIGIBLE.value
    assert verified_eu["result_group"] == ResultGroup.INELIGIBLE.value
    assert any("does not match student's preferred study destination" in r for r in verified_eu["admission_ineligible_reasons"])


def test_scenario_c_cgpa_7_6_out_of_10_preserved_and_unknown_against_4pt_scale(temp_db: str):
    """Scenario C: Student CGPA of 7.6/10 must remain 7.6/10 and be marked UNKNOWN against a 3.0/4.0 requirement."""
    profile_7_6 = StudentProfile(
        session_id="sess-scen-c",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=7.6,
        cgpa_scale=10.0,
    )
    create_session("sess-scen-c", status="completed", db_path=temp_db)

    # Verify model preservation: never mutated to 76.0 or 76%
    assert profile_7_6.cgpa == 7.6
    assert profile_7_6.cgpa_scale == 10.0

    # Scholarship requiring 3.0/4.0
    cand_3pt = {
        "opportunity_id": "opp-3pt-req",
        "session_id": "sess-scen-c",
        "institution": "University of Toronto",
        "program_name": "Master of Science",
        "official_url": "https://utoronto.ca/admissions",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "evidence_excerpt": "Minimum 3.0 on 4.0 scale required for admission.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=60)).isoformat(),
            "raw_text": "Deadline in 60 days",
        }],
    }

    verified = verify_opportunities([cand_3pt], profile_7_6, "sess-scen-c", db_path=temp_db)[0]

    # Admission eligibility must be UNKNOWN with explicit mismatch reason
    assert verified["admission_eligible"] == EligibilityStatus.UNKNOWN.value
    assert "official_cgpa_conversion" in verified["missing_student_fields"]
    assert any(
        "student holds 7.6/10.0 but requirement states 3.0/4.0" in r
        for r in verified["admission_ineligible_reasons"]
    )
    # Never linear converted to ineligible (3.04/4.0) or fabricated
    assert verified["admission_eligible"] != EligibilityStatus.INELIGIBLE.value


def test_scenario_d_percentage_76_distinct_from_cgpa(temp_db: str):
    """Scenario D: Student percentage of 76% remains distinct on a 100.0 scale and is not relabelled as CGPA 7.6/10."""
    from backend.agents.spa import extract_cgpa_and_scale

    # Test extraction from text
    val_pct, scale_pct, _ = extract_cgpa_and_scale("Academic Performance: Percentage: 76.0%")
    assert val_pct == 76.0
    assert scale_pct == 100.0

    val_cgpa, scale_cgpa, _ = extract_cgpa_and_scale("Academic Performance: CGPA: 7.6 / 10.0")
    assert val_cgpa == 7.6
    assert scale_cgpa == 10.0

    # Ensure profile with 76.0/100.0 validates correctly
    profile_pct = StudentProfile(
        session_id="sess-scen-d",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=76.0,
        cgpa_scale=100.0,
    )
    assert profile_pct.cgpa == 76.0
    assert profile_pct.cgpa_scale == 100.0


def test_scenario_e_mock_provenance_and_t4_prohibition(temp_db: str):
    """Scenario E: Mock records cannot be labeled T4 solely because of pre-filled evidence."""
    profile = StudentProfile(
        session_id="sess-scen-e",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-scen-e", status="completed", db_path=temp_db)

    # Mock candidate with official-looking provider and evidence excerpt
    mock_opp = {
        "opportunity_id": "opp-mock-fake-t4",
        "session_id": "sess-scen-e",
        "institution": "University of Oxford",
        "program_name": "Clarendon Fund Scholarship",
        "official_url": "https://ox.ac.uk/clarendon",
        "country": "United Kingdom",
        "is_mock": True,
        "search_provider": "mock",
        "evidence_excerpt": "Pre-filled mock evidence text from local database.",
    }

    verified = verify_opportunities([mock_opp], profile, "sess-scen-e", db_path=temp_db)[0]

    # Provenance preserved
    assert verified["is_mock"] is True
    assert verified["search_provider"] == "mock"

    # Strictly forbidden to achieve T4 solely on mock data
    assert verified["verification_tier"] != VerificationTier.T4.value
    assert verified["verification_tier"] in (VerificationTier.T3.value, VerificationTier.T2.value, VerificationTier.T1.value)


# ============================================================================
# TARGETED REGRESSION SUITE: ISSUES A through E
# ============================================================================

def test_regression_cgpa_7_56_vs_3_7_requirement(temp_db: str):
    """Regression 1: CGPA 7.56/10 compared with 3.7/4 requirement.
    
    Must NOT be labeled ineligible.
    Must have neutral unknown eligibility with scale_conversion_required=True.
    Grade 7.56/10.0 must be preserved exactly without mathematical linear scaling.
    """
    profile = StudentProfile(
        session_id="sess-reg-1",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        nationality="India",
        cgpa=7.56,
        cgpa_scale=10.0,
    )
    create_session("sess-reg-1", status="completed", db_path=temp_db)

    cand = {
        "opportunity_id": "opp-ox-37",
        "session_id": "sess-reg-1",
        "institution": "University of Oxford",
        "program_name": "Clarendon Fund Scholarship",
        "official_url": "https://ox.ac.uk/clarendon",
        "degree_level": "masters",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "eligible_nationalities": ["All"],
        "evidence_excerpt": "Minimum requirement of 3.7 on 4.0 scale.",
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": (date.today() + timedelta(days=90)).isoformat(),
            "raw_text": "Deadline in 90 days",
        }],
    }

    verified = verify_opportunities([cand], profile, "sess-reg-1", db_path=temp_db)[0]

    # Neutral status: NOT ineligible!
    assert verified["admission_eligible"] == EligibilityStatus.UNKNOWN.value
    assert verified["admission_eligible"] != EligibilityStatus.INELIGIBLE.value

    # Scale conversion required
    assert verified["scale_conversion_required"] is True
    assert verified["scale_conversion_explanation"] is not None
    assert "7.56/10.0" in verified["scale_conversion_explanation"] or "7.56" in verified["scale_conversion_explanation"]
    assert "3.7" in verified["scale_conversion_explanation"]

    # Student fields intact
    assert profile.cgpa == 7.56
    assert profile.cgpa_scale == 10.0


def test_regression_new_zealand_only_search(temp_db: str):
    """Regression 2: New Zealand-only search.
    
    Must return New Zealand opportunities and strictly zero Canadian or European items.
    """
    profile = StudentProfile(
        session_id="sess-reg-nz",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["New Zealand"],
    )
    create_session("sess-reg-nz", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-nz", db_path=temp_db, max_candidates=5)

    assert len(candidates) > 0
    for c in candidates:
        assert c["country"] == "New Zealand"
        assert c["country"] != "Canada"
        assert c["country"] != "United Kingdom"
        assert c["country"] != "Germany"

    # Confirm New Zealand programs discovered
    nz_programs = [c["program_name"] for c in candidates]
    assert any("Manaaki" in p or "Auckland" in p for p in nz_programs)


def test_regression_australia_only_search(temp_db: str):
    """Regression 3: Australia-only search.
    
    Must return Australia opportunities and strictly zero non-Australian items.
    """
    profile = StudentProfile(
        session_id="sess-reg-aus",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Australia"],
    )
    create_session("sess-reg-aus", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-aus", db_path=temp_db, max_candidates=5)

    assert len(candidates) > 0
    for c in candidates:
        assert c["country"] == "Australia"
        assert c["country"] != "Canada"
        assert c["country"] != "United Kingdom"

    aus_programs = [c["program_name"] for c in candidates]
    assert any("Australia" in p or "Melbourne" in p for p in aus_programs)


def test_regression_canada_only_no_european_leak(temp_db: str):
    """Regression 4: Canada-only search with no European opportunities leaking into results."""
    profile = StudentProfile(
        session_id="sess-reg-ca",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Canada"],
    )
    create_session("sess-reg-ca", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-ca", db_path=temp_db, max_candidates=5)

    assert len(candidates) > 0
    for c in candidates:
        assert c["country"] == "Canada"
        assert c["country"] not in ("United Kingdom", "Germany", "France", "Switzerland", "New Zealand")


def test_regression_multi_country_search(temp_db: str):
    """Regression 5: Multi-country search: Canada + New Zealand + Australia.
    
    Returns opportunities across all selected destinations without unselected countries leaking.
    """
    profile = StudentProfile(
        session_id="sess-reg-multi",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Canada", "New Zealand", "Australia"],
    )
    create_session("sess-reg-multi", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-multi", db_path=temp_db, max_candidates=10)

    assert len(candidates) >= 3
    found_countries = {c["country"] for c in candidates}

    # All returned opportunities must belong to the selected list
    for c in found_countries:
        assert c in ("Canada", "New Zealand", "Australia")

    # At least two or all three destinations represented
    assert len(found_countries) >= 2


def test_regression_worldwide_search_no_accidental_filter(temp_db: str):
    """Regression 6: Worldwide search without an accidental single-country restriction."""
    profile = StudentProfile(
        session_id="sess-reg-ww",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Worldwide"],
    )
    create_session("sess-reg-ww", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-ww", db_path=temp_db, max_candidates=10)

    assert len(candidates) >= 5
    found_countries = {c["country"] for c in candidates}
    # Worldwide must include multiple different countries, not just Canada or UK
    assert len(found_countries) >= 3


def test_regression_destination_with_zero_results(temp_db: str):
    """Regression 7: Destination with zero results does not substitute scholarships from other countries."""
    profile = StudentProfile(
        session_id="sess-reg-zero",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Fiji"],
    )
    create_session("sess-reg-zero", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-zero", db_path=temp_db, max_candidates=5)

    # Must be empty: no unverified substitutions from other countries
    assert candidates == []


def test_regression_mock_results_never_t4_or_official_verified(temp_db: str):
    """Regression 8: Mock results never receive T4 or official provider verified labels."""
    from backend.agents.mra import rank_opportunities

    profile = StudentProfile(
        session_id="sess-reg-mock-t4",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["New Zealand"],
        cgpa=3.9,
        cgpa_scale=4.0,
    )
    create_session("sess-reg-mock-t4", status="completed", db_path=temp_db)

    candidates = discover_opportunities(profile, "sess-reg-mock-t4", db_path=temp_db, max_candidates=5)
    verified = verify_opportunities(candidates, profile, "sess-reg-mock-t4", db_path=temp_db)

    for v in verified:
        assert v["is_mock"] is True
        # Must NEVER be T4
        assert v["verification_tier"] != VerificationTier.T4.value
        # Source type must not claim official provider
        assert v["source_type"] != SourceType.OFFICIAL_PROVIDER.value
        # Result group cannot be CONFIRMED_ELIGIBLE
        assert v["result_group"] != ResultGroup.CONFIRMED_ELIGIBLE.value

    # MRA Ranking must exclude mock records from Top-5 recommendations
    ranked = rank_opportunities(verified, profile, "sess-reg-mock-t4", db_path=temp_db)
    top_5 = [r for r in ranked if r.get("rank") is not None and r["rank"] <= 5]
    assert len(top_5) == 0  # Zero mock records allowed in Top-5 recommendations


def test_regression_unknown_eligibility_and_expired_not_open(temp_db: str):
    """Regression 9: Unknown eligibility and expired deadlines are not shown as confirmed/open."""
    from backend.agents.mra import rank_opportunities

    profile = StudentProfile(
        session_id="sess-reg-exp",
        field_of_study="Computer Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=None,  # Missing CGPA makes eligibility unknown
    )
    create_session("sess-reg-exp", status="completed", db_path=temp_db)

    # Expired opportunity
    expired_opp = {
        "opportunity_id": "opp-exp-1",
        "session_id": "sess-reg-exp",
        "institution": "Expired Univ",
        "program_name": "Past Award",
        "official_url": "https://expired.edu/award",
        "degree_level": "masters",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "deadlines": [{
            "deadline_type": "scholarship",
            "deadline_date": "2024-01-01",
            "raw_text": "Closed January 2024",
        }],
    }

    verified = verify_opportunities([expired_opp], profile, "sess-reg-exp", db_path=temp_db)[0]

    assert verified["cycle_status"] == CycleStatus.EXPIRED.value
    assert verified["result_group"] == ResultGroup.EXPIRED.value
    assert verified["admission_eligible"] == EligibilityStatus.UNKNOWN.value

    # Expired opp cannot receive any rank
    ranked = rank_opportunities([verified], profile, "sess-reg-exp", db_path=temp_db)
    assert ranked[0]["rank"] is None


