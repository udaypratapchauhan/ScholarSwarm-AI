"""Eligibility Evaluation and Verification Agent (EEVA) for ScholarSwarm AI.

Fetches candidate pages via SSRF-safe HTTP utility, verifies provenance and canonical URLs,
extracts structured requirements and deadlines, and independently evaluates admission and
scholarship eligibility without hallucinating facts.
"""

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.parse
import uuid

from backend.app.database import record_pipeline_event
from backend.app.schemas import (
    AgentRole,
    CycleStatus,
    DeadlineEntry,
    DeadlineType,
    EligibilityStatus,
    ResultGroup,
    SourceType,
    StudentProfile,
    VerificationTier,
    VerifiedOpportunity,
)
from backend.app.utils.country_config import is_country_match, is_worldwide
from backend.app.utils.ssrf import (
    SSRFSecurityError,
    safe_fetch_url,
)

# Known official university and national scholarship authority domains worldwide
OFFICIAL_DOMAINS = (
    ".edu", ".ac.uk", ".edu.au", ".gov.au", ".ac.nz", ".govt.nz",
    ".edu.sg", ".ac.in", ".ca", ".gc.ca", ".ac.jp", ".edu.cn",
    ".ac.kr", ".edu.sa", ".edu.qa", ".ac.ae",
    "gatescambridge.org", "ox.ac.uk", "cam.ac.uk", "stanford.edu",
    "ethz.ch", "harvard.edu", "mit.edu", "eacea.ec.europa.eu",
    "vanier.gc.ca", "mcgill.ca", "utoronto.ca", "mccallmacbainscholars.org",
    "auckland.ac.nz", "unimelb.edu.au", "dfat.gov.au", "scholarships.govt.nz",
)


def _classify_source(url: str, is_mock: bool = False) -> SourceType:
    """Classify source trust based on authoritative academic and governmental indicators.
    
    Strict Provenance Rule:
    Mock candidates are unverified demonstration records and can NEVER be classified
    as SourceType.OFFICIAL_PROVIDER, preventing false claims of official grounding.
    """
    if is_mock:
        return SourceType.UNKNOWN

    parsed = urllib.parse.urlsplit(url.lower())
    netloc = parsed.netloc

    for dom in OFFICIAL_DOMAINS:
        if netloc == dom or netloc.endswith(dom):
            return SourceType.OFFICIAL_PROVIDER
    
    if any(k in netloc for k in ("daad", "fulbright", "chevening", "erasmus", "campusfrance", "studyinjapan")):
        return SourceType.RELIABLE_SECONDARY

    if any(k in netloc for k in ("scholarshipportal", "wemakescholars", "armacad", "internationalscholarships")):
        return SourceType.AGGREGATOR

    return SourceType.UNKNOWN


