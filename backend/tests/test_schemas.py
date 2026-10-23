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
    DeadlineEntry,
    DeadlineType,
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
    ResultGroup,
    SkillConfidence,
    SkillEntry,
    SOPDraft,
    SourceType,
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


def test_student_profile_cgpa_unknown_scale_permitted():
    """Verify providing CGPA without cgpa_scale preserves raw value with scale marked as None (unknown)."""
    profile = StudentProfile(
        session_id="sess-002",
        field_of_study="Data Science",
        target_degree=DegreeLevel.MASTERS,
        cgpa=3.85,
        cgpa_scale=None,  # Unknown scale permitted!
    )
    assert profile.cgpa == 3.85
    assert profile.cgpa_scale is None


def test_student_profile_cgpa_10_point_and_percentage_scales():
    """Verify 10-point and percentage scales validate correctly."""
    p_10 = StudentProfile(
        session_id="sess-10pt",
        field_of_study="Engineering",
        target_degree=DegreeLevel.MASTERS,
        cgpa=8.75,
        cgpa_scale=10.0,
    )
    assert p_10.cgpa == 8.75
    assert p_10.cgpa_scale == 10.0

    p_pct = StudentProfile(
        session_id="sess-pct",
        field_of_study="Physics",
        target_degree=DegreeLevel.MASTERS,
        cgpa=85.0,
        cgpa_scale=100.0,
    )
    assert p_pct.cgpa == 85.0
    assert p_pct.cgpa_scale == 100.0


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

    with pytest.raises(ValidationError) as exc_info2:
        StudentProfile(
            session_id="sess-003b",
            field_of_study="Robotics",
            target_degree=DegreeLevel.MASTERS,
            cgpa=10.5,
            cgpa_scale=10.0,  # 10.5 > 10.0
        )
    assert "cannot exceed the specified cgpa_scale" in str(exc_info2.value)


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


def test_verified_opportunity_min_cgpa_unknown_scale_allowed():
    """Verify min_cgpa without cgpa_scale preserves raw requirement with scale=None (unknown)."""
    opp = VerifiedOpportunity(
        opportunity_id="opp-ver-002",
        session_id="sess-001",
        institution="Oxford",
        program_name="DPhil in Computer Science",
        official_url="https://ox.ac.uk/cs",
        source_url="https://ox.ac.uk/cs",
        verification_tier=VerificationTier.T3,
        min_cgpa=3.7,
        cgpa_scale=None,  # Unstated scale allowed!
    )
    assert opp.min_cgpa == 3.7
    assert opp.cgpa_scale is None


def test_verified_opportunity_min_cgpa_cannot_exceed_scale():
    """Verify min_cgpa cannot exceed specified cgpa_scale."""
    with pytest.raises(ValidationError) as exc_info:
        VerifiedOpportunity(
            opportunity_id="opp-ver-002b",
            session_id="sess-001",
            institution="Oxford",
            program_name="DPhil in Computer Science",
            official_url="https://ox.ac.uk/cs",
            source_url="https://ox.ac.uk/cs",
            verification_tier=VerificationTier.T3,
            min_cgpa=4.5,
            cgpa_scale=4.0,  # 4.5 > 4.0
        )
    assert "cannot exceed the specified cgpa_scale" in str(exc_info.value)


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


# ============================================================================
# Phase 1: SourceType, DeadlineType, ResultGroup & DeadlineEntry Tests
# ============================================================================

def test_source_type_enum():
    """Verify SourceType enum contains expected trust tiers."""
    assert SourceType.OFFICIAL_PROVIDER.value == "official_provider"
    assert SourceType.RELIABLE_SECONDARY.value == "reliable_secondary"
    assert SourceType.AGGREGATOR.value == "aggregator"
    assert SourceType.UNKNOWN.value == "unknown"


def test_deadline_type_enum():
    """Verify DeadlineType enum values."""
    assert DeadlineType.SCHOLARSHIP.value == "scholarship"
    assert DeadlineType.ADMISSION.value == "admission"
    assert DeadlineType.PRIORITY_AID.value == "priority_aid"
    assert DeadlineType.DEPARTMENTAL.value == "departmental"
    assert DeadlineType.GENERAL.value == "general"
    assert DeadlineType.UNKNOWN.value == "unknown"


def test_result_group_enum():
    """Verify ResultGroup enum values."""
    assert ResultGroup.CONFIRMED_ELIGIBLE.value == "confirmed_eligible"
    assert ResultGroup.POTENTIALLY_ELIGIBLE.value == "potentially_eligible"
    assert ResultGroup.INELIGIBLE.value == "ineligible"
    assert ResultGroup.EXPIRED.value == "expired"


