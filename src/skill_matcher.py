"""
Skill matcher - filters and scores job listings against user-defined skills.
Includes: synonym/alias matching, smart US location detection, multi-location handling.
"""

import re
import logging
from typing import List, Dict, Tuple, Set

logger = logging.getLogger(__name__)

# ================================================================
#  BUILT-IN ROLE SYNONYMS
#  Each group = related job titles that should match each other.
#  If a user configures "data analyst", ALL synonyms in that group
#  are automatically included in matching.
# ================================================================

BUILT_IN_ROLE_SYNONYMS = [
    # Data & Analytics
    {
        "data analyst", "data analytics", "analytics analyst", "quantitative analyst",
        "data analytics specialist", "junior data analyst", "associate data analyst",
        "data analysis", "analytics associate", "insight analyst", "decision analyst",
    },
    {
        "data scientist", "data science", "applied scientist", "research scientist",
        "quantitative researcher", "decision scientist", "analytics scientist",
    },
    {
        "data engineer", "data engineering", "analytics engineer", "data platform engineer",
        "ETL developer", "data infrastructure engineer", "big data engineer",
    },
    {
        "business analyst", "business analytics", "strategy analyst", "operations analyst",
        "process analyst", "management analyst", "business systems analyst",
    },
    {
        "business intelligence", "BI analyst", "BI developer", "BI engineer",
        "business intelligence analyst", "business intelligence developer",
        "reporting analyst", "insights analyst",
    },

    # Machine Learning & AI
    {
        "ML engineer", "machine learning engineer", "machine learning", "ML developer",
        "applied ML engineer", "ML ops engineer", "MLOps",
    },
    {
        "AI engineer", "artificial intelligence engineer", "deep learning engineer",
        "NLP engineer", "computer vision engineer", "AI/ML engineer",
    },

    # Marketing & Growth
    {
        "marketing analyst", "marketing analytics", "growth analyst",
        "digital marketing analyst", "marketing data analyst",
        "performance marketing analyst", "campaign analyst",
    },
    {
        "marketing operations", "marketing ops", "marketing operations manager",
        "marketing operations specialist", "marketing automation",
        "demand generation", "revenue operations",
    },
    {
        "sales operations", "sales ops", "revenue operations", "RevOps",
        "sales operations analyst", "sales analytics", "GTM operations",
        "go-to-market operations",
    },

    # Program & Product
    {
        "program analyst", "program manager", "program coordinator",
        "technical program manager", "TPM",
    },
    {
        "product analyst", "product analytics", "product data analyst",
        "growth product analyst",
    },

    # Software Engineering (broad)
    {
        "software engineer", "software developer", "SWE", "SDE",
        "application developer", "backend engineer", "full stack engineer",
        "fullstack engineer", "full-stack engineer",
    },
    {
        "robotics engineer", "robotics software engineer", "robotics developer",
        "automation engineer", "controls engineer", "motion planning engineer",
        "perception engineer",
    },
]

# Technical skill synonyms (abbreviations ↔ full names)
BUILT_IN_TECH_SYNONYMS = [
    {"Python", "python3", "python programming"},
    {"SQL", "structured query language", "MySQL", "PostgreSQL", "Postgres"},
    {"Tableau", "tableau desktop", "tableau server"},
    {"Power BI", "PowerBI", "power bi"},
    {"machine learning", "ML", "statistical modeling"},
    {"deep learning", "DL", "neural networks"},
    {"ETL", "extract transform load", "data pipeline", "data pipelines"},
    {"A/B testing", "AB testing", "experimentation", "split testing"},
    {"CRM", "customer relationship management"},
    {"NLP", "natural language processing"},
    {"computer vision", "CV", "image recognition"},
    {"CI/CD", "continuous integration", "continuous deployment"},
    {"AWS", "Amazon Web Services"},
    {"GCP", "Google Cloud Platform", "Google Cloud"},
    {"Azure", "Microsoft Azure"},
]

# ================================================================
#  BUILT-IN EXCLUSION PATTERNS (defense-in-depth)
#  These regex patterns catch US citizenship / export-control /
#  security-clearance requirements regardless of user config.
#  Compiled once at import time for zero per-job overhead.
# ================================================================
BUILT_IN_EXCLUDE_PATTERNS = [
    re.compile(r'\bu\.?s\.?\s*person\b', re.IGNORECASE),
    re.compile(r'\bexport[- ]control', re.IGNORECASE),
    re.compile(r'\bmust\s+be\s+a?\s*u\.?s\.?\s*(citizen|person|national)\b', re.IGNORECASE),
    re.compile(r'\b(ts|top\s*secret)[/ ]sci\b', re.IGNORECASE),
    re.compile(r'\bobtain\b.*\b(security\s+clearance|clearance)\b', re.IGNORECASE),
    re.compile(r'\bactive\b.*\bclearance\b', re.IGNORECASE),
]


