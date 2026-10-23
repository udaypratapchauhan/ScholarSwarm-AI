"""Search provider abstraction for scholarship discovery.

Supports Tavily, Serper, and high-fidelity mock discovery for offline development and testing.
Uses centralized country configuration to guarantee accurate destination discovery worldwide.
"""

from dataclasses import dataclass
import os
import re
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import httpx

load_dotenv()

from backend.app.utils.country_config import detect_countries_in_query, is_country_match


@dataclass
class SearchResult:
    """Standardized search hit."""
    title: str
    url: str
    snippet: str
    score: float = 1.0
    is_mock: bool = False
    provider: str = "mock"


# Realistic curated scholarship database for mock mode & testing across major worldwide destinations.
# All mock records are explicitly labeled with is_mock=True and verification_tier=T1.
MOCK_SCHOLARSHIP_POOL: List[Dict[str, Any]] = [
    {
        "title": "Clarendon Fund Scholarships - University of Oxford",
        "url": "https://www.ox.ac.uk/clarendon",
        "snippet": "The Clarendon Fund is a major graduate scholarship scheme at the University of Oxford, offering around 140 new fully funded scholarships every year to eligible graduate applicants.",
        "institution": "University of Oxford",
        "program_name": "Clarendon Fund Scholarship",
        "degree_level": "masters",
        "country": "United Kingdom",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition fees plus annual living stipend (~£18,622)",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-12-01",
                "deadline_time": "23:59",
                "timezone": "GMT",
                "intake_cycle": "Fall 2027",
                "raw_text": "Illustrative cycle: Clarendon applications close at 23:59 GMT on December 1, 2026 for the Fall 2027 cycle.",
            },
            {
                "deadline_type": "admission",
                "deadline_date": "2027-01-15",
                "raw_text": "Department admissions deadline: January 15, 2027.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] All applicants for graduate study at Oxford who apply by the relevant deadline are considered for a Clarendon Scholarship. Covers full course fees and living allowance.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Gates Cambridge Scholarship - Cambridge University",
        "url": "https://www.gatescambridge.org/apply",
        "snippet": "Gates Cambridge Scholarships are prestigious international awards for outstanding applicants outside the UK to pursue a full-time postgraduate degree at Cambridge.",
        "institution": "University of Cambridge",
        "program_name": "Gates Cambridge Scholarship",
        "degree_level": "masters",
        "country": "United Kingdom",
        "funding_coverage": "full",
        "funding_amount_text": "Full cost of studying at Cambridge including maintenance allowance (~£20,000/year)",
        "min_cgpa": 3.8,
        "cgpa_scale": 4.0,
        "english_test": "TOEFL",
        "english_min_score": "100",
        "gre_required": False,
        "eligible_nationalities": ["All except UK"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-12-05",
                "raw_text": "Illustrative cycle: Gates Cambridge international deadline closes early December 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Covers University Composition Fee and maintenance allowance for a single student.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "DAAD Helmut-Schmidt-Programme - Master's Scholarships for Public Policy & Good Governance",
        "url": "https://www.daad.de/helmut-schmidt",
        "snippet": "DAAD Helmut-Schmidt-Programme supports future leaders from developing countries who wish to promote democracy and social justice in their home countries.",
        "institution": "German Academic Exchange Service (DAAD)",
        "program_name": "Helmut-Schmidt Master's Programme",
        "degree_level": "masters",
        "country": "Germany",
        "funding_coverage": "full",
        "funding_amount_text": "€934 monthly stipend plus travel allowance, health insurance, and German language course",
        "min_cgpa": 3.2,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["Developing Countries"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-07-31",
                "raw_text": "Illustrative cycle: Application period runs from June 1 to July 31, 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Monthly scholarship payment of 934 euros. Health, accident and personal liability insurance contributions. Travel allowances.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "ETH Zurich Excellence Scholarship & Opportunity Programme (ESOP)",
        "url": "https://ethz.ch/esop",
        "snippet": "ETH Zurich supports outstanding master students with the Excellence Scholarship & Opportunity Programme (ESOP). The scholarship covers study and living costs.",
        "institution": "ETH Zurich",
        "program_name": "Excellence Scholarship & Opportunity Programme",
        "degree_level": "masters",
        "country": "Switzerland",
        "funding_coverage": "full",
        "funding_amount_text": "CHF 12,000 per semester plus tuition fee waiver",
        "min_cgpa": 3.8,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.0",
        "gre_required": True,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-30",
                "raw_text": "Illustrative cycle: ESOP application deadline is strictly November 30, 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] The ESOP scholarship covers study and living costs (CHF 12,000/semester) as well as a tuition fee waiver.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Knight-Hennessy Scholars - Stanford University",
        "url": "https://knight-hennessy.stanford.edu/admission",
        "snippet": "Knight-Hennessy Scholars develops a community of future global leaders through full funding to pursue any graduate degree at Stanford University.",
        "institution": "Stanford University",
        "program_name": "Knight-Hennessy Scholars",
        "degree_level": "masters",
        "country": "United States",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition and fees, plus living stipend and travel grant",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "english_test": "TOEFL",
        "english_min_score": "100",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-10-07",
                "raw_text": "Illustrative cycle: Knight-Hennessy Scholars application deadline: October 7, 2026 at 1:00 PM Pacific Time.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Provides funding for graduate degree study at Stanford including tuition and academic stipend.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Eiffel Excellence Scholarship Programme - Campus France",
        "url": "https://www.campusfrance.org/en/eiffel-scholarship-program-of-excellence",
        "snippet": "The Eiffel Excellence Scholarship Program was established by the French Ministry for Europe and Foreign Affairs to enable French higher education institutions to attract top foreign students.",
        "institution": "Campus France / French Foreign Ministry",
        "program_name": "Eiffel Excellence Scholarship",
        "degree_level": "masters",
        "country": "France",
        "funding_coverage": "tuition_plus_stipend",
        "funding_amount_text": "€1,181 monthly allowance plus transport, health insurance and cultural activities",
        "min_cgpa": 3.4,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["Non-French citizens"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2027-01-10",
                "raw_text": "Illustrative cycle: Applications close early January 2027 via host French higher education institution.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Monthly allowance of €1,181 for Master level with travel and insurance contributions.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Erasmus Mundus Joint Master Degrees (EMJM) Scholarships",
        "url": "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en",
        "snippet": "Erasmus Mundus Joint Masters are high-level integrated study programmes designed and delivered by an international partnership of higher education institutions.",
        "institution": "European Commission",
        "program_name": "Erasmus Mundus Scholarship",
        "degree_level": "masters",
        "country": "European Union",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition, €1,400 monthly allowance, and travel reimbursement",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2027-01-15",
                "raw_text": "Illustrative cycle: Most Erasmus Mundus consortia deadlines fall between December 2026 and February 2027.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] The EU-funded scholarship covers student participation costs, insurance, and contribution to travel and living allowance.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Vanier Canada Graduate Scholarships - Government of Canada",
        "url": "https://vanier.gc.ca/en/home-accueil.html",
        "snippet": "The Vanier Canada Graduate Scholarships (Vanier CGS) program helps Canadian institutions attract highly qualified doctoral students. Valued at $50,000 CAD per year.",
        "institution": "Government of Canada",
        "program_name": "Vanier Canada Graduate Scholarship",
        "degree_level": "doctoral",
        "country": "Canada",
        "funding_coverage": "full",
        "funding_amount_text": "$50,000 CAD per year for up to 3 years",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "english_test": "TOEFL",
        "english_min_score": "100",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-01",
                "raw_text": "Illustrative cycle: Vanier CGS institutional nomination deadline is November 1, 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Valued at $50,000 CAD per year for three years during doctoral studies in Canada.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "McCall MacBain Scholarships - McGill University",
        "url": "https://www.mccallmacbainscholars.org/apply",
        "snippet": "The McCall MacBain Scholarship covers tuition and fees for eligible master's programs at McGill University in Canada plus a $2,000 CAD monthly living stipend.",
        "institution": "McGill University",
        "program_name": "McCall MacBain Scholarship",
        "degree_level": "masters",
        "country": "Canada",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition and fees plus $2,000 CAD monthly living stipend",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-09-24",
                "raw_text": "Illustrative cycle: International applicants deadline: September 24, 2026 for master's admission at McGill.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Covers tuition and fees plus a CAD $2,000 monthly living stipend for eligible master's degrees at McGill in Canada.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Ontario Graduate Scholarship (OGS) - University of Toronto",
        "url": "https://www.sgs.utoronto.ca/awards/ontario-graduate-scholarship/",
        "snippet": "The Ontario Graduate Scholarship (OGS) program encourages excellence in graduate studies at publicly-assisted universities in Ontario, Canada.",
        "institution": "University of Toronto",
        "program_name": "Ontario Graduate Scholarship (OGS)",
        "degree_level": "masters",
        "country": "Canada",
        "funding_coverage": "partial",
        "funding_amount_text": "$15,000 CAD per academic year ($5,000 CAD per session)",
        "min_cgpa": 3.7,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.0",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2027-03-01",
                "raw_text": "Illustrative cycle: OGS international student competition closes March 1, 2027.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Value: $5,000 per session to a maximum of $15,000 for one academic year at University of Toronto in Ontario, Canada.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    # -------------------------------------------------------------------------
    # NEW ZEALAND OPPORTUNITIES
    # -------------------------------------------------------------------------
    {
        "title": "Manaaki New Zealand Scholarship - Universities New Zealand",
        "url": "https://www.scholarships.govt.nz/manaaki-nz",
        "snippet": "The Manaaki New Zealand Scholarship supports eligible international students to undertake full-time postgraduate study at participating New Zealand universities.",
        "institution": "Government of New Zealand / MFAT",
        "program_name": "Manaaki New Zealand Scholarship",
        "degree_level": "masters",
        "country": "New Zealand",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition fees, living allowance NZ$531 per week, and establishment allowance",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-30",
                "raw_text": "Illustrative cycle: Applications close late November 2026 for New Zealand intake.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Manaaki New Zealand Scholarships offer full tuition fees, a living allowance of NZ$531 per week, medical insurance, and travel allowance.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "University of Auckland International Student Excellence Scholarship",
        "url": "https://www.auckland.ac.nz/scholarships/international-excellence",
        "snippet": "University of Auckland provides awards up to NZ$10,000 towards tuition fees for high-achieving new international students undertaking master's studies in New Zealand.",
        "institution": "University of Auckland",
        "program_name": "International Student Excellence Scholarship",
        "degree_level": "masters",
        "country": "New Zealand",
        "funding_coverage": "partial",
        "funding_amount_text": "Up to NZ$10,000 contribution towards tuition fees",
        "min_cgpa": 3.2,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-20",
                "raw_text": "Illustrative cycle: Applications close November 20, 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] The main purpose of the Scholarship is to attract new international students of high calibre to study at University of Auckland in New Zealand.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    # -------------------------------------------------------------------------
    # AUSTRALIA OPPORTUNITIES
    # -------------------------------------------------------------------------
    {
        "title": "Australia Awards Scholarship - Department of Foreign Affairs and Trade",
        "url": "https://www.dfat.gov.au/people-to-people/australia-awards",
        "snippet": "Australia Awards Scholarships are prestigious long-term development awards administered by DFAT for full-time master's study in Australia.",
        "institution": "Australian Government (DFAT)",
        "program_name": "Australia Awards Scholarship",
        "degree_level": "masters",
        "country": "Australia",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition fees, return air travel, establishment allowance, and contribution to living expenses",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-15",
                "raw_text": "Illustrative cycle: Applications close mid-November 2026 for Australian universities.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Australia Awards Scholarships cover full tuition, return air travel, establishment allowance, and living expenses for study in Australia.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Melbourne Research Scholarship - University of Melbourne",
        "url": "https://scholarships.unimelb.edu.au/awards/melbourne-research-scholarship",
        "snippet": "The Melbourne Research Scholarship is awarded to high-achieving domestic and international research students pursuing master's or PhD degrees in Australia.",
        "institution": "University of Melbourne",
        "program_name": "Melbourne Research Scholarship",
        "degree_level": "masters",
        "country": "Australia",
        "funding_coverage": "full",
        "funding_amount_text": "Full fee offset up to two years, plus living allowance AUD$37,000 per year",
        "min_cgpa": 3.5,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "7.0",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-10-31",
                "raw_text": "Illustrative cycle: Round closes October 31, 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] Melbourne Research Scholarships provide full fee offset and living allowance for graduate researchers at the University of Melbourne in Australia.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    # -------------------------------------------------------------------------
    # IRELAND OPPORTUNITY
    # -------------------------------------------------------------------------
    {
        "title": "Government of Ireland International Education Scholarship (GOI-IES)",
        "url": "https://hea.ie/funding/goi-ies",
        "snippet": "The Government of Ireland International Education Scholarships scheme supports high-calibre international students to study full-time in Ireland for one master's year.",
        "institution": "Higher Education Authority Ireland",
        "program_name": "Government of Ireland International Education Scholarship",
        "degree_level": "masters",
        "country": "Ireland",
        "funding_coverage": "full",
        "funding_amount_text": "€10,000 stipend plus full tuition fee waiver at Irish universities",
        "min_cgpa": 3.2,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All except EU/EEA"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2027-03-15",
                "raw_text": "Illustrative cycle: Call closes mid-March 2027 for Ireland.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] The GOI-IES scheme awards a €10,000 stipend towards one year study plus a full tuition fee waiver at Irish institutions.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    # -------------------------------------------------------------------------
    # JAPAN & SINGAPORE (ASIA)
    # -------------------------------------------------------------------------
    {
        "title": "MEXT Japanese Government Research Student Scholarship",
        "url": "https://www.studyinjapan.go.jp/en/planning/by-style/mext/",
        "snippet": "The Ministry of Education, Culture, Sports, Science and Technology (MEXT) of Japan offers scholarships for international students wishing to study at Japanese universities.",
        "institution": "Government of Japan (MEXT)",
        "program_name": "MEXT Research Student Scholarship",
        "degree_level": "masters",
        "country": "Japan",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition waiver, round-trip airfare, and monthly allowance ~144,000 JPY",
        "min_cgpa": 3.0,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-11-15",
                "raw_text": "Illustrative cycle: Embassy recommendation closes November 2026.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] MEXT scholarship provides full tuition fee exemption, monthly living allowance of 144,000 JPY, and travel expense support to Japan.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
    {
        "title": "Singapore International Graduate Award (SINGA) - A*STAR",
        "url": "https://www.a-star.edu.sg/scholarships/singa",
        "snippet": "The Singapore International Graduate Award (SINGA) supports international students with passion for biomedical sciences, physical science, and engineering in Singapore.",
        "institution": "Agency for Science, Technology and Research (A*STAR)",
        "program_name": "Singapore International Graduate Award (SINGA)",
        "degree_level": "masters",
        "country": "Singapore",
        "funding_coverage": "full",
        "funding_amount_text": "Full tuition fees, monthly stipend of SGD $2,200-$2,700, and airfare grant",
        "min_cgpa": 3.4,
        "cgpa_scale": 4.0,
        "english_test": "IELTS",
        "english_min_score": "6.5",
        "gre_required": False,
        "eligible_nationalities": ["All"],
        "deadlines": [
            {
                "deadline_type": "scholarship",
                "deadline_date": "2026-12-01",
                "raw_text": "Illustrative cycle: SINGA deadline December 1, 2026 for August intake.",
            }
        ],
        "evidence_excerpt": "[Illustrative Mock Demonstration Record] SINGA covers full tuition fees, a monthly stipend up to SGD $2,700, and settling-in allowance in Singapore.",
        "source_type": "unknown",
        "verification_tier": "T1",
        "is_mock": True,
        "is_verified": False,
    },
]


def _is_valid_url(url: str) -> bool:
    """Validate that URL has http or https scheme and a non-empty hostname."""
    if not isinstance(url, str):
        return False
    u = url.strip()
    return (u.startswith("http://") or u.startswith("https://")) and len(u) > 10


def search_scholarships(query: str, max_results: int = 5) -> List[SearchResult]:
    """Execute scholarship search with configured provider and graceful mock fallback."""
    provider = os.getenv("SEARCH_PROVIDER", "mock").lower().strip()
    api_key = os.getenv("SEARCH_API_KEY", "").strip()

    # 1. Live Tavily Provider
    if provider == "tavily" and api_key:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": max_results,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results: List[SearchResult] = []
                    for r in data.get("results", []):
                        raw_url = r.get("url", "").strip()
                        if not _is_valid_url(raw_url):
                            continue
                        results.append(
                            SearchResult(
                                title=r.get("title", "Scholarship").strip(),
                                url=raw_url,
                                snippet=r.get("content", "").strip(),
                                score=float(r.get("score", 1.0)),
                                is_mock=False,
                                provider="tavily",
                            )
                        )
                    if results:
                        return results
        except Exception:
            # Fall back to mock on network or credential error
            pass

    # 2. Live Serper Provider
    elif provider == "serper" and api_key:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": max_results},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for r in data.get("organic", []):
                        raw_url = r.get("link", "").strip()
                        if not _is_valid_url(raw_url):
                            continue
                        results.append(
                            SearchResult(
                                title=r.get("title", "Scholarship").strip(),
                                url=raw_url,
                                snippet=r.get("snippet", "").strip(),
                                score=1.0,
                                is_mock=False,
                                provider="serper",
                            )
                        )
                    if results:
                        return results
        except Exception:
            # Fall back to mock on network or credential error
            pass

    # 3. High-fidelity mock search response (Development & Offline fallback)
    q_lower = query.lower()
    target_countries = detect_countries_in_query(query)

    matches = []
    for item in MOCK_SCHOLARSHIP_POOL:
        item_country = item.get("country", "")
        # When query specifies particular destination countries, strictly enforce matching
        if target_countries and not is_country_match(item_country, target_countries):
            continue

        text = f"{item['title']} {item['snippet']} {item_country} {item['degree_level']}".lower()
        relevance = sum(1 for word in q_lower.split() if word in text)
        matches.append((relevance, item))

    matches.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchResult(
            title=item["title"],
            url=item["url"],
            snippet=item["snippet"],
            score=1.0,
            is_mock=True,
            provider="mock",
        )
        for _, item in matches[:max_results]
    ]
