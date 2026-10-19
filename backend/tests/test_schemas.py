"""Unit tests for ScholarSwarm AI Pydantic data models.

Covers positive parsing, negative validation, enum constraints, type errors,
and cross-field validation (e.g. CGPA scale requirements).
"""

from datetime import date, datetime
import pytest
from pydantic import ValidationError

from backend.app.schemas import (
    AgentRole,
    CycleStatus,
    DegreeLevel,
    EligibilityStatus,
    FundingCoverage,
    GitHubRepo,
    HealthResponse,
    OpportunityStub,
    OpportunityType,
    PipelineError,
    PipelineEvent,
    RankedOpportunity,
    SkillConfidence,
    SkillEntry,
    SOPDraft,
    StudentProfile,
    VerificationTier,
    VerifiedOpportunity,
)


# ============================================================================
# StudentProfile Tests
# ============================================================================

def test_student_profile_valid():
    """Verify conforming StudentProfile parses successfully."""
    profile = StudentProfile(
        session_id="sess-001",
        name="Amira Chen",
        email="amira.chen@example.edu",
        nationality="Singapore",
        current_degree="B.S. in Computer Science",
        cgpa=3.85,
        cgpa_scale=4.0,
        ielts_score=8.0,
        field_of_study="Artificial Intelligence",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["Germany", "Switzerland"],
        skills_extracted=[
            SkillEntry(skill="PyTorch", confidence=SkillConfidence.EXPLICIT),
            SkillEntry(skill="Distributed Systems", confidence=SkillConfidence.INFERRED),
        ],
        github_repos=[
            GitHubRepo(name="fast-transformer", language="Python", stars=42, description="Inference engine")
        ],
    )
    assert profile.name == "Amira Chen"
    assert profile.cgpa == 3.85
    assert profile.cgpa_scale == 4.0
    assert len(profile.skills_extracted) == 2


def test_student_profile_cgpa_requires_scale():
    """Verify providing CGPA without cgpa_scale raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        StudentProfile(
            session_id="sess-002",
            field_of_study="Data Science",
            target_degree=DegreeLevel.MASTERS,
            cgpa=3.85,
            cgpa_scale=None,  # Missing scale!
        )
    assert "cgpa_scale is required whenever cgpa is provided" in str(exc_info.value)


def test_student_profile_cgpa_cannot_exceed_scale():
    """Verify CGPA exceeding scale maximum raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        StudentProfile(
            session_id="sess-003",
            field_of_study="Robotics",
            target_degree=DegreeLevel.MASTERS,
            cgpa=4.5,
            cgpa_scale=4.0,  # 4.5 > 4.0
        )
    assert "cannot exceed the specified cgpa_scale" in str(exc_info.value)


def test_student_profile_missing_required_fields():
    """Verify missing mandatory fields raises ValidationError."""
    with pytest.raises(ValidationError):
        # Missing session_id, field_of_study, target_degree
        StudentProfile(name="Incomplete User")


def test_student_profile_forbid_extra_fields():
    """Verify extra unexpected fields are rejected."""
    with pytest.raises(ValidationError):
        StudentProfile(
            session_id="sess-004",
            field_of_study="Physics",
            target_degree=DegreeLevel.PHD,
            unexpected_field="disallowed",
        )


# ============================================================================
# OpportunityStub Tests
# ============================================================================