def _build_synonym_map(synonym_groups: list, configured_keywords: list) -> Dict[str, Set[str]]:
    """
    Build a mapping from each configured keyword to all its synonyms.
    Only expands keywords that appear in a synonym group.
    """
    keyword_to_synonyms = {}
    configured_lower = {k.lower() for k in configured_keywords}

    for group in synonym_groups:
        group_lower = {s.lower() for s in group}
        # Check if any configured keyword is in this group
        overlap = configured_lower & group_lower
        if overlap:
            # For each configured keyword in this group, add all group members as synonyms
            for kw in overlap:
                keyword_to_synonyms[kw] = group_lower - {kw}

    return keyword_to_synonyms


# ================================================================
#  US LOCATION DETECTION
# ================================================================

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI",
}

US_LOCATION_KEYWORDS = [
    "united states", "usa", "u.s.a", "u.s.",
]

US_LOCATION_PATTERN = re.compile(
    r',\s*(' + '|'.join(US_STATE_CODES) + r')\b',
    re.IGNORECASE
)

# Patterns that indicate the job is available in the US even without a specific city
US_MULTI_LOCATION_KEYWORDS = [
    "multiple locations", "various locations", "multiple us locations",
    "various us offices", "nationwide", "multiple offices",
    "locations across the us", "us locations", "us offices",
    "open to all locations",
]

# Non-US country keywords — if these appear alongside "multiple locations",
# the job is NOT considered US
NON_US_COUNTRY_KEYWORDS = [
    "india", "uk", "united kingdom", "germany", "canada", "australia",
    "japan", "china", "singapore", "brazil", "france", "ireland",
    "netherlands", "israel", "south korea", "taiwan", "mexico",
    "europe", "asia", "emea", "apac", "latam",
]

US_STATES_FULL = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
]


def is_us_location(location: str) -> bool:
    """Detect if a location string refers to a US location."""
    loc_lower = location.lower().strip()

    # Explicit US keywords
    for kw in US_LOCATION_KEYWORDS:
        if kw in loc_lower:
            return True

    # Multi-location keywords that imply US (but not if a non-US country is mentioned)
    for kw in US_MULTI_LOCATION_KEYWORDS:
        if kw in loc_lower:
            # Check if a non-US country is also mentioned
            has_non_us = any(country in loc_lower for country in NON_US_COUNTRY_KEYWORDS)
            if not has_non_us:
                return True

    # "City, STATE" pattern
    if US_LOCATION_PATTERN.search(location):
        return True

    # Full state names
    for state in US_STATES_FULL:
        if state in loc_lower:
            return True

    # Multiple "City, ST" entries separated by | / ; or newlines
    # e.g., "San Jose, CA | Austin, TX | New York, NY"
    if re.search(r'[|/;]', location):
        parts = re.split(r'[|/;]', location)
        for part in parts:
            if US_LOCATION_PATTERN.search(part.strip()):
                return True

    return False


# ================================================================
#  SKILL MATCHER
# ================================================================

