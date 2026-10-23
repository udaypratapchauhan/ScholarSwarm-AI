"""Centralized, maintainable country and destination configuration for ScholarSwarm AI.

Provides canonical country resolution, aliases, regional groupings, and consistent
country-matching logic across ORA discovery, EEVA verification, MRA ranking, and UI filtering.
"""

import re
from typing import Dict, List, Optional, Set

WORLDWIDE_KEYWORDS: Set[str] = {
    "worldwide",
    "all",
    "any",
    "global",
    "all countries",
    "world",
    "international",
    "everywhere",
    "*",
}

# Canonical Country -> Set of lowercase aliases and keywords
COUNTRY_CATALOG: Dict[str, Set[str]] = {
    "Canada": {"canada", "ca", "canadian"},
    "United States": {"united states", "usa", "us", "u.s.", "u.s.a.", "united states of america", "america", "american"},
    "United Kingdom": {"united kingdom", "uk", "u.k.", "britain", "great britain", "england", "scotland", "wales", "british"},
    "Ireland": {"ireland", "ie", "republic of ireland", "irish"},
    "Australia": {"australia", "au", "aus", "australian"},
    "New Zealand": {"new zealand", "nz", "n.z.", "aotearoa", "kiwi"},
    "Germany": {"germany", "de", "deutschland", "german"},
    "France": {"france", "fr", "french"},
    "Switzerland": {"switzerland", "ch", "swiss"},
    "Netherlands": {"netherlands", "nl", "holland", "dutch"},
    "Sweden": {"sweden", "se", "swedish"},
    "Norway": {"norway", "no", "norwegian"},
    "Finland": {"finland", "fi", "finnish"},
    "Denmark": {"denmark", "dk", "danish"},
    "Italy": {"italy", "it", "italian"},
    "Spain": {"spain", "es", "spanish"},
    "Russia": {"russia", "ru", "russian federation", "russian"},
    "Japan": {"japan", "jp", "japanese"},
    "South Korea": {"south korea", "korea", "kr", "republic of korea", "korean"},
    "China": {"china", "cn", "prc", "people's republic of china", "chinese"},
    "Singapore": {"singapore", "sg", "singaporean"},
    "Hong Kong": {"hong kong", "hk", "hong kong sar"},
    "United Arab Emirates": {"united arab emirates", "uae", "u.a.e.", "dubai", "abu dhabi", "emirati"},
    "Saudi Arabia": {"saudi arabia", "ksa", "saudi"},
    "Qatar": {"qatar", "qa", "qatari"},
    "European Union": {"european union", "eu", "europe", "european"},
}

# Regional groupings
REGIONAL_GROUPS: Dict[str, Set[str]] = {
    "europe": {
        "Germany", "France", "Switzerland", "Netherlands", "Sweden",
        "Norway", "Finland", "Denmark", "Italy", "Spain", "United Kingdom",
        "Ireland", "European Union"
    },
    "asia": {
        "Japan", "South Korea", "China", "Singapore", "Hong Kong"
    },
    "oceania": {
        "Australia", "New Zealand"
    },
    "middle east": {
        "United Arab Emirates", "Saudi Arabia", "Qatar"
    },
    "north america": {
        "Canada", "United States"
    },
}

# Academic and governmental TLDs per country
COUNTRY_TLDS: Dict[str, List[str]] = {
    "Canada": [".ca", ".gc.ca"],
    "United States": [".edu", ".gov"],
    "United Kingdom": [".ac.uk", ".gov.uk"],
    "Ireland": [".ie"],
    "Australia": [".edu.au", ".gov.au"],
    "New Zealand": [".ac.nz", ".govt.nz", ".org.nz"],
    "Germany": [".de", "daad.de"],
    "France": [".fr", "campusfrance.org"],
    "Switzerland": [".ch", "ethz.ch", "epfl.ch"],
    "Netherlands": [".nl"],
    "Sweden": [".se"],
    "Norway": [".no"],
    "Finland": [".fi"],
    "Denmark": [".dk"],
    "Italy": [".it"],
    "Spain": [".es"],
    "Russia": [".ru"],
    "Japan": [".ac.jp", ".jp"],
    "South Korea": [".ac.kr", ".kr"],
    "China": [".edu.cn", ".cn"],
    "Singapore": [".edu.sg", ".sg"],
    "Hong Kong": [".edu.hk", ".hk"],
    "United Arab Emirates": [".ac.ae", ".ae"],
    "Saudi Arabia": [".edu.sa", ".sa"],
    "Qatar": [".edu.qa", ".qa"],
}


def is_worldwide(target_countries: Optional[List[str]]) -> bool:
    """Return True if target_countries indicates global / unrestricted discovery."""
    if not target_countries:
        return True
    for c in target_countries:
        cleaned = c.strip().lower()
        if cleaned in WORLDWIDE_KEYWORDS:
            return True
    return False


def normalize_country(raw_name: Optional[str]) -> Optional[str]:
    """Map any alias, code, or country string to canonical catalog name."""
    if not raw_name or not isinstance(raw_name, str):
        return None
    cleaned = raw_name.strip().lower()
    if cleaned in WORLDWIDE_KEYWORDS:
        return "Worldwide"

    # Exact match in catalog
    for canon, aliases in COUNTRY_CATALOG.items():
        if cleaned == canon.lower() or cleaned in aliases:
            return canon

    # Substring search if no exact match
    for canon, aliases in COUNTRY_CATALOG.items():
        if any(re.search(rf"\b{re.escape(a)}\b", cleaned) for a in aliases):
            return canon

    # Fallback to title-cased raw name
    return raw_name.strip().title()


def is_country_match(opp_country: Optional[str], target_countries: Optional[List[str]]) -> bool:
    """Check if opportunity country matches student's preferred destinations.
    
    Strict Rules:
    - If target_countries is empty or worldwide, matches all destinations.
    - If target_countries specifies destinations but opp_country is missing, does NOT match.
    - Matches canonical names, aliases, and regional groupings.
    """
    if is_worldwide(target_countries):
        return True
    if not opp_country:
        return False

    norm_opp = normalize_country(opp_country)
    opp_low = opp_country.strip().lower()

    for tc in target_countries:  # type: ignore[union-attr]
        tc_clean = tc.strip().lower()
        if tc_clean in WORLDWIDE_KEYWORDS:
            return True

        # Check regional groups (e.g. "europe", "asia")
        if tc_clean in REGIONAL_GROUPS:
            if norm_opp in REGIONAL_GROUPS[tc_clean]:
                return True

        norm_target = normalize_country(tc)
        if norm_opp and norm_target and norm_opp == norm_target:
            return True

        # Check catalog aliases directly
        if norm_target and norm_target in COUNTRY_CATALOG:
            aliases = COUNTRY_CATALOG[norm_target]
            if opp_low in aliases or any(a in opp_low for a in aliases):
                return True

        if tc_clean == opp_low or tc_clean in opp_low or opp_low in tc_clean:
            return True

    return False


def detect_countries_in_query(query: str) -> List[str]:
    """Extract canonical target countries mentioned in a search query string."""
    q_low = query.lower()
    detected = []
    for canon, aliases in COUNTRY_CATALOG.items():
        for a in aliases:
            # Word boundary match to prevent 'us' matching 'focus' or 'ca' matching 'canada'
            if re.search(rf"\b{re.escape(a)}\b", q_low):
                detected.append(canon)
                break
    return detected
