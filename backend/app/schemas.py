"""Pydantic data models and schemas for ScholarSwarm AI.

Defines canonical types, strict enums, cross-field validation, and structured
data contracts across all multi-agent stages (SPA, ORA, EEVA, MRA, ASA).
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)



# ============================================================================
# Strict Enums
# ============================================================================

class VerificationTier(str, Enum):
    """Four-tier evidence verification model.

    T1: Discovered via search query; official URL not yet fetched.
    T2: Source Accessible; official URL returned HTTP 2xx and content retrieved.
    T3: Evidence Extracted; structured requirements extracted from page content.
    T4: Fully Verified; requirements compared to profile, eligibility classified,
        and verbatim evidence excerpt recorded.
    """
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class EligibilityStatus(str, Enum):
    """Independent eligibility classification.

    ELIGIBLE: Explicit textual evidence confirms all criteria are met.
    INELIGIBLE: Documented evidence confirms a requirement is not met.
    UNKNOWN: Evidence is absent, ambiguous, or profile data is missing.
        Never assume eligible when unknown.
    """
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNKNOWN = "unknown"


class CycleStatus(str, Enum):
    """Application cycle currency status.

    CURRENT: Verified future deadline AND matching intake session.
    EXPIRED: Stated deadline has passed.
    UNCERTAIN: Deadline or intake year missing, ambiguous, or unverifiable.
    """
    CURRENT = "current"
    EXPIRED = "expired"
    UNCERTAIN = "uncertain"


class DegreeLevel(str, Enum):
    """Target academic degree level."""
    UNDERGRADUATE = "undergraduate"
    MASTERS = "masters"
    PHD = "phd"
    POSTDOC = "postdoc"


class FundingCoverage(str, Enum):
    """Degree of funding coverage."""
    FULL = "full"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class OpportunityType(str, Enum):
    """Type of academic opportunity."""
    SCHOLARSHIP = "scholarship"
    PROGRAM = "program"
    FELLOWSHIP = "fellowship"


class AgentRole(str, Enum):
    """Autonomous agent roles in the ScholarSwarm system."""
    SPA = "SPA"      # Student Profile Agent
    ORA = "ORA"      # Opportunity Research Agent
    EEVA = "EEVA"    # Eligibility & Evidence Verification Agent
    MRA = "MRA"      # Matching & Ranking Agent
    ASA = "ASA"      # Application / SOP Assistant
    SYSTEM = "SYSTEM"


class SkillConfidence(str, Enum):
    """Confidence tier for extracted skills; no skills may be hallucinated."""
    EXPLICIT = "explicit"  # Directly stated in text
    INFERRED = "inferred"  # Derived from concrete project descriptions


# ============================================================================
# Student Profile Models
# ============================================================================

class SkillEntry(BaseModel):
    """Extracted student skill with source confidence level."""
    model_config = ConfigDict(extra="forbid")

    skill: str = Field(..., min_length=1, max_length=100, description="Name of the skill")
    confidence: SkillConfidence = Field(
        ..., description="Whether explicitly stated or inferred from projects"
    )


class GitHubRepo(BaseModel):
    """Public GitHub repository metadata without exaggerated claims."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Repository name")
    language: Optional[str] = Field(None, description="Primary programming language")
    stars: int = Field(0, ge=0, description="Star count")
    description: Optional[str] = Field(None, description="Repository description")