def test_opportunity_stub_valid():
    """Verify valid OpportunityStub defaults to T1."""
    stub = OpportunityStub(
        opportunity_id="opp-stub-001",
        session_id="sess-001",
        institution="ETH Zurich",
        program_or_scholarship_name="Excellence Scholarship & Opportunity Programme",
        official_url="https://ethz.ch/students/en/studies/financial/scholarships/esop.html",
        country="Switzerland",
        degree_level=DegreeLevel.MASTERS,
        search_query_used="eth zurich masters excellence scholarship 2026",
        search_result_snippet="The Excellence Scholarship & Opportunity Programme supports master students...",
        dedup_hash="a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    )
    assert stub.verification_tier == VerificationTier.T1
    assert stub.institution == "ETH Zurich"


def test_opportunity_stub_invalid_url_scheme():
    """Verify non-HTTP/HTTPS URLs are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        OpportunityStub(
            opportunity_id="opp-stub-002",
            session_id="sess-001",
            institution="Test Univ",
            program_or_scholarship_name="Test Scholarship",
            official_url="ftp://ftp.example.edu/scholarship.pdf",
            search_query_used="test query",
            search_result_snippet="snippet",
            dedup_hash="1234567890abcdef",
        )
    assert "official_url must start with http:// or https://" in str(exc_info.value)


# ============================================================================
# VerifiedOpportunity Tests
# ============================================================================

def test_verified_opportunity_valid_t4():
    """Verify full T4 opportunity with independent eligibility statuses."""
    opp = VerifiedOpportunity(
        opportunity_id="opp-ver-001",
        session_id="sess-001",
        institution="Technical University of Munich",
        program_name="M.Sc. in Informatics",
        type=OpportunityType.PROGRAM,
        official_url="https://www.tum.de/en/studies/degree-programs/detail/informatics-master-of-science-msc",
        source_url="https://www.tum.de/en/studies/degree-programs/detail/informatics-master-of-science-msc",
        verification_tier=VerificationTier.T4,
        page_accessible=True,
        page_http_status=200,
        min_cgpa=3.0,
        cgpa_scale=4.0,
        funding_coverage=FundingCoverage.PARTIAL,
        application_deadline=date(2026, 5, 31),
        intake_session="Winter 2026/27",
        evidence_excerpt="Applicants must hold a Bachelor of Science in Informatics with a minimum grade...",
        admission_eligible=EligibilityStatus.ELIGIBLE,
        scholarship_eligible=EligibilityStatus.UNKNOWN,
        scholarship_ineligible_reasons=[],
        cycle_status=CycleStatus.CURRENT,
    )
    assert opp.verification_tier == VerificationTier.T4
    assert opp.admission_eligible == EligibilityStatus.ELIGIBLE
    assert opp.scholarship_eligible == EligibilityStatus.UNKNOWN
    assert opp.cycle_status == CycleStatus.CURRENT


def test_verified_opportunity_min_cgpa_requires_scale():
    """Verify min_cgpa without cgpa_scale is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        VerifiedOpportunity(
            opportunity_id="opp-ver-002",
            session_id="sess-001",
            institution="Oxford",
            program_name="DPhil in Computer Science",
            official_url="https://ox.ac.uk/cs",
            source_url="https://ox.ac.uk/cs",
            verification_tier=VerificationTier.T3,
            min_cgpa=3.7,
            cgpa_scale=None,  # Missing scale!
        )
    assert "cgpa_scale is required whenever min_cgpa is provided" in str(exc_info.value)


def test_verified_opportunity_invalid_enum_rejected():
    """Verify invalid tier and eligibility strings fail validation."""
    with pytest.raises(ValidationError):
        VerifiedOpportunity(
            opportunity_id="opp-ver-003",
            session_id="sess-001",
            institution="Oxford",
            program_name="DPhil",
            official_url="https://ox.ac.uk",
            source_url="https://ox.ac.uk",
            verification_tier="T99",  # Invalid tier!
        )

    with pytest.raises(ValidationError):
        VerifiedOpportunity(
            opportunity_id="opp-ver-004",
            session_id="sess-001",
            institution="Oxford",
            program_name="DPhil",
            official_url="https://ox.ac.uk",
            source_url="https://ox.ac.uk",
            verification_tier=VerificationTier.T4,
            admission_eligible="maybe",  # Invalid enum!
        )


# ============================================================================
# RankedOpportunity, SOPDraft & Event Tests
# ============================================================================

def test_ranked_opportunity_valid():
    """Verify RankedOpportunity model with explainable score breakdown."""
    ranked = RankedOpportunity(
        rank=1,
        opportunity_id="opp-ver-001",
        total_score=87.5,
        score_breakdown={
            "field_alignment": 30.0,
            "funding_coverage": 20.0,
            "deadline_proximity": 18.0,
            "eligibility_clarity": 10.0,
            "data_completeness": 9.5,
        },
        recommendation_rationale="Strong field alignment with verified English proficiency requirement match.",
        action_items=["Obtain certified degree transcript", "Request academic reference letter"],
        confidence="high",
    )
    assert ranked.rank == 1
    assert ranked.total_score == 87.5
    assert ranked.confidence == "high"


def test_sop_draft_valid():
    """Verify SOPDraft structure."""
    sop = SOPDraft(
        draft_id="sop-001",
        session_id="sess-001",
        opportunity_id="opp-ver-001",
        institution="TUM",
        program_name="Informatics",
        sop_text="During my undergraduate studies in Computer Science at University..." * 10,
        word_count=120,
        cited_profile_elements=["fast-transformer repository", "PyTorch expertise", "3.85 CGPA"],
        missing_info_prompts=["State your specific faculty research interests at TUM"],
        suggested_revisions=["Clarify your long-term research trajectory in autonomous systems"],
    )
    assert sop.draft_id == "sop-001"
    assert len(sop.cited_profile_elements) == 3


def test_pipeline_event_valid():
    """Verify PipelineEvent structure for frontend polling."""
    event = PipelineEvent(
        event_id="evt-001",
        session_id="sess-001",
        agent=AgentRole.EEVA,
        event_type="tier_advanced",
        message="Opportunity advanced from T1 to T4 following requirement extraction.",
        payload={"opportunity_id": "opp-001", "tier": "T4"},
    )
    assert event.agent == AgentRole.EEVA
    assert event.payload["tier"] == "T4"
