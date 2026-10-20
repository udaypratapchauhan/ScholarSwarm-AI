"""Deterministic unit tests for the Student Profile Agent (SPA).

Verifies fact preservation, CGPA scale requirements, standardized score validation,
strict separation of explicit vs. inferred skills, and GitHub metadata resolution.
"""

from unittest.mock import MagicMock
import pytest

from backend.agents.spa import (
    extract_cgpa_and_scale,
    extract_email,
    extract_name,
    extract_skills,
    extract_standardized_tests,
    extract_student_profile,
    extract_work_experience_years,
)
from backend.app.schemas import (
    DegreeLevel,
    GitHubRepo,
    SkillConfidence,
    StudentProfile,
)


# ============================================================================
# Basic Entity Extraction Tests
# ============================================================================

def test_extract_email():
    text = "Candidate resume\nContact: dev.candidate@university.edu\nPhone: 123-456"
    assert extract_email(text) == "dev.candidate@university.edu"

    assert extract_email("No email address provided in this text") is None


def test_extract_name():
    text_labeled = "Name: Alexandra Chen\nEmail: alex@example.com"
    assert extract_name(text_labeled) == "Alexandra Chen"

    text_header = "Michael Johnson\n123 College St\nmike@univ.edu\nEducation"
    assert extract_name(text_header) == "Michael Johnson"


def test_extract_work_experience_years():
    text = "Professional Experience: Over 3.5 years of work experience in software engineering."
    assert extract_work_experience_years(text) == 3.5

    text_short = "Has 2 yrs experience with cloud infrastructure."
    assert extract_work_experience_years(text_short) == 2.0


# ============================================================================
# CGPA Scale Enforcement (Mandatory Safeguards)
# ============================================================================

def test_extract_cgpa_with_explicit_scale():
    # Valid GPA on 4.0 scale
    text_4 = "Academic record: Cumulative GPA: 3.85/4.0 in Computer Science."
    cgpa, scale, warnings = extract_cgpa_and_scale(text_4)
    assert cgpa == 3.85
    assert scale == 4.0
    assert warnings == []

    # Valid GPA on 10.0 scale
    text_10 = "B.Tech in Electrical Engineering with CGPA: 8.9 out of 10.0"
    cgpa, scale, warnings = extract_cgpa_and_scale(text_10)
    assert cgpa == 8.9
    assert scale == 10.0
    assert warnings == []


def test_extract_cgpa_omits_unscaled_values_with_warning():
    """Safeguard: Never assume 4.0 or any scale when unstated."""
    text_unscaled = "Education:\nB.Sc in Mathematics, CGPA: 3.8, First Class Honours."
    cgpa, scale, warnings = extract_cgpa_and_scale(text_unscaled)
    assert cgpa is None
    assert scale is None
    assert len(warnings) == 1
    assert "without an explicit grading scale" in warnings[0]


def test_extract_cgpa_rejects_value_exceeding_scale():
    """Safeguard: CGPA cannot exceed stated scale maximum."""
    text_invalid = "Grade report: CGPA: 4.8/4.0"
    cgpa, scale, warnings = extract_cgpa_and_scale(text_invalid)
    assert cgpa is None
    assert scale is None
    assert len(warnings) == 1
    assert "cannot exceed grading scale" in warnings[0]


# ============================================================================
# Standardized Tests Extraction
# ============================================================================

def test_extract_standardized_tests_valid():
    text = (
        "Standardized Scores:\n"
        "IELTS overall band score: 7.5\n"
        "TOEFL iBT total score: 108\n"
        "GRE combined score: 326\n"
        "GMAT total score: 710\n"
    )
    ielts, toefl, gre, gmat, warnings = extract_standardized_tests(text)
    assert ielts == 7.5
    assert toefl == 108
    assert gre == 326
    assert gmat == 710
    assert warnings == []


def test_extract_standardized_tests_out_of_bounds_warns():
    text = "Scores: IELTS band: 10.5 (invalid), GRE score: 350 (invalid)"
    ielts, toefl, gre, gmat, warnings = extract_standardized_tests(text)
    assert ielts is None
    assert gre is None
    assert len(warnings) == 2


# ============================================================================
# Explicit vs. Inferred Skills Differentiation
# ============================================================================