class StudentProfile(BaseModel):
    """Canonical student profile extracted from uploaded documents and public data.

    Enforces that CGPA requires an explicit grading scale. Does not perform
    arbitrary linear normalization across disparate grading systems.
    """
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., min_length=1, description="Unique session identifier")
    name: Optional[str] = Field(None, max_length=200, description="Student full name")
    email: Optional[str] = Field(None, max_length=254, description="Student email address")
    nationality: Optional[str] = Field(None, max_length=100, description="Country of citizenship")
    current_degree: Optional[str] = Field(None, max_length=150, description="Current or most recent degree")
    cgpa: Optional[float] = Field(None, ge=0.0, description="Cumulative Grade Point Average")
    cgpa_scale: Optional[float] = Field(None, gt=0.0, description="Scale maximum for CGPA (e.g. 4.0, 10.0)")
    ielts_score: Optional[float] = Field(None, ge=0.0, le=9.0, description="IELTS overall band score")
    toefl_score: Optional[int] = Field(None, ge=0, le=120, description="TOEFL iBT total score")
    gre_score: Optional[int] = Field(None, ge=260, le=340, description="GRE combined score")
    gmat_score: Optional[int] = Field(None, ge=200, le=800, description="GMAT total score")
    work_experience_years: Optional[float] = Field(None, ge=0.0, description="Years of professional experience")
    publications: List[str] = Field(default_factory=list, description="Academic publications or papers")
    awards: List[str] = Field(default_factory=list, description="Academic or professional honors")
    languages_known: List[str] = Field(default_factory=list, description="Spoken/written languages")
    github_repos: List[GitHubRepo] = Field(default_factory=list, description="Verified public repositories")
    skills_extracted: List[SkillEntry] = Field(default_factory=list, description="Extracted skills")
    field_of_study: str = Field(..., min_length=1, max_length=150, description="Target academic field")
    target_degree: DegreeLevel = Field(..., description="Target degree level (masters, phd, etc.)")
    preferred_countries: List[str] = Field(default_factory=list, description="Target study destinations")
    parse_warnings: List[str] = Field(default_factory=list, description="Non-fatal parsing warnings")
    parse_errors: List[str] = Field(default_factory=list, description="Recoverable parser errors")
    created_at: datetime = Field(default_factory=utc_now, description="Record creation timestamp")

    @model_validator(mode="after")
    def validate_cgpa_and_scale(self) -> "StudentProfile":
        """Ensure that if CGPA is provided, the grading scale is also provided and valid."""
        if self.cgpa is not None:
            if self.cgpa_scale is None:
                raise ValueError("cgpa_scale is required whenever cgpa is provided.")
            if self.cgpa > self.cgpa_scale:
                raise ValueError(
                    f"cgpa ({self.cgpa}) cannot exceed the specified cgpa_scale ({self.cgpa_scale})."
                )
        return self


# ============================================================================
# Opportunity Models
# ============================================================================

class OpportunityStub(BaseModel):
    """Initial opportunity stub discovered by the Opportunity Research Agent (ORA)."""
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str = Field(..., min_length=1, description="Unique opportunity identifier (UUID)")
    session_id: str = Field(..., min_length=1, description="Associated session identifier")
    type: OpportunityType = Field(default=OpportunityType.SCHOLARSHIP, description="Opportunity type")
    institution: str = Field(..., min_length=1, max_length=250, description="University or funding organization")
    program_or_scholarship_name: str = Field(..., min_length=1, max_length=250, description="Official title")
    official_url: str = Field(..., min_length=8, description="Official source URL")
    country: Optional[str] = Field(None, max_length=100, description="Host country")
    degree_level: Optional[DegreeLevel] = Field(None, description="Eligible degree level")
    search_query_used: str = Field(..., min_length=1, description="Exact search query string for traceability")
    search_result_snippet: str = Field(..., description="Snippet returned by search engine")
    search_timestamp: datetime = Field(default_factory=utc_now, description="Discovery timestamp")
    url_reachable: Optional[bool] = Field(None, description="Result of initial URL reachability probe")
    url_http_status: Optional[int] = Field(None, description="HTTP status code from probe")
    dedup_hash: str = Field(..., min_length=16, description="SHA256 deduplication hash")
    verification_tier: VerificationTier = Field(
        default=VerificationTier.T1, description="All stubs start at T1 (Discovered)"
    )

    @field_validator("official_url")
    @classmethod
    def validate_url_scheme(cls, v: str) -> str:
        v_clean = v.strip()
        if not (v_clean.startswith("http://") or v_clean.startswith("https://")):
            raise ValueError("official_url must start with http:// or https://")
        return v_clean