def test_deadline_entry_valid_with_time_and_timezone():
    """Verify DeadlineEntry parses valid date, time, and explicit timezone."""
    entry = DeadlineEntry(
        deadline_type=DeadlineType.SCHOLARSHIP,
        deadline_date=date(2026, 12, 1),
        deadline_time="23:59",
        timezone="EST",
        intake_cycle="Fall 2027",
        raw_text="Scholarship applications close December 1, 2026 at 23:59 EST for Fall 2027 intake.",
        is_inferred_year=False,
    )
    assert entry.deadline_type == DeadlineType.SCHOLARSHIP
    assert entry.deadline_date == date(2026, 12, 1)
    assert entry.deadline_time == "23:59"
    assert entry.timezone == "EST"
    assert entry.intake_cycle == "Fall 2027"
    assert entry.is_inferred_year is False


def test_deadline_entry_date_only_preserves_none_timezone():
    """Verify DeadlineEntry preserves timezone=None and deadline_time=None without fabricating UTC."""
    entry = DeadlineEntry(
        deadline_type=DeadlineType.ADMISSION,
        deadline_date=date(2026, 11, 15),
        raw_text="Application cutoff is November 15, 2026.",
    )
    assert entry.deadline_date == date(2026, 11, 15)
    assert entry.deadline_time is None
    assert entry.timezone is None
    assert entry.is_inferred_year is False


def test_deadline_entry_extra_fields_forbidden():
    """Verify DeadlineEntry rejects undeclared extra attributes."""
    with pytest.raises(ValidationError):
        DeadlineEntry(
            deadline_type=DeadlineType.GENERAL,
            raw_text="Open until filled",
            synthetic_field="not_allowed",
        )


def test_verified_opportunity_phase1_fields_populated():
    """Verify VerifiedOpportunity with all Phase 1 fields parses cleanly."""
    opp = VerifiedOpportunity(
        opportunity_id="opp-p1-001",
        session_id="sess-p1",
        institution="Oxford University",
        program_name="Clarendon Fund Scholarship",
        official_url="https://ox.ac.uk/clarendon",
        canonical_url="https://www.ox.ac.uk/clarendon/apply",
        source_type=SourceType.OFFICIAL_PROVIDER,
        source_url="https://ox.ac.uk/clarendon",
        verification_tier=VerificationTier.T4,
        page_accessible=True,
        page_http_status=200,
        deadlines=[
            DeadlineEntry(
                deadline_type=DeadlineType.SCHOLARSHIP,
                deadline_date=date(2026, 12, 1),
                raw_text="Clarendon scholarship deadline: Dec 1, 2026",
            ),
            DeadlineEntry(
                deadline_type=DeadlineType.ADMISSION,
                deadline_date=date(2027, 1, 15),
                raw_text="General department admission: Jan 15, 2027",
            ),
        ],
        effective_scholarship_deadline=date(2026, 12, 1),
        effective_admission_deadline=date(2027, 1, 15),
        result_group=ResultGroup.CONFIRMED_ELIGIBLE,
        rank=1,
        total_score=92.5,
        score_breakdown={"field_alignment": 30.0, "funding_coverage": 25.0},
        recommendation_rationale="Fully funded scholarship matching computer science focus.",
        confidence="high",
        admission_eligible=EligibilityStatus.ELIGIBLE,
        scholarship_eligible=EligibilityStatus.ELIGIBLE,
        cycle_status=CycleStatus.CURRENT,
    )
    assert opp.canonical_url == "https://www.ox.ac.uk/clarendon/apply"
    assert opp.source_type == SourceType.OFFICIAL_PROVIDER
    assert len(opp.deadlines) == 2
    assert opp.effective_scholarship_deadline == date(2026, 12, 1)
    assert opp.effective_admission_deadline == date(2027, 1, 15)
    assert opp.result_group == ResultGroup.CONFIRMED_ELIGIBLE
    assert opp.rank == 1
    assert opp.total_score == 92.5


def test_verified_opportunity_canonical_url_scheme_validation():
    """Verify canonical_url rejects invalid schemes."""
    with pytest.raises(ValidationError) as exc_info:
        VerifiedOpportunity(
            opportunity_id="opp-p1-bad",
            session_id="sess-p1",
            institution="Cambridge",
            program_name="Gates Cambridge",
            official_url="https://gatescambridge.org",
            canonical_url="ftp://gatescambridge.org/repo",  # Invalid scheme!
            source_url="https://gatescambridge.org",
            verification_tier=VerificationTier.T2,
        )
    assert "canonical_url must start with http:// or https://" in str(exc_info.value)
