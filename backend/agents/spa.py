"""Student Profile Agent (SPA) for ScholarSwarm AI.

Extracts canonical academic profiles from parsed document text and public GitHub metadata
using deterministic, rule-grounded parsers. Strictly prohibits hallucination or inventing
unverified academic facts, differentiates explicit vs. inferred skills, and requires
explicit grading scales for CGPA.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.schemas import (
    DegreeLevel,
    GitHubRepo,
    SkillConfidence,
    SkillEntry,
    StudentProfile,
)
from backend.app.utils.github_client import fetch_github_repos


# ============================================================================
# Skill Catalogs & Canonical Normalization
# ============================================================================

KNOWN_SKILLS = [
    # Programming Languages
    "Python", "Java", "C++", "C", "C#", "Rust", "Go", "TypeScript", "JavaScript",
    "Kotlin", "Swift", "R", "Scala", "MATLAB", "SQL", "Ruby", "PHP", "Dart",
    # Frameworks & Libraries
    "FastAPI", "Django", "Flask", "React", "Vue", "Angular", "Next.js", "Node.js",
    "PyTorch", "TensorFlow", "Keras", "Scikit-Learn", "Pandas", "NumPy", "OpenCV",
    "Hugging Face", "LangChain", "Spring Boot", "Express",
    # Systems, Cloud & DevOps
    "Docker", "Kubernetes", "Linux", "Git", "AWS", "Google Cloud", "Azure",
    "CI/CD", "Terraform", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka",
    "GraphQL", "REST APIs", "Microservices",
    # Disciplines & Concepts
    "Machine Learning", "Deep Learning", "Computer Vision",
    "Natural Language Processing", "Data Science", "Data Analysis",
    "Distributed Systems", "Algorithms", "Cybersecurity", "Embedded Systems",
    "Bioinformatics", "Quantum Computing", "Robotics", "Signal Processing",
]

# Case-insensitive mapping to canonical name
SKILL_LOOKUP = {s.lower(): s for s in KNOWN_SKILLS}

COMMON_LANGUAGES = [
    "English", "Spanish", "French", "German", "Mandarin", "Hindi", "Arabic",
    "Portuguese", "Russian", "Japanese", "Korean", "Italian", "Bengali", "Urdu",
]
LANG_LOOKUP = {lang.lower(): lang for lang in COMMON_LANGUAGES}


# ============================================================================
# Deterministic Extraction Helpers
# ============================================================================

def extract_email(text: str) -> Optional[str]:
    """Find the first valid email address in text."""
    pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b"
    match = re.search(pattern, text)
    return match.group(0) if match else None


def extract_name(text: str) -> Optional[str]:
    """Extract candidate student name from labeled or structural header text."""
    # 1. Look for explicit label: Name: Jane Doe
    label_pattern = r"(?i)\bName\s*[:=\-]\s*([A-Za-z\t .'\\-]{2,50})"
    match = re.search(label_pattern, text)
    if match:
        name = match.group(1).splitlines()[0].strip()
        if len(name.split()) >= 2:
            return name

    # 2. Inspect first 5 non-empty lines for typical name header
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        # Exclude typical CV/Resume title words and URLs
        lower = line.lower()
        if any(term in lower for term in ("curriculum", "resume", "cv", "page", "http", "email", "phone", "contact")):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.match(r"^[A-Z][a-zA-Z.'\-]*$", w) for w in words):
            return line

    return None


def extract_cgpa_and_scale_detailed(text: str) -> Dict[str, Any]:
    """Extract CGPA and grading scale with strict validation, evidence provenance, and ambiguity detection.

    Safeguards:
    - Never guesses or silently invents a scale (e.g. 4.0 or 10.0).
    - Preserves unscaled CGPA with scale=None and logs a warning.
    - Preserves percentage separately on scale=100.0.
    - Prioritizes university CGPA over secondary percentages when both appear.
    - Flags ambiguity when conflicting or multiple grading metrics are detected.
    """
    warnings: List[str] = []

    # 1. Search for scaled CGPA: "CGPA: 3.85/4.0", "7.6/10 CGPA", "GPA 8.5 out of 10.0"
    scale_pattern_1 = (
        r"(?i)\b(?:CGPA|GPA|Grade Point Average|Cumulative GPA)\s*[:=\-]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:\/|\bout of\b)\s*([0-9]+(?:\.[0-9]+)?)"
    )
    scale_pattern_2 = (
        r"(?i)\b([0-9]+(?:\.[0-9]+)?)\s*(?:\/|\bout of\b)\s*([0-9]+(?:\.[0-9]+)?)\s*"
        r"(?:CGPA|GPA|Grade Point Average|Cumulative GPA)\b"
    )

    match_scaled = re.search(scale_pattern_1, text) or re.search(scale_pattern_2, text)

    # 2. Search for unscaled CGPA: "CGPA: 7.6", "7.6 CGPA", "GPA 3.85"
    unscaled_pattern_1 = (
        r"(?i)\b(?:CGPA|GPA|Grade Point Average|Cumulative GPA)\s*[:=\-]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\b(?!\s*(?:\/|\bout of\b|%))"
    )
    unscaled_pattern_2 = (
        r"(?i)\b([0-9]+(?:\.[0-9]+)?)\b\s*(?:CGPA|GPA)\b(?!\s*(?:\/|\bout of\b|%))"
    )
    match_unscaled = re.search(unscaled_pattern_1, text) or re.search(unscaled_pattern_2, text)

    # 3. Search for percentage: "Percentage: 76%", "Aggregate: 82%", "76% marks"
    percentage_pattern = (
        r"(?i)\b(?:Percentage|Aggregate|Marks|Score)\s*[:=\-]?\s*"
        r"([0-9]+(?:\.[0-9]+)?)\s*%"
    )
    match_pct = re.search(percentage_pattern, text)
    if not match_pct:
        match_pct = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:marks|aggregate|score|grade)\b", text, re.IGNORECASE)
    if not match_pct:
        match_pct = re.search(r"(?i)\b(?:Class\s*(?:10|12|X|XII)(?:th)?|Secondary|CBSE|ICSE).*?([0-9]+(?:\.[0-9]+)?)\s*%", text)

    # Analyze candidates
    cgpa_cand: Optional[Tuple[float, Optional[float], str]] = None
    scaled_attempted = False
    if match_scaled:
        scaled_attempted = True
        try:
            v = float(match_scaled.group(1))
            s = float(match_scaled.group(2))
            if s > 0 and v <= s:
                cgpa_cand = (v, s, match_scaled.group(0).strip())
            elif s <= 0:
                warnings.append(f"Invalid non-positive CGPA scale ({s}) found; omitted.")
            else:
                warnings.append(f"CGPA ({v}) cannot exceed grading scale ({s}); omitted.")
        except ValueError:
            pass

    if not scaled_attempted and match_unscaled:
        try:
            v = float(match_unscaled.group(1))
            warnings.append(
                f"CGPA value '{v}' was detected without an explicit grading scale. "
                "Preserving raw value with scale marked as unknown."
            )
            cgpa_cand = (v, None, match_unscaled.group(0).strip())
        except ValueError:
            pass

    pct_cand: Optional[Tuple[float, float, str]] = None
    if match_pct:
        try:
            p_val = float(match_pct.group(1))
            if 0 <= p_val <= 100.0:
                pct_cand = (p_val, 100.0, match_pct.group(0).strip())
            else:
                warnings.append(f"Percentage ({p_val}) outside valid range (0-100%); omitted.")
        except ValueError:
            pass

    # Check for ambiguity between CGPA and Percentage
    if cgpa_cand and pct_cand:
        c_val, c_scale, c_ev = cgpa_cand
        p_val, _, p_ev = pct_cand
        is_ambiguous = True
        amb_msg = (
            f"Multiple academic records found in document: CGPA '{c_val}' ({c_ev}) "
            f"and Percentage '{p_val}%' ({p_ev}). Higher-education CGPA prioritized; "
            "please verify your college grading scale."
        )
        warnings.append(amb_msg)
        return {
            "val": c_val,
            "scale": c_scale,
            "warnings": warnings,
            "evidence": c_ev,
            "source": "Extracted from uploaded document",
            "is_ambiguous": is_ambiguous,
            "ambiguity_reason": amb_msg,
        }

    if cgpa_cand:
        c_val, c_scale, c_ev = cgpa_cand
        return {
            "val": c_val,
            "scale": c_scale,
            "warnings": warnings,
            "evidence": c_ev,
            "source": "Extracted from uploaded document",
            "is_ambiguous": False,
            "ambiguity_reason": None,
        }

    if pct_cand:
        p_val, p_scale, p_ev = pct_cand
        return {
            "val": p_val,
            "scale": p_scale,
            "warnings": warnings,
            "evidence": p_ev,
            "source": "Extracted from uploaded document",
            "is_ambiguous": False,
            "ambiguity_reason": None,
        }

    # Standalone number labeled as grade (e.g. "Grade: 76", "Aggregate: 76")
    bare_grade_pattern = r"(?i)\b(?:Grade|Marks|Aggregate|Score)\s*[:=\-]\s*([0-9]+(?:\.[0-9]+)?)\b"
    match_bare = re.search(bare_grade_pattern, text)
    if match_bare:
        try:
            b_val = float(match_bare.group(1))
            amb_msg = f"Grade value '{b_val}' detected without scale or percentage symbol. Confirmation required."
            warnings.append(amb_msg)
            return {
                "val": b_val,
                "scale": None,
                "warnings": warnings,
                "evidence": match_bare.group(0).strip(),
                "source": "Extracted from uploaded document",
                "is_ambiguous": True,
                "ambiguity_reason": amb_msg,
            }
        except ValueError:
            pass

    return {
        "val": None,
        "scale": None,
        "warnings": warnings,
        "evidence": None,
        "source": None,
        "is_ambiguous": False,
        "ambiguity_reason": None,
    }


def extract_cgpa_and_scale(text: str) -> Tuple[Optional[float], Optional[float], List[str]]:
    """Extract CGPA and grading scale with strict validation.

    Safeguard: Never guesses or invents a scale (e.g. 4.0 or 10.0). If CGPA is found
    without an explicit scale, the CGPA is preserved with scale=None and a warning is logged.
    """
    res = extract_cgpa_and_scale_detailed(text)
    return res["val"], res["scale"], res["warnings"]


def extract_standardized_tests(text: str) -> Tuple[
    Optional[float], Optional[int], Optional[int], Optional[int], List[str]
]:
    """Extract IELTS, TOEFL, GRE, and GMAT scores with range bounds."""
    warnings: List[str] = []
    ielts: Optional[float] = None
    toefl: Optional[int] = None
    gre: Optional[int] = None
    gmat: Optional[int] = None

    # IELTS (0.0 - 9.0)
    ielts_match = re.search(r"(?i)\bIELTS\b.*?\b(?:overall|band|score)?\s*[:=\-]?\s*([0-9]+(?:\.[0-9]+)?)\b", text)
    if ielts_match:
        try:
            score = float(ielts_match.group(1))
            if 0.0 <= score <= 9.0:
                ielts = score
            else:
                warnings.append(f"IELTS score {score} is outside valid band range (0.0-9.0); omitted.")
        except ValueError:
            pass

    # TOEFL (0 - 120)
    toefl_match = re.search(r"(?i)\bTOEFL\b.*?\b(?:iBT|total|score)?\s*[:=\-]?\s*([0-9]+)\b", text)
    if toefl_match:
        try:
            score = int(toefl_match.group(1))
            if 0 <= score <= 120:
                toefl = score
            else:
                warnings.append(f"TOEFL score {score} is outside valid iBT range (0-120); omitted.")
        except ValueError:
            pass

    # GRE (260 - 340)
    gre_match = re.search(r"(?i)\bGRE\b.*?\b(?:combined|total|score)?\s*[:=\-]?\s*([0-9]+)\b", text)
    if gre_match:
        try:
            score = int(gre_match.group(1))
            if 260 <= score <= 340:
                gre = score
            else:
                warnings.append(f"GRE score {score} is outside valid range (260-340); omitted.")
        except ValueError:
            pass

    # GMAT (200 - 800)
    gmat_match = re.search(r"(?i)\bGMAT\b.*?\b(?:total|score)?\s*[:=\-]?\s*([0-9]+)\b", text)
    if gmat_match:
        try:
            score = int(gmat_match.group(1))
            if 200 <= score <= 800:
                gmat = score
            else:
                warnings.append(f"GMAT score {score} is outside valid range (200-800); omitted.")
        except ValueError:
            pass

    return ielts, toefl, gre, gmat, warnings


def extract_work_experience_years(text: str) -> Optional[float]:
    """Extract years of professional work experience from text."""
    pattern = r"(?i)\b(\d+(?:\.\d+)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:work\s+experience|professional\s+experience|industry\s+experience|experience)\b"
    match = re.search(pattern, text)
    if match:
        try:
            val = float(match.group(1))
            if 0.0 <= val <= 50.0:
                return val
        except ValueError:
            pass
    return None


def extract_degree_title(text: str) -> Optional[str]:
    """Extract candidate current degree or academic title."""
    degree_patterns = [
        r"(?i)\b(?:Bachelor\s+of\s+(?:Science|Engineering|Technology|Arts|Commerce|Business)|B\.?Sc\.?|B\.?S\.?|B\.?Tech\.?|B\.?E\.?|B\.?A\.?)\s*(?:in\s+[A-Za-z\s]+)?",
        r"(?i)\b(?:Master\s+of\s+(?:Science|Engineering|Technology|Arts|Business\s+Administration)|M\.?Sc\.?|M\.?S\.?|M\.?Tech\.?|M\.?E\.?|M\.?A\.?|MBA)\s*(?:in\s+[A-Za-z\s]+)?",
        r"(?i)\b(?:Doctor\s+of\s+Philosophy|Ph\.?D\.?)\s*(?:in\s+[A-Za-z\s]+)?",
    ]
    for pattern in degree_patterns:
        match = re.search(pattern, text)
        if match:
            # Clean and truncate candidate title
            candidate = match.group(0).strip()
            # Stop at line boundary or punctuation
            candidate = re.split(r"[\n\r,;|]", candidate)[0].strip()
            if candidate:
                return candidate
    return None


def extract_sections(text: str) -> Dict[str, str]:
    """Segment document text into conceptual sections based on headers."""
    section_patterns = {
        "skills": r"(?i)\b(?:technical\s+skills|skills\s*(?:&|and)\s*competencies|skills|technologies|tools\s*(?:&|and)\s*technologies)\b",
        "projects": r"(?i)\b(?:projects|academic\s+projects|key\s+projects|personal\s+projects)\b",
        "experience": r"(?i)\b(?:work\s+experience|professional\s+experience|experience|employment)\b",
        "education": r"(?i)\b(?:education|academic\s+background|academics)\b",
        "publications": r"(?i)\b(?:publications|research\s+papers|conference\s+papers|selected\s+publications)\b",
        "awards": r"(?i)\b(?:honors\s*(?:&|and)\s*awards|awards|achievements|honors|scholarships)\b",
        "languages": r"(?i)\b(?:languages|languages\s+known|spoken\s+languages)\b",
    }

    # Find start offsets of matched section headers
    found_headers: List[Tuple[int, str]] = []
    for section_name, pat in section_patterns.items():
        for match in re.finditer(pat, text):
            found_headers.append((match.start(), section_name))

    found_headers.sort(key=lambda x: x[0])

    sections: Dict[str, str] = {}
    if not found_headers:
        sections["body"] = text
        return sections

    # First segment before any section header
    if found_headers[0][0] > 0:
        sections["header"] = text[: found_headers[0][0]]

    for i in range(len(found_headers)):
        start_idx, name = found_headers[i]
        end_idx = found_headers[i + 1][0] if i + 1 < len(found_headers) else len(text)
        content = text[start_idx:end_idx].strip()
        sections[name] = sections.get(name, "") + "\n" + content

    return sections


def extract_skills(sections: Dict[str, str], full_text: str) -> List[SkillEntry]:
    """Differentiate explicitly listed skills from skills inferred from project descriptions.

    Safeguard: Skills found in explicit skill sections receive SkillConfidence.EXPLICIT.
    Skills identified in projects/experience or document text receive SkillConfidence.INFERRED.
    No hallucinated skills are permitted.
    """
    explicit_skills: Set[str] = set()
    inferred_skills: Set[str] = set()

    skills_text = sections.get("skills", "")
    projects_text = sections.get("projects", "") + " " + sections.get("experience", "")

    # 1. Search for skills in explicit skills section
    for lower_skill, canonical in SKILL_LOOKUP.items():
        pattern = r"(?<!\w)" + re.escape(lower_skill) + r"(?!\w)"
        if re.search(pattern, skills_text, re.IGNORECASE):
            explicit_skills.add(canonical)

    # 2. Search for skills in projects/experience sections
    for lower_skill, canonical in SKILL_LOOKUP.items():
        if canonical in explicit_skills:
            continue
        pattern = r"(?<!\w)" + re.escape(lower_skill) + r"(?!\w)"
        if re.search(pattern, projects_text, re.IGNORECASE):
            inferred_skills.add(canonical)

    # 3. If no skills section was found in document, infer skills from body
    if not explicit_skills:
        for lower_skill, canonical in SKILL_LOOKUP.items():
            pattern = r"(?<!\w)" + re.escape(lower_skill) + r"(?!\w)"
            if re.search(pattern, full_text, re.IGNORECASE):
                inferred_skills.add(canonical)

    skill_entries: List[SkillEntry] = []
    for skill in sorted(explicit_skills):
        skill_entries.append(SkillEntry(skill=skill, confidence=SkillConfidence.EXPLICIT))
    for skill in sorted(inferred_skills):
        skill_entries.append(SkillEntry(skill=skill, confidence=SkillConfidence.INFERRED))

    return skill_entries


def extract_bullet_list(text: str, max_items: int = 10) -> List[str]:
    """Extract individual bullet items or numbered lines from section content."""
    items: List[str] = []
    lines = text.splitlines()
    for line in lines[1:]:  # Skip section header itself
        clean = line.strip()
        if not clean:
            continue
        # Strip leading bullet indicators (-, *, •, [1], 1.)
        clean_item = re.sub(r"^(?:[\-\*•\u2022]|\(?\d+[\.\)])\s*", "", clean).strip()
        if len(clean_item) >= 5 and clean_item not in items:
            items.append(clean_item)
            if len(items) >= max_items:
                break
    return items


def extract_languages(text: str) -> List[str]:
    """Extract spoken/written languages from language section or text."""
    found: Set[str] = set()
    for lower_lang, canonical in LANG_LOOKUP.items():
        pattern = r"(?<!\w)" + re.escape(lower_lang) + r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            found.add(canonical)
    return sorted(list(found))


def find_github_url_in_text(text: str) -> Optional[str]:
    """Detect GitHub profile URL embedded in document body."""
    pattern = r"https?://(?:www\.)?github\.com/[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}/?"
    match = re.search(pattern, text)
    return match.group(0) if match else None


# ============================================================================
# Main Agent Invocation
# ============================================================================

def extract_student_profile(
    session_id: str,
    document_text: str,
    field_of_study: str,
    target_degree: DegreeLevel,
    preferred_countries: Optional[List[str]] = None,
    github_url: Optional[str] = None,
    document_warnings: Optional[List[str]] = None,
    user_overrides: Optional[Dict[str, Any]] = None,
) -> StudentProfile:
    """Execute the Student Profile Agent (SPA) to construct a validated StudentProfile.

    Orchestrates deterministic parsing across contact information, academic records,
    standardized tests, experience, skills with confidence grading, and GitHub metadata.
    User overrides, if provided, take precedence over extracted document values.
    """
    warnings: List[str] = list(document_warnings or [])
    errors: List[str] = []

    # Segment document into sections
    sections = extract_sections(document_text)

    # 1. Contact and personal info
    name = extract_name(document_text)
    email = extract_email(document_text)
    current_degree = extract_degree_title(document_text)
    nationality = None

    # 2. CGPA and Scale
    cgpa, cgpa_scale, cgpa_warnings = extract_cgpa_and_scale(document_text)
    warnings.extend(cgpa_warnings)

    # 3. Standardized Test Scores
    ielts, toefl, gre, gmat, test_warnings = extract_standardized_tests(document_text)
    warnings.extend(test_warnings)

    # 4. Work Experience
    work_exp = extract_work_experience_years(document_text)

    # 5. Skills extraction with strict confidence differentiation
    skills_extracted = extract_skills(sections, document_text)

    # 6. Publications and Awards
    publications: List[str] = []
    if "publications" in sections:
        publications = extract_bullet_list(sections["publications"])

    awards: List[str] = []
    if "awards" in sections:
        awards = extract_bullet_list(sections["awards"])

    # 7. Languages
    languages_text = sections.get("languages", document_text)
    languages_known = extract_languages(languages_text)

    # 8. GitHub metadata resolution
    active_github_url = github_url or find_github_url_in_text(document_text)
    github_repos: List[GitHubRepo] = []
    if active_github_url:
        repos, gh_warnings = fetch_github_repos(active_github_url)
        github_repos = repos
        warnings.extend(gh_warnings)

    # Apply explicit user-verified overrides
    if user_overrides:
        if "name" in user_overrides and user_overrides["name"] is not None:
            name = user_overrides["name"]
        if "email" in user_overrides and user_overrides["email"] is not None:
            email = user_overrides["email"]
        if "nationality" in user_overrides and user_overrides["nationality"] is not None:
            nationality = user_overrides["nationality"]
        if "current_degree" in user_overrides and user_overrides["current_degree"] is not None:
            current_degree = user_overrides["current_degree"]
        if "cgpa" in user_overrides:
            cgpa = user_overrides["cgpa"]
        if "cgpa_scale" in user_overrides:
            cgpa_scale = user_overrides["cgpa_scale"]
        if "ielts_score" in user_overrides:
            ielts = user_overrides["ielts_score"]
        if "toefl_score" in user_overrides:
            toefl = user_overrides["toefl_score"]
        if "gre_score" in user_overrides:
            gre = user_overrides["gre_score"]
        if "gmat_score" in user_overrides:
            gmat = user_overrides["gmat_score"]
        if "work_experience_years" in user_overrides:
            work_exp = user_overrides["work_experience_years"]

    # Clean preferred countries
    countries = [c.strip() for c in (preferred_countries or []) if c.strip()]

    return StudentProfile(
        session_id=session_id,
        name=name,
        email=email,
        nationality=nationality,
        current_degree=current_degree,
        cgpa=cgpa,
        cgpa_scale=cgpa_scale,
        ielts_score=ielts,
        toefl_score=toefl,
        gre_score=gre,
        gmat_score=gmat,
        work_experience_years=work_exp,
        publications=publications,
        awards=awards,
        languages_known=languages_known,
        github_repos=github_repos,
        skills_extracted=skills_extracted,
        field_of_study=field_of_study.strip(),
        target_degree=target_degree,
        preferred_countries=countries,
        parse_warnings=warnings,
        parse_errors=errors,
    )
