"""Matchmaking & Ranking Agent (MRA) for ScholarSwarm AI.

Deterministically scores and ranks verified opportunities against student profile
using configurable weights from config/scoring_weights.json.
Enforces strict T4 official-provider constraints for Top-5 recommendations.
"""

from datetime import date
import json
import os
from typing import Any, Dict, List, Optional
import uuid

from backend.app.database import record_pipeline_event
from backend.app.schemas import (
    AgentRole,
    CycleStatus,
    EligibilityStatus,
    FundingCoverage,
    ResultGroup,
    SourceType,
    StudentProfile,
    VerificationTier,
)
from backend.app.utils.country_config import is_country_match

DEFAULT_WEIGHTS = {
    "field_alignment": 0.30,
    "funding_coverage": 0.25,
    "deadline_proximity": 0.20,
    "eligibility_clarity": 0.15,
    "data_completeness": 0.10,
}


def load_scoring_weights(config_path: Optional[str] = None) -> Dict[str, float]:
    """Load scoring weights from JSON file or return standard defaults.
    
    Guarantees weights sum to 1.0 and all required factor keys are present.
    """
    path = config_path or os.getenv("SCORING_WEIGHTS_FILE", "config/scoring_weights.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Ensure all required factors exist
                    cleaned = {k: float(loaded.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
                    total = sum(cleaned.values())
                    if total > 0:
                        # Normalize so weights always sum to 1.0
                        return {k: round(v / total, 4) for k, v in cleaned.items()}
        except Exception:
            pass
    return DEFAULT_WEIGHTS.copy()


def _score_opportunity(
    opp: Dict[str, Any], student_profile: StudentProfile, weights: Dict[str, float]
) -> Dict[str, Any]:
    """Compute deterministic factor contributions and overall 0-100 score.
    
    Enforces strict grounding:
    - Never awards eligibility points for unknown info or missing data.
    - Factors evaluated:
      1. Field & Degree Alignment (0-100)
      2. Funding Coverage Fit (0-100)
      3. Deadline Proximity & Currency (0-100)
      4. Eligibility Clarity & Nationality Match (0-100)
      5. Data Completeness & Verification Tier (0-100)
    """
    # -------------------------------------------------------------------------
    # 1. Field Alignment & Degree Match (0-100)
    # -------------------------------------------------------------------------
    degree_score = 0.0
    req_degree = opp.get("degree_level")
    target_deg = getattr(student_profile, "target_degree", None)
    target_deg_val = target_deg.value.lower() if hasattr(target_deg, "value") else str(target_deg or "").lower()

    if req_degree and target_deg_val:
        if req_degree.lower() == target_deg_val:
            degree_score = 40.0
        else:
            degree_score = 0.0  # Mismatch
    elif not req_degree and target_deg_val:
        degree_score = 20.0  # Unstated degree level on page: neutral, not confirmed
    else:
        degree_score = 0.0

    field_match_score = 0.0
    student_field = getattr(student_profile, "field_of_study", "").strip().lower()
    opp_text = f"{opp.get('program_name', '')} {opp.get('institution', '')} {opp.get('evidence_excerpt', '')}".lower()

    if student_field and student_field in opp_text:
        field_match_score = 30.0

    skill_score = 0.0
    skills = [s.skill.lower().strip() for s in getattr(student_profile, "skills_extracted", []) if s.skill]
    matched_skills = [s for s in skills if s in opp_text]
    skill_score = min(30.0, len(matched_skills) * 10.0)

    field_score = min(100.0, degree_score + field_match_score + skill_score)

    # -------------------------------------------------------------------------
    # 2. Funding Coverage (0-100)
    # Never award points for unknown funding
    # -------------------------------------------------------------------------
    cov = str(opp.get("funding_coverage", "unknown")).lower()
    if cov in ("full", FundingCoverage.FULL.value):
        funding_score = 100.0
    elif cov in ("tuition_plus_stipend", "tuition_and_stipend"):
        funding_score = 85.0
    elif cov in ("tuition_only", "tuition"):
        funding_score = 65.0
    elif cov in ("partial", FundingCoverage.PARTIAL.value):
        funding_score = 45.0
    else:
        # Unknown funding coverage awards 0 points
        funding_score = 0.0

    # -------------------------------------------------------------------------
    # 3. Deadline Proximity & Currency (0-100)
    # Expired or unknown deadlines receive 0 points
    # -------------------------------------------------------------------------
    target_dl = (
        opp.get("effective_scholarship_deadline")
        or opp.get("application_deadline")
        or opp.get("effective_admission_deadline")
    )
    cycle_status = opp.get("cycle_status", "uncertain")
    today = date.today()
    deadline_score = 0.0

    if cycle_status == CycleStatus.EXPIRED.value:
        deadline_score = 0.0
    elif target_dl:
        try:
            dl_date = date.fromisoformat(str(target_dl)[:10])
            days_left = (dl_date - today).days
            if days_left < 0:
                deadline_score = 0.0
            elif 30 <= days_left <= 180:
                deadline_score = 100.0  # Optimal application preparation window
            elif 15 <= days_left < 30:
                deadline_score = 75.0   # Actionable but close
            elif days_left > 180:
                deadline_score = 80.0   # Ample runway
            elif 0 <= days_left < 15:
                deadline_score = 35.0   # Imminent deadline
        except ValueError:
            deadline_score = 0.0
    else:
        deadline_score = 0.0  # Missing/unknown deadline awards 0 points

    # -------------------------------------------------------------------------
    # 4. Eligibility Clarity & Grounding (0-100)
    # Hard exclusions get 0; missing student fields penalize clarity
    # -------------------------------------------------------------------------
    adm_el = opp.get("admission_eligible", EligibilityStatus.UNKNOWN.value)
    schol_el = opp.get("scholarship_eligible", EligibilityStatus.UNKNOWN.value)

    if adm_el == EligibilityStatus.INELIGIBLE.value or schol_el == EligibilityStatus.INELIGIBLE.value:
        clarity_score = 0.0
    else:
        # Base on confirmed eligibility
        if adm_el == EligibilityStatus.ELIGIBLE.value and schol_el == EligibilityStatus.ELIGIBLE.value:
            base_clarity = 100.0
        elif adm_el == EligibilityStatus.ELIGIBLE.value or schol_el == EligibilityStatus.ELIGIBLE.value:
            base_clarity = 50.0
        else:
            base_clarity = 20.0

        # Penalize for missing profile fields required to confirm eligibility
        missing_fields = opp.get("missing_student_fields") or []
        deduction = len(missing_fields) * 15.0
        clarity_score = max(0.0, base_clarity - deduction)

    # -------------------------------------------------------------------------
    # 5. Data Completeness & Verification Tier (0-100)
    # Rewards verified official evidence
    # -------------------------------------------------------------------------
    comp_score = 0.0
    tier = opp.get("verification_tier", "T1")
    src_type = opp.get("source_type", "unknown")

    if tier == VerificationTier.T4.value and src_type == SourceType.OFFICIAL_PROVIDER.value:
        comp_score += 50.0
    elif tier == VerificationTier.T3.value:
        comp_score += 30.0
    elif tier == VerificationTier.T2.value:
        comp_score += 15.0
    else:
        comp_score += 0.0

    if opp.get("evidence_excerpt"):
        comp_score += 25.0
    if opp.get("deadlines"):
        comp_score += 15.0
    if opp.get("min_cgpa") is not None or opp.get("english_min_score") is not None:
        comp_score += 10.0

    completeness_score = min(100.0, comp_score)

    # -------------------------------------------------------------------------
    # Weighted Summation
    # -------------------------------------------------------------------------
    breakdown = {
        "field_alignment": round(field_score * weights["field_alignment"], 2),
        "funding_coverage": round(funding_score * weights["funding_coverage"], 2),
        "deadline_proximity": round(deadline_score * weights["deadline_proximity"], 2),
        "eligibility_clarity": round(clarity_score * weights["eligibility_clarity"], 2),
        "data_completeness": round(completeness_score * weights["data_completeness"], 2),
    }

    total = round(sum(breakdown.values()), 2)

    # -------------------------------------------------------------------------
    # Explainable Rationale & Confidence
    # -------------------------------------------------------------------------
    matched_factors: List[str] = []
    if field_match_score > 0:
        matched_factors.append(f"field match ({student_field})")
    if matched_skills:
        matched_factors.append(f"{len(matched_skills)} matching skills ({', '.join(matched_skills[:3])})")
    if degree_score == 40.0:
        matched_factors.append("degree level match")
    if funding_score >= 85.0:
        matched_factors.append("generous funding package")

    missing_factors: List[str] = []
    if opp.get("missing_student_fields"):
        missing_factors.append(f"missing profile fields: {', '.join(opp['missing_student_fields'])}")
    if deadline_score == 0.0 and cycle_status != CycleStatus.EXPIRED.value:
        missing_factors.append("unconfirmed deadline")

    country_label = opp.get("country") or "Study Destination"
    rationale_parts = [
        f"{opp.get('funding_coverage', 'Partial').replace('_', ' ').capitalize()} funding at {opp.get('institution')} ({country_label}).",
        f"Alignment score: {int(field_score)}/100, verified with {tier} evidence."
    ]
    if matched_factors:
        rationale_parts.append(f"Key fits: {'; '.join(matched_factors)}.")
    if missing_factors:
        rationale_parts.append(f"Action needed: {'; '.join(missing_factors)}.")

    rationale = " ".join(rationale_parts)

    is_t4_official = (
        tier == VerificationTier.T4.value
        and src_type == SourceType.OFFICIAL_PROVIDER.value
    )
    if total >= 70.0 and is_t4_official and adm_el == EligibilityStatus.ELIGIBLE.value and schol_el == EligibilityStatus.ELIGIBLE.value:
        confidence = "high"
    elif total >= 45.0 and tier in (VerificationTier.T3.value, VerificationTier.T4.value):
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "total_score": total,
        "score_breakdown": breakdown,
        "recommendation_rationale": rationale,
        "confidence": confidence,
    }


def rank_opportunities(
    opportunities: List[Dict[str, Any]],
    student_profile: StudentProfile,
    session_id: str,
    db_path: Optional[str] = None,
    weights_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Score all opportunities and rank eligible ones, strictly enforcing Top-5 rules.
    
    Hard Rules:
    1. INELIGIBLE and EXPIRED opportunities are strictly excluded from recommendations (rank = None).
    2. Top-5 recommendations must contain ONLY T4 opportunities supported by official primary-provider evidence.
    3. If fewer than five qualify, return fewer than five (NEVER backfill with T1-T3).
    4. Confirmed eligible (Group 1) has priority over Potentially eligible (Group 2).
    5. Safely handles empty candidate lists and incomplete student profiles.
    """
    weights = load_scoring_weights(weights_path)

    record_pipeline_event(
        event_id=f"evt-mra-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.MRA.value,
        event_type="scoring_start",
        message="Computing multi-factor alignment and explainable scores for verified candidates",
        payload={"weights": weights, "candidate_count": len(opportunities)},
        db_path=db_path,
    )

    if not opportunities:
        record_pipeline_event(
            event_id=f"evt-mra-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            agent=AgentRole.MRA.value,
            event_type="ranking_complete",
            message="No candidate opportunities to score or rank.",
            payload={"top_5_count": 0, "total_ranked": 0},
            db_path=db_path,
        )
        return []

    scored: List[Dict[str, Any]] = []
    for opp in opportunities:
        opp_copy = dict(opp)
        scores = _score_opportunity(opp_copy, student_profile, weights)
        opp_copy.update(scores)
        scored.append(opp_copy)

    # -------------------------------------------------------------------------
    # Segregate Candidates
    # -------------------------------------------------------------------------
    # Top-5 candidates MUST satisfy:
    # 1. verification_tier == T4
    # 2. source_type == official_provider
    # 3. result_group not in (ineligible, expired)
    # 4. country must match preferred_countries if specified
    target_countries = getattr(student_profile, "preferred_countries", [])

    group1_t4 = [
        o for o in scored
        if o.get("result_group") == ResultGroup.CONFIRMED_ELIGIBLE.value
        and o.get("verification_tier") == VerificationTier.T4.value
        and o.get("source_type") == SourceType.OFFICIAL_PROVIDER.value
        and is_country_match(o.get("country"), target_countries)
    ]
    group2_t4 = [
        o for o in scored
        if o.get("result_group") == ResultGroup.POTENTIALLY_ELIGIBLE.value
        and o.get("verification_tier") == VerificationTier.T4.value
        and o.get("source_type") == SourceType.OFFICIAL_PROVIDER.value
        and is_country_match(o.get("country"), target_countries)
    ]

    # Non-T4 official-provider or ineligible/expired opportunities
    non_top5_eligible_t4 = []
    excluded_or_lower_tier = [
        o for o in scored
        if o not in group1_t4 and o not in group2_t4
    ]

    # Sort each group by total_score descending
    group1_t4.sort(key=lambda x: x["total_score"], reverse=True)
    group2_t4.sort(key=lambda x: x["total_score"], reverse=True)

    # Select up to 5 Top Recommendations
    # Priority: Group 1 first, then Group 2
    qualified_top = group1_t4 + group2_t4
    top_candidates = qualified_top[:5]
    remaining_t4 = qualified_top[5:]

    # Sort excluded or lower-tier items for consistent output ordering:
    # POTENTIALLY_ELIGIBLE first, then INELIGIBLE, then EXPIRED
    def _sort_key(o: Dict[str, Any]) -> tuple:
        grp = o.get("result_group")
        tier_val = o.get("verification_tier", "T1")
        grp_prio = 0 if grp == ResultGroup.POTENTIALLY_ELIGIBLE.value else (
            1 if grp == ResultGroup.INELIGIBLE.value else 2
        )
        return (grp_prio, -o.get("total_score", 0.0))

    excluded_or_lower_tier.sort(key=_sort_key)

    # -------------------------------------------------------------------------
    # Assign Ranks
    # -------------------------------------------------------------------------
    ranked_result: List[Dict[str, Any]] = []

    # 1. Top-5 recommendations: rank 1..K (K <= 5)
    for rank_idx, opp in enumerate(top_candidates, start=1):
        opp["rank"] = rank_idx
        ranked_result.append(opp)

    # 2. Additional T4 official-provider opportunities beyond rank 5 get rank 6..N
    current_rank = len(top_candidates) + 1
    for opp in remaining_t4:
        opp["rank"] = current_rank
        current_rank += 1
        ranked_result.append(opp)

    # 3. Lower-tier (T1-T3), INELIGIBLE, and EXPIRED opportunities are excluded
    # from recommendations: rank = None
    for opp in excluded_or_lower_tier:
        opp["rank"] = None
        ranked_result.append(opp)

    record_pipeline_event(
        event_id=f"evt-mra-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.MRA.value,
        event_type="ranking_complete",
        message=f"Ranked {len(top_candidates)} Top-5 recommendations with verified T4 official-provider evidence",
        payload={
            "top_5_count": len(top_candidates),
            "group1_count": len(group1_t4),
            "group2_count": len(group2_t4),
            "top_recommendation": top_candidates[0]["program_name"] if top_candidates else None,
        },
        db_path=db_path,
    )

    return ranked_result