class VerifiedOpportunity(BaseModel):
    """Verified opportunity enriched with source evidence and independent eligibility statuses."""
    model_config = ConfigDict(extra="forbid")

    opportunity_id: str = Field(..., min_length=1, description="Unique opportunity identifier")
    session_id: str = Field(..., min_length=1, description="Associated session identifier")
    institution: str = Field(..., min_length=1, max_length=250, description="Host institution")
    program_name: str = Field(..., min_length=1, max_length=250, description="Program or scholarship title")
    type: OpportunityType = Field(default=OpportunityType.SCHOLARSHIP, description="Opportunity type")
    official_url: str = Field(..., min_length=8, description="Official primary source URL")
    country: Optional[str] = Field(None, max_length=100, description="Country of study")
    degree_level: Optional[DegreeLevel] = Field(None, description="Target degree level")

    # Provenance and verification
    verification_tier: VerificationTier = Field(
        ..., description="Verification tier achieved (T1-T4)"
    )
    page_accessible: bool = Field(False, description="Whether the official page was successfully fetched")
    page_http_status: Optional[int] = Field(None, description="HTTP response status code")
    page_fetch_timestamp: Optional[datetime] = Field(None, description="Timestamp when page was fetched")
    extraction_failed: bool = Field(False, description="Whether structured requirement extraction failed")
    conflicting_info_flags: List[str] = Field(
        default_factory=list, description="Explicit record of discrepancies (e.g. deadline conflict)"
    )

    # Extracted requirements (nullable when not found on official page)
    eligible_nationalities: Optional[List[str]] = Field(
        None, description="Explicitly stated eligible countries; null means not specified on page"
    )
    min_cgpa: Optional[float] = Field(None, ge=0.0, description="Minimum required CGPA if specified")
    cgpa_scale: Optional[float] = Field(None, gt=0.0, description="Grading scale for min_cgpa")
    english_test: Optional[str] = Field(None, description="Required English language test (IELTS, TOEFL)")
    english_min_score: Optional[str] = Field(None, description="Verbatim minimum score requirement")
    gre_required: Optional[bool] = Field(None, description="Whether GRE is mandatory")
    funding_amount_text: Optional[str] = Field(
        None, description="Verbatim funding description; not converted to arbitrary numbers"
    )
    funding_coverage: FundingCoverage = Field(
        default=FundingCoverage.UNKNOWN, description="Full, partial, or unknown coverage"
    )
    application_deadline: Optional[date] = Field(
        None, description="Exact application deadline date; null if unverified"
    )
    intake_session: Optional[str] = Field(
        None, description="Target academic intake (e.g. 'Fall 2026', '2026-2027')"
    )
    required_documents: List[str] = Field(
        default_factory=list, description="Documents required for application"
    )
    application_instructions: Optional[str] = Field(
        None, description="Official steps to apply"
    )

    # Grounding & Evidence
    evidence_excerpt: Optional[str] = Field(
        None, max_length=1000, description="Verbatim quote from the official page supporting requirements"
    )
    source_url: str = Field(..., description="Traceable source URL matching official_url")
    last_verified: Optional[datetime] = Field(None, description="Verification execution timestamp")

    # Independent Eligibility Dimensions
    admission_eligible: EligibilityStatus = Field(
        default=EligibilityStatus.UNKNOWN,
        description="University program admission eligibility",
    )
    admission_ineligible_reasons: List[str] = Field(
        default_factory=list, description="Specific criteria causing admission ineligibility"
    )
    scholarship_eligible: EligibilityStatus = Field(
        default=EligibilityStatus.UNKNOWN,
        description="Scholarship/funding award eligibility",
    )
    scholarship_ineligible_reasons: List[str] = Field(
        default_factory=list, description="Specific criteria causing scholarship ineligibility"
    )
    missing_student_fields: List[str] = Field(
        default_factory=list, description="Student profile fields needed to resolve unknown eligibility"
    )

    # Currency
    cycle_status: CycleStatus = Field(
        default=CycleStatus.UNCERTAIN,
        description="Current, expired, or uncertain intake cycle",
    )

    @field_validator("official_url", "source_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v_clean = v.strip()
        if not (v_clean.startswith("http://") or v_clean.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v_clean

    @model_validator(mode="after")
    def validate_min_cgpa_scale(self) -> "VerifiedOpportunity":
        if self.min_cgpa is not None and self.cgpa_scale is None:
            raise ValueError("cgpa_scale is required whenever min_cgpa is provided.")
        return self


# ============================================================================
# Ranking and Output Models
# ============================================================================

class RankedOpportunity(BaseModel):
    """Ranked opportunity with explainable factor breakdown."""
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(..., ge=1, description="1-based rank position")
    opportunity_id: str = Field(..., min_length=1, description="Associated opportunity ID")
    total_score: float = Field(..., ge=0.0, le=100.0, description="Overall explainable score out of 100")
    score_breakdown: Dict[str, float] = Field(
        ..., description="Named factor contributions summing to total_score"
    )
    recommendation_rationale: str = Field(
        ..., min_length=10, description="Explainable rationale grounded in score factors"
    )
    action_items: List[str] = Field(
        default_factory=list, description="Missing requirements or documents to gather"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence grade based on data completeness and verification tier"
    )


class SOPDraft(BaseModel):
    """Evidence-grounded Statement of Purpose draft."""
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(..., min_length=1, description="Unique SOP draft ID")
    session_id: str = Field(..., min_length=1, description="Associated session ID")
    opportunity_id: str = Field(..., min_length=1, description="Target opportunity ID")
    institution: str = Field(..., min_length=1, description="Target institution")
    program_name: str = Field(..., min_length=1, description="Target academic program")
    sop_text: str = Field(..., min_length=100, description="Generated SOP draft text")
    word_count: int = Field(..., ge=1, description="Total word count")
    cited_profile_elements: List[str] = Field(
        default_factory=list, description="Student profile elements cited in the text"
    )
    missing_info_prompts: List[str] = Field(
        default_factory=list, description="Questions for student to add personal context"
    )
    suggested_revisions: List[str] = Field(
        default_factory=list, description="Actionable editorial suggestions"
    )
    generated_at: datetime = Field(default_factory=utc_now, description="Generation timestamp")


# ============================================================================
# Pipeline Event & Diagnostics Models
# ============================================================================

class PipelineEvent(BaseModel):
    """Structured event emitted during multi-agent pipeline execution for polling UI."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, description="Unique event identifier")
    session_id: str = Field(..., min_length=1, description="Associated session identifier")
    agent: AgentRole = Field(..., description="Agent role emitting the event")
    event_type: str = Field(..., min_length=1, description="Machine-readable event type")
    message: str = Field(..., min_length=1, description="Human-readable progress description")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured event metadata")
    created_at: datetime = Field(default_factory=utc_now, description="Event timestamp")


class PipelineError(BaseModel):
    """Structured error logged when an agent encounters an exception or condition."""
    model_config = ConfigDict(extra="forbid")

    error_id: str = Field(..., min_length=1, description="Unique error identifier")
    session_id: str = Field(..., min_length=1, description="Associated session identifier")
    agent: AgentRole = Field(..., description="Agent role where error occurred")
    error_type: str = Field(..., min_length=1, description="Error classification")
    message: str = Field(..., min_length=1, description="Error message")
    recoverable: bool = Field(True, description="Whether pipeline continued past this error")
    created_at: datetime = Field(default_factory=utc_now, description="Error timestamp")


class HealthResponse(BaseModel):
    """Response model for the system health check endpoint."""
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "unhealthy"] = Field(..., description="Service health state")
    database: Literal["connected", "disconnected"] = Field(..., description="Database connection state")
    version: str = Field("0.1.0", description="Application version")
    timestamp: datetime = Field(default_factory=utc_now, description="Current server UTC timestamp")