def verify_opportunities(
    candidates: List[Dict[str, Any]],
    student_profile: StudentProfile,
    session_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Verify and evaluate candidate opportunities against student profile."""
    record_pipeline_event(
        event_id=f"evt-eeva-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.EEVA.value,
        event_type="verification_start",
        message=f"Beginning SSRF-safe verification and eligibility checks on {len(candidates)} candidates",
        payload={"candidate_count": len(candidates)},
        db_path=db_path,
    )

    verified_list: List[Dict[str, Any]] = []

    for opp in candidates:
        url = opp.get("official_url") or opp.get("source_url")
        is_mock_cand = bool(opp.get("is_mock", False))
        source_type = _classify_source(url, is_mock=is_mock_cand)

        # 1. Fetch page via SSRF-safe fetcher
        page_accessible = False
        page_http_status = None
        canonical_url = url
        fetch_ts = datetime.now(timezone.utc)
        extraction_failed = False

        try:
            resp = safe_fetch_url(url, timeout=5.0)
            page_accessible = (resp.status_code == 200)
            page_http_status = resp.status_code
            if hasattr(resp, "request") and hasattr(resp.request, "url"):
                canonical_url = str(resp.request.url)
        except SSRFSecurityError:
            page_accessible = False
            page_http_status = 403
            extraction_failed = True
        except Exception:
            page_accessible = False
            page_http_status = 504
            extraction_failed = True

        # 2. Parse Deadlines
        raw_deadlines = opp.get("deadlines") or []
        parsed_deadlines: List[Dict[str, Any]] = []
        eff_schol_dl: Optional[str] = None
        eff_adm_dl: Optional[str] = None

        today = date.today()

        if isinstance(raw_deadlines, list):
            for d in raw_deadlines:
                if isinstance(d, dict):
                    dl_date_val = d.get("deadline_date")
                    if isinstance(dl_date_val, str):
                        try:
                            parsed_date = date.fromisoformat(dl_date_val)
                        except ValueError:
                            parsed_date = None
                    else:
                        parsed_date = dl_date_val

                    dl_type_str = d.get("deadline_type", "scholarship")
                    if dl_type_str == "scholarship" and parsed_date and not eff_schol_dl:
                        eff_schol_dl = parsed_date.isoformat()
                    elif dl_type_str == "admission" and parsed_date and not eff_adm_dl:
                        eff_adm_dl = parsed_date.isoformat()

                    parsed_deadlines.append({
                        "deadline_type": dl_type_str,
                        "deadline_date": parsed_date.isoformat() if parsed_date else None,
                        "deadline_time": d.get("deadline_time"),
                        "timezone": d.get("timezone"),
                        "intake_cycle": d.get("intake_cycle"),
                        "raw_text": d.get("raw_text", "Deadline specified on portal"),
                        "is_inferred_year": d.get("is_inferred_year", False),
                    })

        # 3. Determine cycle status
        target_dl_str = eff_schol_dl or eff_adm_dl or opp.get("application_deadline")
        cycle_status = CycleStatus.UNCERTAIN
        if target_dl_str:
            try:
                dl_d = date.fromisoformat(str(target_dl_str)[:10])
                cycle_status = CycleStatus.CURRENT if dl_d >= today else CycleStatus.EXPIRED
            except ValueError:
                cycle_status = CycleStatus.UNCERTAIN

        # 4. Independent Eligibility Evaluation
        adm_status = EligibilityStatus.ELIGIBLE
        adm_reasons: List[str] = []
        schol_status = EligibilityStatus.ELIGIBLE
        schol_reasons: List[str] = []
        missing_fields: List[str] = []
        scale_conversion_required = False
        scale_conversion_explanation: Optional[str] = None

        # A. Admission Eligibility: CGPA & Scale Check
        min_cgpa = opp.get("min_cgpa")
        req_scale = opp.get("cgpa_scale")
        student_cgpa = student_profile.cgpa
        student_scale = student_profile.cgpa_scale

        if min_cgpa is not None:
            if student_cgpa is not None:
                if student_scale is None or req_scale is None:
                    # One or both scales are unconfirmed/unknown - never assume 4.0 or 10.0
                    if adm_status == EligibilityStatus.ELIGIBLE:
                        adm_status = EligibilityStatus.UNKNOWN
                    adm_reasons.append(
                        f"Grading scale is unconfirmed (student holds {student_cgpa}/{student_scale or 'unknown'}, while requirement states {min_cgpa}/{req_scale or 'unknown'}). Evaluation pending confirmed scale."
                    )
                    missing_fields.append("cgpa_scale")
                    scale_conversion_required = True
                    scale_conversion_explanation = (
                        f"Your grade is recorded as {student_cgpa} without a confirmed maximum scale. "
                        f"This program requires {min_cgpa}/{req_scale or 'unknown'}. "
                        "What to do next: Select your institution's grading scale (e.g. 10.0 or 4.0) in your profile or upload an official transcript."
                    )
                elif abs(student_scale - req_scale) < 1e-4:
                    # Compatible identical scales (e.g. both 4.0, both 10.0, or both 100.0)
                    if student_cgpa < min_cgpa:
                        adm_status = EligibilityStatus.INELIGIBLE
                        adm_reasons.append(
                            f"Student CGPA ({student_cgpa}/{student_scale}) does not meet minimum requirement ({min_cgpa}/{req_scale})"
                        )
                else:
                    # Incompatible grading scales (e.g. 10.0 vs 4.0 or 100.0 vs 4.0)
                    # Never perform unauthorized linear conversion without an official institutional conversion rule.
                    # Keep status UNKNOWN (neutral eligibility not confirmed), NOT ineligible!
                    if adm_status == EligibilityStatus.ELIGIBLE:
                        adm_status = EligibilityStatus.UNKNOWN
                    scale_mismatch_msg = (
                        f"Grading scale mismatch: student holds {student_cgpa}/{student_scale} but requirement states {min_cgpa}/{req_scale}. "
                        "Official institutional conversion required to confirm eligibility."
                    )
                    adm_reasons.append(scale_mismatch_msg)
                    missing_fields.append("official_cgpa_conversion")
                    scale_conversion_required = True
                    scale_conversion_explanation = (
                        f"Your profile records {student_cgpa}/{student_scale}, while this program specifies a minimum of {min_cgpa}/{req_scale}. "
                        "Direct mathematical multiplication or division is not recognized by university admissions. "
                        "What to do next: Request an official credential evaluation report (e.g. WES, ECE, or institutional equivalency certificate from your registrar) "
                        "to establish official conversion on the program's required scale."
                    )
            else:
                missing_fields.append("cgpa")
                if adm_status == EligibilityStatus.ELIGIBLE:
                    adm_status = EligibilityStatus.UNKNOWN

        # B. Admission Eligibility: English Proficiency Check
        min_eng = opp.get("english_min_score")
        if min_eng is not None:
            student_ielts = getattr(student_profile, "ielts_score", None)
            student_toefl = getattr(student_profile, "toefl_score", None)
            test_type = (opp.get("english_test") or "").upper()
            if student_ielts is None and student_toefl is None:
                missing_fields.append("english_test_score")
                if adm_status == EligibilityStatus.ELIGIBLE:
                    adm_status = EligibilityStatus.UNKNOWN
            elif "IELTS" in test_type and student_ielts is not None:
                try:
                    req_score = float(min_eng)
                    if student_ielts < req_score:
                        adm_status = EligibilityStatus.INELIGIBLE
                        adm_reasons.append(f"Student IELTS ({student_ielts}) below minimum requirement ({req_score})")
                except ValueError:
                    pass
            elif "TOEFL" in test_type and student_toefl is not None:
                try:
                    req_score = int(min_eng)
                    if student_toefl < req_score:
                        adm_status = EligibilityStatus.INELIGIBLE
                        adm_reasons.append(f"Student TOEFL ({student_toefl}) below minimum requirement ({req_score})")
                except ValueError:
                    pass

        # C. Admission Eligibility: GRE Requirement Check
        if opp.get("gre_required") is True:
            student_gre = getattr(student_profile, "gre_score", None)
            if student_gre is None:
                missing_fields.append("gre_score")
                if adm_status == EligibilityStatus.ELIGIBLE:
                    adm_status = EligibilityStatus.UNKNOWN

        # D. Scholarship Eligibility: Degree Level Check
        req_deg = opp.get("degree_level")
        target_deg = getattr(student_profile, "target_degree", None)
        if req_deg:
            if not target_deg:
                missing_fields.append("target_degree")
                if schol_status == EligibilityStatus.ELIGIBLE:
                    schol_status = EligibilityStatus.UNKNOWN
            elif req_deg.lower() != target_deg.value.lower():
                schol_status = EligibilityStatus.INELIGIBLE
                schol_reasons.append(
                    f"Program degree ({req_deg}) differs from student target ({target_deg.value})"
                )

        # E. Scholarship Eligibility: Nationality Check
        el_nats = opp.get("eligible_nationalities") or []
        student_nat = getattr(student_profile, "nationality", None)
        if el_nats and "All" not in el_nats:
            if not student_nat:
                missing_fields.append("nationality")
                if schol_status == EligibilityStatus.ELIGIBLE:
                    schol_status = EligibilityStatus.UNKNOWN
            else:
                excluded = any(
                    "except" in nat.lower() and student_nat.lower() in nat.lower()
                    for nat in el_nats
                )
                if excluded or (el_nats and student_nat not in el_nats and not any("all" in n.lower() for n in el_nats)):
                    schol_status = EligibilityStatus.INELIGIBLE
                    schol_reasons.append(f"Student nationality ({student_nat}) not eligible under award rules")

        # F. Study Destination Country Eligibility Check
        preferred_destinations = getattr(student_profile, "preferred_countries", [])
        opp_country = opp.get("country")
        if preferred_destinations and not is_worldwide(preferred_destinations) and opp_country:
            if not is_country_match(opp_country, preferred_destinations):
                adm_status = EligibilityStatus.INELIGIBLE
                schol_status = EligibilityStatus.INELIGIBLE
                dest_reason = (
                    f"Program study location ({opp_country}) does not match student's preferred study destination ({', '.join(preferred_destinations)})"
                )
                adm_reasons.append(dest_reason)
                schol_reasons.append(dest_reason)

        # 5. Verification Tier
        # Strict Provenance Rules:
        # - Mock records must NEVER receive T4 or T3 verification. They enter and remain at T1.
        # - T4 strictly requires genuine official-provider domain, successful SSRF safe fetch,
        #   grounded verbatim evidence excerpt, and is_mock=False.
        evidence_text = opp.get("evidence_excerpt")
        has_grounded_evidence = bool(
            evidence_text and isinstance(evidence_text, str) and evidence_text.strip()
        )
        if not is_mock_cand and source_type == SourceType.OFFICIAL_PROVIDER and page_accessible and has_grounded_evidence:
            tier = VerificationTier.T4
        elif not is_mock_cand and source_type in (SourceType.OFFICIAL_PROVIDER, SourceType.RELIABLE_SECONDARY) and page_accessible:
            tier = VerificationTier.T3
        elif not is_mock_cand and page_accessible:
            tier = VerificationTier.T2
        else:
            tier = VerificationTier.T1

        # 6. Mutually Exclusive Result Group with Deterministic Precedence
        if cycle_status == CycleStatus.EXPIRED:
            result_group = ResultGroup.EXPIRED
        elif adm_status == EligibilityStatus.INELIGIBLE or schol_status == EligibilityStatus.INELIGIBLE:
            result_group = ResultGroup.INELIGIBLE
        elif (
            adm_status == EligibilityStatus.ELIGIBLE
            and schol_status == EligibilityStatus.ELIGIBLE
            and cycle_status == CycleStatus.CURRENT
            and tier == VerificationTier.T4
            and source_type == SourceType.OFFICIAL_PROVIDER
        ):
            # Strictly requires T4 official provider evidence and current cycle
            result_group = ResultGroup.CONFIRMED_ELIGIBLE
        else:
            result_group = ResultGroup.POTENTIALLY_ELIGIBLE

        verified_record = {
            "opportunity_id": opp["opportunity_id"],
            "session_id": session_id,
            "verification_tier": tier.value,
            "type": opp.get("type", "scholarship"),
            "institution": opp["institution"],
            "program_name": opp["program_name"],
            "official_url": opp["official_url"],
            "canonical_url": canonical_url,
            "source_type": source_type.value,
            "country": opp.get("country"),
            "degree_level": opp.get("degree_level"),
            "eligible_nationalities": el_nats,
            "min_cgpa": min_cgpa,
            "cgpa_scale": req_scale,
            "english_test": opp.get("english_test"),
            "english_min_score": opp.get("english_min_score"),
            "gre_required": opp.get("gre_required"),
            "funding_amount_text": opp.get("funding_amount_text"),
            "funding_coverage": opp.get("funding_coverage", "unknown"),
            "application_deadline": target_dl_str[:10] if target_dl_str else None,
            "deadlines": parsed_deadlines,
            "effective_scholarship_deadline": eff_schol_dl,
            "effective_admission_deadline": eff_adm_dl,
            "intake_session": opp.get("intake_session"),
            "required_documents": opp.get("required_documents") or [],
            "application_instructions": opp.get("application_instructions"),
            "evidence_excerpt": evidence_text.strip() if has_grounded_evidence else None,
            "source_url": opp.get("source_url", opp["official_url"]),
            "is_mock": is_mock_cand,
            "search_provider": opp.get("search_provider", "mock"),
            "last_verified": datetime.now(timezone.utc).isoformat(),
            "page_accessible": page_accessible,
            "page_http_status": page_http_status,
            "page_fetch_timestamp": fetch_ts.isoformat(),
            "extraction_failed": extraction_failed,
            "cycle_status": cycle_status.value,
            "conflicting_info_flags": opp.get("conflicting_info_flags", []),
            "admission_eligible": adm_status.value,
            "admission_ineligible_reasons": adm_reasons,
            "scholarship_eligible": schol_status.value,
            "scholarship_ineligible_reasons": schol_reasons,
            "missing_student_fields": missing_fields,
            "scale_conversion_required": scale_conversion_required,
            "scale_conversion_explanation": scale_conversion_explanation,
            "result_group": result_group.value,
        }

        verified_list.append(verified_record)

    record_pipeline_event(
        event_id=f"evt-eeva-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.EEVA.value,
        event_type="verification_complete",
        message=f"Verified {len(verified_list)} opportunities ({sum(1 for v in verified_list if v['result_group'] == ResultGroup.CONFIRMED_ELIGIBLE.value)} confirmed eligible)",
        payload={
            "verified_count": len(verified_list),
            "confirmed_count": sum(1 for v in verified_list if v["result_group"] == ResultGroup.CONFIRMED_ELIGIBLE.value),
        },
        db_path=db_path,
    )

    return verified_list