def test_skills_confidence_distinction():
    sections = {
        "skills": "Technical Skills: Python, Docker, PostgreSQL, React",
        "projects": "Projects:\nBuilt an autonomous navigation bot using C++, ROS, and Machine Learning algorithms.",
        "experience": "Work Experience:\nDesigned data pipelines using Kafka and Go.",
    }
    entries = extract_skills(sections, "")
    entry_dict = {e.skill: e.confidence for e in entries}

    # Explicit skills from Technical Skills section
    assert entry_dict["Python"] == SkillConfidence.EXPLICIT
    assert entry_dict["Docker"] == SkillConfidence.EXPLICIT
    assert entry_dict["PostgreSQL"] == SkillConfidence.EXPLICIT
    assert entry_dict["React"] == SkillConfidence.EXPLICIT

    # Inferred skills from Projects / Experience
    assert entry_dict["C++"] == SkillConfidence.INFERRED
    assert entry_dict["Machine Learning"] == SkillConfidence.INFERRED
    assert entry_dict["Kafka"] == SkillConfidence.INFERRED
    assert entry_dict["Go"] == SkillConfidence.INFERRED


def test_skills_explicit_precedence_over_inferred():
    # If Python appears in both skills and projects, it must remain EXPLICIT
    sections = {
        "skills": "Technical Skills: Python",
        "projects": "Used Python and TensorFlow to build vision models.",
    }
    entries = extract_skills(sections, "")
    entry_dict = {e.skill: e.confidence for e in entries}
    assert entry_dict["Python"] == SkillConfidence.EXPLICIT
    assert entry_dict["TensorFlow"] == SkillConfidence.INFERRED


# ============================================================================
# Full Profile Extraction Pipeline
# ============================================================================

def test_extract_student_profile_end_to_end(monkeypatch):
    resume_text = """
    Jane Doe
    Email: jane.doe@mit.edu
    GitHub: https://github.com/janedoe-cs

    Education:
    Bachelor of Science in Computer Science
    Cumulative GPA: 3.92/4.0

    Technical Skills:
    Python, PyTorch, Docker, PostgreSQL

    Projects:
    Distributed Consensus Engine: Implemented Raft protocol in Go and Kubernetes.

    Test Scores:
    IELTS overall score: 8.0
    GRE total score: 330

    Languages:
    English, Spanish
    """

    mock_repos = [
        GitHubRepo(name="raft-go", language="Go", stars=35, description="Raft consensus in Go")
    ]
    monkeypatch.setattr(
        "backend.agents.spa.fetch_github_repos",
        lambda url: (mock_repos, []),
    )

    profile = extract_student_profile(
        session_id="test-spa-sess-1",
        document_text=resume_text,
        field_of_study="Artificial Intelligence",
        target_degree=DegreeLevel.MASTERS,
        preferred_countries=["USA", "Canada"],
    )

    assert isinstance(profile, StudentProfile)
    assert profile.session_id == "test-spa-sess-1"
    assert profile.name == "Jane Doe"
    assert profile.email == "jane.doe@mit.edu"
    assert profile.cgpa == 3.92
    assert profile.cgpa_scale == 4.0
    assert profile.ielts_score == 8.0
    assert profile.gre_score == 330
    assert profile.field_of_study == "Artificial Intelligence"
    assert profile.target_degree == DegreeLevel.MASTERS
    assert profile.preferred_countries == ["USA", "Canada"]
    assert "English" in profile.languages_known
    assert "Spanish" in profile.languages_known
    assert len(profile.github_repos) == 1
    assert profile.github_repos[0].name == "raft-go"

    # Verify skill confidence
    skills_map = {s.skill: s.confidence for s in profile.skills_extracted}
    assert skills_map["Python"] == SkillConfidence.EXPLICIT
    assert skills_map["PyTorch"] == SkillConfidence.EXPLICIT
    assert skills_map["Go"] == SkillConfidence.INFERRED
    assert skills_map["Kubernetes"] == SkillConfidence.INFERRED


def test_extract_student_profile_empty_document_does_not_invent_facts():
    """Safeguard: Empty or minimal text must not fabricate student data."""
    profile = extract_student_profile(
        session_id="test-spa-empty",
        document_text="Brief note without credentials.",
        field_of_study="Physics",
        target_degree=DegreeLevel.PHD,
        document_warnings=["Minimal text warning"],
    )

    assert profile.name is None
    assert profile.email is None
    assert profile.cgpa is None
    assert profile.cgpa_scale is None
    assert profile.ielts_score is None
    assert profile.github_repos == []
    assert profile.skills_extracted == []
    assert len(profile.parse_warnings) >= 1