class SkillMatcher:
    """Match job listings against configured skills with synonym expansion."""

    def __init__(self, config: dict):
        skills_cfg = config.get("skills", {})
        self.primary_keywords = [k.lower() for k in skills_cfg.get("primary", [])]
        self.technical_keywords = [k.lower() for k in skills_cfg.get("technical", [])]
        self.exclude_keywords = [k.lower() for k in skills_cfg.get("exclude", [])]

        # Load user-defined synonyms from config
        user_role_synonyms = skills_cfg.get("role_synonyms", [])
        user_tech_synonyms = skills_cfg.get("tech_synonyms", [])

        # Merge built-in + user synonyms
        all_role_groups = BUILT_IN_ROLE_SYNONYMS + [set(g) for g in user_role_synonyms]
        all_tech_groups = BUILT_IN_TECH_SYNONYMS + [set(g) for g in user_tech_synonyms]

        # Build synonym maps
        self.primary_synonyms = _build_synonym_map(all_role_groups, self.primary_keywords)
        self.tech_synonyms = _build_synonym_map(all_tech_groups, self.technical_keywords)

        # Build expanded keyword lists (original + all synonyms)
        self.primary_expanded = {}
        for kw in self.primary_keywords:
            synonyms = self.primary_synonyms.get(kw, set())
            self.primary_expanded[kw] = {kw} | synonyms

        self.tech_expanded = {}
        for kw in self.technical_keywords:
            synonyms = self.tech_synonyms.get(kw, set())
            self.tech_expanded[kw] = {kw} | synonyms

        # Log synonym expansion
        for kw, syns in self.primary_synonyms.items():
            if syns:
                logger.debug(f"  Synonym expansion: '{kw}' → +{len(syns)} variants")

        loc_cfg = config.get("locations", {})
        self.include_remote = loc_cfg.get("include_remote", True)
        self.preferred_locations = [l.lower() for l in loc_cfg.get("preferred", [])]
        self.country = loc_cfg.get("country", "").upper().strip()

        exp_cfg = config.get("experience", {})
        self.max_years = exp_cfg.get("max_years", 5)

    def _check_keywords(self, keywords_expanded: dict, text: str,
                        text_label: str, score_per_match: float) -> Tuple[float, List[str]]:
        """Check expanded keywords against text. Returns (score, matched_list)."""
        score = 0.0
        matched = []
        for original_kw, variants in keywords_expanded.items():
            for variant in variants:
                if variant in text:
                    if variant == original_kw:
                        matched.append(original_kw)
                    else:
                        matched.append(f"{original_kw}→{variant}")
                    score += score_per_match
                    break  # One match per keyword group is enough
        return score, matched

    def _score_location(self, location: str) -> float:
        """
        Score a job's location.
          +5  = preferred city match
          +4  = remote job
          +3  = country match (any US city/state/multi-location)
          +0  = no match
        """
        loc_lower = location.lower()
        score = 0.0

        # Country-level match
        if self.country == "US" and is_us_location(location):
            score = 3.0

        # Preferred city/region match
        if self.preferred_locations:
            for pref in self.preferred_locations:
                if pref in loc_lower:
                    score = max(score, 5.0)
                    break

        # Remote
        if self.include_remote and "remote" in loc_lower:
            score = max(score, 4.0)

        # No filters set = accept all
        if not self.country and not self.preferred_locations:
            score = 3.0

        return score

    def match_job(self, job: Dict) -> Tuple[bool, float, List[str]]:
        """
        Evaluate a job against configured criteria with synonym expansion.
        Returns: (is_match, relevance_score, matched_keywords)
        """
        title = job.get("title", "").lower()
        description = job.get("description", "").lower()
        location = job.get("location", "").lower()
        department = job.get("department", "").lower()
        searchable = f"{title} {description} {department}"

        # --- EXCLUSION CHECK (full text) ---
        # Short keywords (≤4 chars) use word-boundary regex to avoid
        # false positives (e.g., "EAR" matching inside "learning")
        for kw in self.exclude_keywords:
            if len(kw) <= 4:
                if re.search(r'\b' + re.escape(kw) + r'\b', searchable):
                    return False, 0.0, []
            else:
                if kw in searchable:
                    return False, 0.0, []

        # --- BUILT-IN EXCLUSION PATTERNS (regex, always active) ---
        for pattern in BUILT_IN_EXCLUDE_PATTERNS:
            if pattern.search(searchable):
                return False, 0.0, []

        # --- PRIMARY KEYWORD MATCH (with synonyms) ---
        matched = []
        title_score = 0.0   # matches in title/department
        desc_score = 0.0    # matches in description only

        for original_kw, variants in self.primary_expanded.items():
            best_match = None
            match_in = None

            for variant in variants:
                if variant in title or variant in department:
                    best_match = variant
                    match_in = "title"
                    break  # Title match is best, stop looking
                elif variant in description and match_in != "title":
                    best_match = variant
                    match_in = "desc"

            if best_match:
                if match_in == "title":
                    if best_match == original_kw:
                        matched.append(original_kw)
                    else:
                        matched.append(f"{original_kw}→{best_match}")
                    title_score += 10.0
                else:
                    if best_match == original_kw:
                        matched.append(f"{original_kw} (desc)")
                    else:
                        matched.append(f"{original_kw}→{best_match} (desc)")
                    desc_score += 3.0

        # Must match at least one primary keyword in TITLE/DEPARTMENT
        # Description-only matches boost score but cannot qualify a job
        if title_score == 0:
            return False, 0.0, []

        primary_score = title_score + desc_score

        # --- TECHNICAL SKILL BOOST (with synonyms) ---
        tech_score = 0.0
        for original_kw, variants in self.tech_expanded.items():
            for variant in variants:
                if variant in searchable:
                    if variant == original_kw:
                        matched.append(f"🔧 {original_kw}")
                    else:
                        matched.append(f"🔧 {original_kw}→{variant}")
                    tech_score += 2.0
                    break

        # --- LOCATION SCORE ---
        loc_score = self._score_location(job.get("location", ""))

        # If a country filter is set, REJECT jobs outside that country
        # (loc_score 0 means: not in target country, not remote, not preferred city)
        if self.country and loc_score == 0:
            return False, 0.0, []

        # --- EXPERIENCE CHECK ---
        # Find ALL "X+ years" mentions and reject if ANY exceed max_years
        # (re.search only returns the first match, which may be a smaller number)
        years_matches = re.findall(r'(\d+)\+?\s*years?', searchable)
        if years_matches:
            max_required = max(int(y) for y in years_matches)
            if max_required > self.max_years:
                return False, 0.0, []

        # --- FINAL SCORE ---
        total_score = primary_score + tech_score + loc_score
        return True, round(total_score, 1), matched

    def filter_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filter and score a list of jobs. Returns matched jobs sorted by score."""
        matched_jobs = []
        for job in jobs:
            is_match, score, keywords = self.match_job(job)
            if is_match:
                job["relevance_score"] = score
                job["matched_keywords"] = keywords
                matched_jobs.append(job)

        matched_jobs.sort(key=lambda x: x["relevance_score"], reverse=True)
        logger.info(f"Matched {len(matched_jobs)} / {len(jobs)} jobs")
        return matched_jobs
