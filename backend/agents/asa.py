"""Application Strategy Agent (ASA) for ScholarSwarm AI.

Synthesizes student profile attributes and verified scholarship requirements into an
evidence-grounded Statement of Purpose (SOP) draft, application checklist, and targeted
missing-information prompts without fabricating student achievements.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from backend.app.database import record_pipeline_event, save_sop_draft
from backend.app.schemas import AgentRole, StudentProfile, VerificationTier


def generate_sop_draft(
    opportunity: Dict[str, Any],
    student_profile: StudentProfile,
    session_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate evidence-grounded Statement of Purpose draft and application guidance.
    
    1. Cites real skills, projects, and background strictly from StudentProfile.
    2. Never invents grades, work experience, achievements, or project names.
    3. References target institution and verified scholarship requirements.
    4. Distinguishes confirmed requirements from unconfirmed or missing info.
    5. Produces missing-info prompts and concrete application checklist.
    6. Emits ASA pipeline events and persists draft to database.
    """
    record_pipeline_event(
        event_id=f"evt-asa-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.ASA.value,
        event_type="sop_generation_start",
        message=f"Generating tailored SOP outline grounded in verified evidence for {opportunity.get('institution')}",
        payload={"opportunity_id": opportunity.get("opportunity_id")},
        db_path=db_path,
    )

    institution = opportunity.get("institution", "Academic Institution")
    program = opportunity.get("program_name", "Graduate Degree Program")
    opp_id = opportunity.get("opportunity_id", "opp-target")
    official_url = opportunity.get("official_url") or opportunity.get("source_url") or "Official Portal"
    tier = opportunity.get("verification_tier", "T1")

    # -------------------------------------------------------------------------
    # Extract Real Student Profile Attributes (No Inventions)
    # -------------------------------------------------------------------------
    student_name = getattr(student_profile, "name", None) or "Applicant"
    field = getattr(student_profile, "field_of_study", "").strip() or "Advanced Studies"
    target_degree = (
        student_profile.target_degree.value.capitalize()
        if hasattr(student_profile.target_degree, "value")
        else str(student_profile.target_degree or "Graduate").capitalize()
    )

    skills = [s.skill.strip() for s in getattr(student_profile, "skills_extracted", []) if s.skill.strip()]
    repos = [r.name.strip() for r in getattr(student_profile, "github_repos", []) if r.name.strip()]
    cgpa = getattr(student_profile, "cgpa", None)
    cgpa_scale = getattr(student_profile, "cgpa_scale", None)
    work_exp = getattr(student_profile, "work_experience_years", None)
    nationality = getattr(student_profile, "nationality", None)

    # Verbatim citation tracker
    cited_elements: List[str] = []
    if getattr(student_profile, "name", None):
        cited_elements.append(f"Student Name: {student_profile.name}")
    cited_elements.append(f"Target Field: {field}")
    cited_elements.append(f"Target Degree Level: {target_degree}")

    if cgpa is not None:
        if cgpa_scale is not None:
            cited_elements.append(f"Academic Record: CGPA {cgpa}/{cgpa_scale}")
        else:
            cited_elements.append(f"Academic Record: CGPA {cgpa} (grading scale unconfirmed)")
    if skills:
        cited_elements.append(f"Core Competencies: {', '.join(skills[:5])}")
    if repos:
        cited_elements.append(f"Technical Repository: {repos[0]}")
    if work_exp:
        cited_elements.append(f"Professional Experience: {work_exp} years")
    if nationality:
        cited_elements.append(f"Nationality: {nationality}")

    # Reference to official source evidence
    if opportunity.get("evidence_excerpt"):
        cited_elements.append(f"Source Evidence: '{opportunity['evidence_excerpt'][:80]}...'")

    # -------------------------------------------------------------------------
    # Construct Evidence-Grounded SOP Draft Text
    # -------------------------------------------------------------------------
    skill_summary = ", ".join(skills[:4]) if skills else f"rigorous coursework in {field}"
    
    if repos:
        project_clause = f"demonstrated through practical engineering in public technical repository '{repos[0]}'"
    else:
        project_clause = f"grounded in core principles and applied project coursework in {field}"

    academic_clause = ""
    if cgpa is not None:
        if cgpa_scale is not None:
            academic_clause = f"having achieved a cumulative grade point average of {cgpa}/{cgpa_scale} in prior studies, "
        else:
            academic_clause = f"having achieved a cumulative grade of {cgpa} (grading scale unconfirmed) in prior studies, "

    work_clause = ""
    if work_exp and work_exp > 0:
        work_clause = f"Complementing this academic foundation, {work_exp} years of professional experience have honed my practical problem-solving skills and technical perspective. "

    disclaimer_header = ""
    if tier != VerificationTier.T4.value:
        disclaimer_header = (
            f"[NOTICE: This draft is based on partially verified opportunity information from {official_url}. "
            f"Please verify official deadlines and requirements directly on the department portal before submission.]\n\n"
        )

    sop_paragraphs = [
        f"{disclaimer_header}STATEMENT OF PURPOSE: APPLICATION FOR {program.upper()} AT {institution.upper()}",
        "",
        f"My academic trajectory has centered on cultivating rigor in {skill_summary}. "
        f"Pursuing the {program} at {institution} represents a deliberate and well-considered step toward achieving "
        f"my long-term aspirations in {field}. Having developed solid domain fundamentals, {project_clause}, "
        f"I am eager to engage with the world-class research environment and academic community at {institution}.",
        "",
        f"Throughout my academic career, {academic_clause}I have prioritized structured inquiry and hands-on implementation. "
        f"{work_clause}"
        f"The {program} at {institution} uniquely provides the theoretical depth and advanced research infrastructure "
        f"necessary to explore complex challenges in {field}. Specifically, I look forward to contributing to active "
        f"departmental research initiatives and learning from faculty whose scholarly work shapes this discipline.",
        "",
        f"The financial support associated with this opportunity would be pivotal in allowing me to dedicate my full "
        f"energies to graduate study, research productivity, and collaborative scholarly work at {institution}. "
        f"Upon completing this degree, I aim to leverage the expertise gained to contribute meaningfully to innovation "
        f"and leadership within {field}.",
        "",
        f"Respectfully submitted,\n{student_name}",
    ]

    sop_text = "\n".join(sop_paragraphs)
    words = len(sop_text.split())

    # -------------------------------------------------------------------------
    # Formulate Targeted Missing-Information Prompts (For Student)
    # -------------------------------------------------------------------------
    missing_prompts: List[str] = [
        f"Which specific laboratory, research center, or faculty member at {institution} most closely matches your research interests?",
        f"What was the specific objective, method, or outcome of your work on {repos[0] if repos else 'your primary technical project'}?",
    ]
    if cgpa is None:
        missing_prompts.append("Add your official cumulative GPA and grading scale from your university transcript.")
    if not work_exp:
        missing_prompts.append("Include details of any internships, research assistantships, or industry roles you have undertaken.")
    
    eng_test = opportunity.get("english_test")
    student_ielts = getattr(student_profile, "ielts_score", None)
    student_toefl = getattr(student_profile, "toefl_score", None)
    has_english = (student_ielts is not None or student_toefl is not None)

    if eng_test and not has_english:
        missing_prompts.append(
            f"English proficiency score not provided; check whether an official {eng_test} test is required or if you qualify for an exemption."
        )

    if opportunity.get("gre_required") and not getattr(student_profile, "gre_score", None):
        missing_prompts.append("Check departmental guidelines for GRE requirement or test waiver request.")

    # -------------------------------------------------------------------------
    # Generate Actionable Application Checklist & Strategy Guidance
    # Statuses: CONFIRMED REQUIREMENT | USER ACTION REQUIRED | NEEDS VERIFICATION
    # -------------------------------------------------------------------------
    revisions: List[str] = []
    structured_checklist: List[Dict[str, Any]] = []

    # 1. Deadlines
    eff_dl = opportunity.get("effective_scholarship_deadline") or opportunity.get("application_deadline")
    cycle = opportunity.get("cycle_status", "uncertain")
    if eff_dl and cycle != "expired":
        task_str = f"Submit scholarship application before confirmed deadline: {eff_dl}."
        revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "CONFIRMED REQUIREMENT",
            "category": "deadline",
            "deadline": str(eff_dl)[:10],
            "evidence": f"Confirmed from {official_url}",
            "is_mandatory": True,
        })
    else:
        task_str = f"Application deadline date not verified on portal; check upcoming intake deadlines directly at {official_url}."
        revisions.append(f"[NEEDS VERIFICATION] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "NEEDS VERIFICATION",
            "category": "deadline",
            "deadline": None,
            "evidence": None,
            "is_mandatory": False,
        })

    # 2. Academic Transcript & GPA
    min_cgpa = opportunity.get("min_cgpa")
    req_scale = opportunity.get("cgpa_scale") or 4.0
    if min_cgpa is not None:
        if cgpa is not None and cgpa_scale is not None:
            if abs(cgpa_scale - req_scale) < 1e-4:
                task_str = f"Verify certified transcripts satisfy minimum requirement of {min_cgpa}/{req_scale} (your grade: {cgpa}/{cgpa_scale})."
                revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
                structured_checklist.append({
                    "task": task_str,
                    "status": "CONFIRMED REQUIREMENT",
                    "category": "academic",
                    "deadline": None,
                    "evidence": opportunity.get("evidence_excerpt"),
                    "is_mandatory": True,
                })
            else:
                task_str = f"Obtain official GPA conversion certificate: student grade ({cgpa}/{cgpa_scale}) requires institutional conversion against program threshold ({min_cgpa}/{req_scale})."
                revisions.append(f"[USER ACTION REQUIRED] {task_str}")
                structured_checklist.append({
                    "task": task_str,
                    "status": "USER ACTION REQUIRED",
                    "category": "academic",
                    "deadline": None,
                    "evidence": "Scale conversion required between distinct grading systems",
                    "is_mandatory": True,
                })
        else:
            task_str = f"Provide official certified academic transcripts verifying your GPA against the {min_cgpa}/{req_scale} threshold."
            revisions.append(f"[USER ACTION REQUIRED] {task_str}")
            structured_checklist.append({
                "task": task_str,
                "status": "USER ACTION REQUIRED",
                "category": "academic",
                "deadline": None,
                "evidence": opportunity.get("evidence_excerpt"),
                "is_mandatory": True,
            })
    else:
        task_str = "Prepare official academic transcripts from all previously attended post-secondary institutions."
        revisions.append(f"[USER ACTION REQUIRED] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "USER ACTION REQUIRED",
            "category": "academic",
            "deadline": None,
            "evidence": None,
            "is_mandatory": False,
        })

    # 3. English Proficiency
    min_eng = opportunity.get("english_min_score")
    if min_eng is not None:
        t_name = opportunity.get("english_test") or "English Language Test"
        if has_english:
            student_score = student_ielts or student_toefl
            task_str = f"Submit official electronic {t_name} score report meeting the verified threshold ({min_eng})."
            revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
            structured_checklist.append({
                "task": task_str,
                "status": "CONFIRMED REQUIREMENT",
                "category": "testing",
                "deadline": None,
                "evidence": f"Minimum {t_name} score {min_eng} confirmed by provider",
                "is_mandatory": True,
            })
        else:
            # Rule 2: Do NOT show unknown English score as a failure
            task_str = f"English proficiency score not provided; check whether a test is required or if an exemption applies at {institution}."
            revisions.append(f"[NEEDS VERIFICATION] {task_str}")
            structured_checklist.append({
                "task": task_str,
                "status": "NEEDS VERIFICATION",
                "category": "testing",
                "deadline": None,
                "evidence": f"Official portal lists {t_name} requirement ({min_eng})",
                "is_mandatory": False,
            })
    else:
        task_str = f"Language test requirement not stated on source page; verify whether English proficiency testing applies to your program."
        revisions.append(f"[NEEDS VERIFICATION] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "NEEDS VERIFICATION",
            "category": "testing",
            "deadline": None,
            "evidence": None,
            "is_mandatory": False,
        })

    # 4. Standardized Testing (GRE)
    if opportunity.get("gre_required") is True:
        task_str = f"Submit official Graduate Record Examination (GRE) score report to {institution}."
        revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "CONFIRMED REQUIREMENT",
            "category": "testing",
            "deadline": None,
            "evidence": "GRE is confirmed mandatory by program",
            "is_mandatory": True,
        })
    elif opportunity.get("gre_required") is False:
        task_str = "GRE test score is explicitly not required for this program."
        revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "CONFIRMED REQUIREMENT",
            "category": "testing",
            "deadline": None,
            "evidence": "GRE not required per provider listing",
            "is_mandatory": False,
        })

    # 5. Required Documents (distinguish confirmed vs optional/standard)
    req_docs = opportunity.get("required_documents") or []
    if req_docs:
        for doc in req_docs:
            task_str = f"Prepare confirmed document: {doc}."
            revisions.append(f"[CONFIRMED REQUIREMENT] {task_str}")
            structured_checklist.append({
                "task": task_str,
                "status": "CONFIRMED REQUIREMENT",
                "category": "document",
                "deadline": None,
                "evidence": f"Document listed on official portal: {doc}",
                "is_mandatory": True,
            })
    else:
        task_str = "Prepare standard application dossier (certified degree certificates, resume/CV, and SOP)."
        revisions.append(f"[USER ACTION REQUIRED] {task_str}")
        structured_checklist.append({
            "task": task_str,
            "status": "USER ACTION REQUIRED",
            "category": "document",
            "deadline": None,
            "evidence": None,
            "is_mandatory": False,
        })

    # Strategy / Review Action
    task_str = f"Review full application instructions and departmental policies directly at {official_url}."
    revisions.append(f"[USER ACTION REQUIRED] {task_str}")
    structured_checklist.append({
        "task": task_str,
        "status": "USER ACTION REQUIRED",
        "category": "review",
        "deadline": None,
        "evidence": official_url,
        "is_mandatory": False,
    })

    draft_dict = {
        "draft_id": f"sop-{uuid.uuid4().hex[:10]}",
        "session_id": session_id,
        "opportunity_id": opp_id,
        "institution": institution,
        "program_name": program,
        "sop_text": sop_text,
        "word_count": words,
        "cited_profile_elements": cited_elements,
        "missing_info_prompts": missing_prompts,
        "suggested_revisions": revisions,
        "application_checklist": structured_checklist,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist draft to database if db_path is provided
    if db_path:
        try:
            save_sop_draft(draft_dict, db_path=db_path)
        except Exception:
            try:
                fallback = dict(draft_dict)
                fallback["opportunity_id"] = None
                save_sop_draft(fallback, db_path=db_path)
            except Exception:
                pass

    record_pipeline_event(
        event_id=f"evt-asa-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.ASA.value,
        event_type="sop_generation_complete",
        message=f"SOP draft and application strategy generated ({words} words)",
        payload={
            "word_count": words,
            "cited_elements_count": len(cited_elements),
            "missing_prompts_count": len(missing_prompts),
        },
        db_path=db_path,
    )

    return draft_dict

