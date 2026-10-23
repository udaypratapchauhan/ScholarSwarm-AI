"""Opportunity Research Agent (ORA) for ScholarSwarm AI.

Discovers global scholarship opportunities grounded in the student's profile,
normalizes target queries, deduplicates candidate sources, and emits traceable pipeline events.
Integrates centralized country configuration to guarantee accurate worldwide discovery.
"""

from typing import Any, Dict, List, Optional
import urllib.parse
import uuid

from backend.app.database import record_pipeline_event
from backend.app.schemas import AgentRole, StudentProfile
from backend.app.utils.country_config import (
    detect_countries_in_query,
    is_country_match,
    is_worldwide,
    normalize_country,
)
from backend.app.utils.search import MOCK_SCHOLARSHIP_POOL, search_scholarships


def _normalize_url(url: str) -> str:
    """Normalize URL by stripping trailing slash, query parameters, and fragments for deduplication."""
    parsed = urllib.parse.urlsplit(url.strip())
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}".lower()


def discover_opportunities(
    student_profile: StudentProfile,
    session_id: str,
    max_candidates: int = 10,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Discover candidate scholarship opportunities tailored to student profile.
    
    1. Formulates search queries using degree level, target countries, and academic interests.
    2. Searches via configured search provider (with mock fallback).
    3. Merges and deduplicates candidate opportunities with strict country relevance.
    4. Emits ORA pipeline progress events.
    """
    target_countries = getattr(student_profile, "preferred_countries", [])
    skills = [s.skill for s in getattr(student_profile, "skills_extracted", [])]
    field = getattr(student_profile, "field_of_study", "Computer Science")

    record_pipeline_event(
        event_id=f"evt-ora-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.ORA.value,
        event_type="query_generation",
        message="Formulating targeted scholarship research queries from student profile",
        payload={
            "degree_level": student_profile.target_degree.value if student_profile.target_degree else "masters",
            "target_countries": target_countries,
            "field_of_study": field,
        },
        db_path=db_path,
    )

    queries: List[str] = []
    degree = student_profile.target_degree.value if student_profile.target_degree else "masters"
    interest_str = " ".join(skills[:3]) if skills else field

    if target_countries and not is_worldwide(target_countries):
        for c in target_countries:
            queries.append(f"fully funded {degree} scholarships in {c} {interest_str}")
            queries.append(f"government and university {degree} scholarships in {c}")
        if student_profile.nationality:
            queries.append(f"scholarships for {student_profile.nationality} students in {target_countries[0]} {degree}")
    else:
        # Worldwide / unrestricted search: search diverse international and global awards
        queries.append(f"fully funded {degree} scholarships international students {interest_str}")
        queries.append(f"prestigious global international {degree} scholarships worldwide")
        if student_profile.nationality:
            queries.append(f"scholarships for {student_profile.nationality} students international {degree}")

    candidates: List[Dict[str, Any]] = []
    seen_urls = set()

    for q in queries:
        hits = search_scholarships(q, max_results=5)
        for hit in hits:
            if not (hit.url.startswith("http://") or hit.url.startswith("https://")):
                continue

            norm_url = _normalize_url(hit.url)
            if norm_url in seen_urls:
                continue

            # Match hit with known metadata pool for seed attributes if available
            matched_pool = None
            for item in MOCK_SCHOLARSHIP_POOL:
                if _normalize_url(item["url"]) == norm_url or item["program_name"].lower() in hit.title.lower():
                    matched_pool = item
                    break

            if matched_pool:
                # If target countries specified, enforce country match
                if not is_country_match(matched_pool.get("country"), target_countries):
                    continue

                seen_urls.add(norm_url)
                cand = dict(matched_pool)
                cand["opportunity_id"] = f"opp-{uuid.uuid4().hex[:10]}"
                cand["session_id"] = session_id
                cand["official_url"] = matched_pool["url"]
                cand["source_url"] = matched_pool["url"]
                # Discovery must not claim pre-verification; EEVA will verify
                cand["verification_tier"] = "T1"
                cand["source_type"] = "unknown"
                cand["is_mock"] = getattr(hit, "is_mock", True)
                cand["search_provider"] = getattr(hit, "provider", "mock")
            else:
                detected_c = detect_countries_in_query(f"{hit.title} {hit.snippet}")
                hit_country = detected_c[0] if detected_c else (target_countries[0] if (target_countries and not is_worldwide(target_countries)) else None)

                if not is_country_match(hit_country, target_countries):
                    continue

                seen_urls.add(norm_url)
                cand = {
                    "opportunity_id": f"opp-{uuid.uuid4().hex[:10]}",
                    "session_id": session_id,
                    "institution": hit.title.split("-")[0].strip() if "-" in hit.title else "Academic Institution",
                    "program_name": hit.title,
                    "official_url": hit.url,
                    "source_url": hit.url,
                    "degree_level": degree,
                    "country": hit_country,
                    "funding_coverage": "unknown",
                    "evidence_excerpt": hit.snippet,
                    "source_type": "unknown",
                    "verification_tier": "T1",
                    "is_mock": getattr(hit, "is_mock", False),
                    "search_provider": getattr(hit, "provider", "tavily"),
                }
            candidates.append(cand)
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    # If search returned fewer than 3, backfill from mock pool STRICTLY matching target countries if specified
    if len(candidates) < 3:
        for item in MOCK_SCHOLARSHIP_POOL:
            if not is_country_match(item.get("country"), target_countries):
                continue
            norm_url = _normalize_url(item["url"])
            if norm_url not in seen_urls:
                seen_urls.add(norm_url)
                cand = dict(item)
                cand["opportunity_id"] = f"opp-{uuid.uuid4().hex[:10]}"
                cand["session_id"] = session_id
                cand["official_url"] = item["url"]
                cand["source_url"] = item["url"]
                cand["verification_tier"] = "T1"
                cand["source_type"] = "unknown"
                cand["is_mock"] = True
                cand["search_provider"] = "mock"
                candidates.append(cand)
                if len(candidates) >= max_candidates:
                    break

    record_pipeline_event(
        event_id=f"evt-ora-{uuid.uuid4().hex[:8]}",
        session_id=session_id,
        agent=AgentRole.ORA.value,
        event_type="candidate_discovery",
        message=f"Discovered {len(candidates)} distinct scholarship opportunities",
        payload={"candidate_count": len(candidates)},
        db_path=db_path,
    )

    return candidates
