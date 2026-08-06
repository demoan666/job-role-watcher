#!/usr/bin/env python3
"""Fetch job postings from Greenhouse/Lever/SmartRecruiters, filter, diff, and
write data/postings.json + data/archive.json. Stdlib only, no dependencies.

See ../app_build_spec.md for the full spec this implements.
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
COMPANIES_PATH = os.path.join(DATA_DIR, "companies.json")
POSTINGS_PATH = os.path.join(DATA_DIR, "postings.json")
ARCHIVE_PATH = os.path.join(DATA_DIR, "archive.json")
SEARCH_PROFILE_PATH = os.path.join(DATA_DIR, "search_profile.json")
SEARCH_SCOPE_PATH = os.path.join(DATA_DIR, "search_scope.json")
COUNTRY_CODES_PATH = os.path.join(DATA_DIR, "country-codes.json")

USER_AGENT = "job-role-watcher/1.0 (personal job search tool)"
TODAY = date.today().isoformat()

# --- filtering rules, per app_build_spec.md "Filtering logic" -------------
#
# Deviation from the spec's literal "title or description" wording, found
# during local testing: bare single words like "motion" and "animation"
# false-match generic SaaS jargon in description text ("sales motions",
# "implementation motion", etc.) that has nothing to do with motion design.
# Fix: ambiguous single words are matched against the TITLE only (job titles
# reliably say "Motion Designer" when that's the role); multi-word specific
# phrases are unambiguous enough to still match against title-or-description.
# All matching uses word boundaries so "motions" doesn't match "motion".

AMBIGUOUS_TITLE_ONLY_KEYWORDS = [
    "motion",
    "animation",
]
SPECIFIC_KEYWORDS = [
    "video editor",
    "video producer",
    "animator",
    "art director",
    "creative director",
    "motion graphics",
]


def _load_profile_keywords():
    """Additive only — never touches AMBIGUOUS_TITLE_ONLY_KEYWORDS. That
    title-only split exists to fix a real false-positive bug (see
    CLAUDE.md's "Known Bugs"); profile-derived keywords go through the same
    title-or-description matching as the other SPECIFIC_KEYWORDS instead of
    risking that regression. Missing file (profile never set up, or backend
    never run) is expected, not an error — falls back to the hardcoded list.
    """
    if not os.path.exists(SEARCH_PROFILE_PATH):
        return []
    with open(SEARCH_PROFILE_PATH, "r", encoding="utf-8") as f:
        profile = json.load(f)
    return [kw.lower() for kw in profile.get("keywords", []) if kw]


SPECIFIC_KEYWORDS.extend(_load_profile_keywords())
# "brand designer" only counts if description also mentions video/motion/animation
BRAND_DESIGNER = "brand designer"
BRAND_DESIGNER_CONFIRM = ["video", "motion", "animation"]

# cameraman/cinematographer: always excluded. videographer: excluded only when
# paired with one of these context terms (plain "videographer" at a B2B
# company can be legitimate).
ALWAYS_EXCLUDE = ["cameraman", "cinematographer"]
VIDEOGRAPHER = "videographer"
VIDEOGRAPHER_EXCLUDE_CONTEXT = ["wedding", "event photography", "live broadcast"]


def _word_in(term, text):
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None

# Soft location flag only (never a hard drop) — countries treated as
# "hireable without relocation friction" for a Poland-based EU candidate,
# matching research_brief.md's own geography tiers (Nordics, Benelux/DE/CH,
# UK). This is broader than strict EU/EEA membership (includes CH, UK) by
# deliberate choice, since the tracker itself treats those as in-scope tiers.
# Paired name/code so a Setup-tab country selection (ISO codes) can restrict
# both the name-matching (Greenhouse) and code-matching (SmartRecruiters)
# paths consistently — see _effective_countries() below.
COUNTRY_CODE_NAME_PAIRS = [
    ("at", "austria"), ("be", "belgium"), ("bg", "bulgaria"), ("hr", "croatia"),
    ("cy", "cyprus"), ("cz", "czech"), ("dk", "denmark"), ("ee", "estonia"),
    ("fi", "finland"), ("fr", "france"), ("de", "germany"), ("gr", "greece"),
    ("hu", "hungary"), ("ie", "ireland"), ("it", "italy"), ("lv", "latvia"),
    ("lt", "lithuania"), ("lu", "luxembourg"), ("mt", "malta"), ("nl", "netherlands"),
    ("pl", "poland"), ("pt", "portugal"), ("ro", "romania"), ("sk", "slovakia"),
    ("si", "slovenia"), ("es", "spain"), ("se", "sweden"), ("is", "iceland"),
    ("li", "liechtenstein"), ("no", "norway"), ("ch", "switzerland"),
    ("gb", "united kingdom"),
]
HIREABLE_COUNTRY_NAMES = [name for _, name in COUNTRY_CODE_NAME_PAIRS]
# SmartRecruiters returns lowercase ISO-3166-1 alpha-2 codes ("gb", "de") in
# the location field rather than full names, so names alone miss them.
# "uk" kept as an alias for "gb" — some sources use it non-standardly.
HIREABLE_COUNTRY_CODES = {code for code, _ in COUNTRY_CODE_NAME_PAIRS} | {"uk"}
REMOTE_HINTS = ["remote"]


def _load_full_country_name_map():
    """data/country-codes.json — the same vendored ISO 3166-1 alpha-2 ->
    name mapping the Setup tab's country map/list uses (175 entries,
    global, see data/world-map.svg.LICENSE.txt) — so a selected country
    outside the curated default allowlist below still matches on name,
    not just on raw ISO code."""
    if not os.path.exists(COUNTRY_CODES_PATH):
        return {}
    with open(COUNTRY_CODES_PATH, "r", encoding="utf-8") as f:
        entries = json.load(f)
    return {e["code"].lower(): e["name"].lower() for e in entries}


def _effective_countries():
    """Setup-tab country selection (ISO codes, data/search_scope.json)
    restricts the default hardcoded allowlist above when present; an
    empty/absent selection means "no restriction configured yet", falling
    back to the full default list — same additive/defensive pattern as
    _load_profile_keywords(). The default list stays the curated EU/EEA+UK+CH
    "hireable without relocation friction" set on purpose (research_brief.md's
    own framing) — it does NOT expand just because the global map/mapping
    file supports more countries; only an explicit user selection reaches
    beyond it.
    """
    scope = {}
    if os.path.exists(SEARCH_SCOPE_PATH):
        with open(SEARCH_SCOPE_PATH, "r", encoding="utf-8") as f:
            scope = json.load(f)
    selected = {c.lower() for c in (scope.get("countries") or [])}
    if not selected:
        return HIREABLE_COUNTRY_CODES, HIREABLE_COUNTRY_NAMES
    name_map = _load_full_country_name_map()
    names = [name_map[code] for code in selected if code in name_map]
    return selected, names


EFFECTIVE_COUNTRY_CODES, EFFECTIVE_COUNTRY_NAMES = _effective_countries()


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", file=sys.stderr)


def http_get_json(url, retries=3, backoff=1.5):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = backoff ** attempt
                log(f"429 rate-limited on {url}, retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            log(f"HTTP {e.code} fetching {url}: {e.reason}")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                wait = backoff ** attempt
                log(f"error fetching {url} ({e}), retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            log(f"giving up on {url}: {e}")
            return None
    return None


def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# --- per-ATS fetchers: each returns a list of raw posting dicts -----------
# {id, title, location, description, url}

def _employment_label(value):
    """Normalizes the various shapes ATS APIs use for employment type into a
    plain lowercase string, or None if genuinely absent — never guessed."""
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("label") or value.get("name")
    if not value:
        return None
    return str(value).strip().lower() or None


def fetch_greenhouse(slug):
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = http_get_json(url)
    if not data:
        return []
    out = []
    for job in data.get("jobs", []):
        # Greenhouse's public boards API has no standard employment-type
        # field — contract_type stays unknown rather than guessed.
        out.append({
            "id": str(job.get("id")),
            "title": job.get("title", "") or "",
            "location": (job.get("location") or {}).get("name", "") or "",
            "description": strip_html(job.get("content", "")),
            "url": job.get("absolute_url", "") or "",
            "contract_type": None,
        })
    return out


def fetch_lever(slug):
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    data = http_get_json(url)
    if not data:
        return []
    out = []
    for job in data:
        categories = job.get("categories", {}) or {}
        description = job.get("descriptionPlain") or strip_html(job.get("description", ""))
        lists_text = " ".join(
            strip_html(item.get("content", ""))
            for lst in (job.get("lists") or [])
            for item in [lst]
        )
        out.append({
            "id": str(job.get("id")),
            "title": job.get("text", "") or "",
            "location": categories.get("location", "") or "",
            "description": f"{description} {lists_text}".strip(),
            "url": job.get("hostedUrl", "") or "",
            "contract_type": _employment_label(categories.get("commitment")),
        })
    return out


def fetch_smartrecruiters(slug):
    out = []
    offset = 0
    limit = 100
    total = None
    listed = []
    while total is None or offset < total:
        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={limit}&offset={offset}"
        data = http_get_json(url)
        if not data:
            break
        total = data.get("totalFound", 0)
        content = data.get("content", [])
        if not content:
            break
        listed.extend(content)
        offset += limit
        time.sleep(0.1)

    for item in listed:
        posting_id = item.get("id")
        title = item.get("name", "") or ""
        loc = item.get("location", {}) or {}
        location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
        remote_hint = bool(loc.get("remote"))

        # cameraman/cinematographer are always-exclude regardless of description,
        # so skip the detail fetch for those to save API calls.
        title_lower = title.lower()
        if any(term in title_lower for term in ALWAYS_EXCLUDE):
            continue

        description = ""
        contract_type = _employment_label(item.get("typeOfEmployment"))
        detail_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"
        detail = http_get_json(detail_url)
        if detail:
            job_ad = detail.get("jobAd", {}) or {}
            sections = (job_ad.get("sections") or {})
            parts = []
            for section in sections.values():
                if isinstance(section, dict):
                    parts.append(strip_html(section.get("text", "")))
            description = " ".join(parts)
            contract_type = contract_type or _employment_label(detail.get("typeOfEmployment"))
        time.sleep(0.1)

        posting_url = item.get("ref") or f"https://jobs.smartrecruiters.com/{slug}/{posting_id}"
        out.append({
            "id": str(posting_id),
            "title": title,
            "location": location,
            "description": description,
            "url": posting_url,
            "_remote_hint": remote_hint,
            "contract_type": contract_type,
        })
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "smartrecruiters": fetch_smartrecruiters,
}


# --- filtering --------------------------------------------------------

def matches_include(title, description):
    title_l = title.lower()
    haystack = f"{title_l} {description.lower()}"
    if any(_word_in(kw, title_l) for kw in AMBIGUOUS_TITLE_ONLY_KEYWORDS):
        return True
    if any(_word_in(kw, haystack) for kw in SPECIFIC_KEYWORDS):
        return True
    if _word_in(BRAND_DESIGNER, haystack):
        if any(_word_in(term, haystack) for term in BRAND_DESIGNER_CONFIRM):
            return True
    return False


def matches_exclude(title, description):
    haystack = f"{title.lower()} {description.lower()}"
    if any(_word_in(term, haystack) for term in ALWAYS_EXCLUDE):
        return True
    if _word_in(VIDEOGRAPHER, haystack):
        if any(_word_in(ctx, haystack) for ctx in VIDEOGRAPHER_EXCLUDE_CONTEXT):
            return True
    return False


def location_ok(location, remote_hint):
    haystack = location.lower()
    if remote_hint or any(term in haystack for term in REMOTE_HINTS):
        return True
    tokens = [w for part in re.split(r"[,/]", haystack) for w in part.split()]
    if any(tok in EFFECTIVE_COUNTRY_CODES for tok in tokens):
        return True
    return any(name in haystack for name in EFFECTIVE_COUNTRY_NAMES)


def filter_postings(raw_postings, company):
    matched = []
    for p in raw_postings:
        title, description = p["title"], p["description"]
        if not matches_include(title, description):
            continue
        if matches_exclude(title, description):
            continue
        remote_hint = p.get("_remote_hint", False)
        matched.append({
            "id": f"{company['ats']}:{company['name']}:{p['id']}",
            "company": company["name"],
            "cluster": company.get("cluster", ""),
            "title": title,
            "location": p["location"],
            "remote": remote_hint or "remote" in p["location"].lower(),
            "eu_hireable_or_remote": location_ok(p["location"], remote_hint),
            "url": p["url"],
            "ats": company["ats"],
            "contract_type": p.get("contract_type"),
        })
    return matched


# --- diffing / persistence --------------------------------------------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def diff_and_write(current_matches):
    previous_postings = {p["id"]: p for p in load_json(POSTINGS_PATH, [])}
    archive = load_json(ARCHIVE_PATH, [])
    archived_ids = {a["id"] for a in archive}

    current_by_id = {}
    for m in current_matches:
        prev = previous_postings.get(m["id"])
        m["first_seen"] = prev["first_seen"] if prev else TODAY
        current_by_id[m["id"]] = m

    new_postings = list(current_by_id.values())

    for pid, prev in previous_postings.items():
        if pid not in current_by_id and pid not in archived_ids:
            archived_entry = dict(prev)
            archived_entry["closed_date"] = TODAY
            archive.append(archived_entry)

    new_postings.sort(key=lambda p: (p["cluster"], p["company"], p["title"]))
    save_json(POSTINGS_PATH, new_postings)
    save_json(ARCHIVE_PATH, archive)
    return new_postings, archive


def main():
    companies = load_json(COMPANIES_PATH, [])
    # Missing search_scope.json (Setup mode never used) means "everything
    # active" — same backward-compatible default as the profile keywords.
    scope = load_json(SEARCH_SCOPE_PATH, {})
    active_ats = scope.get("active_ats") or list(FETCHERS.keys())

    all_matches = []
    for company in companies:
        if company.get("ats_slug_needed"):
            log(f"skipping {company['name']}: ats_slug_needed")
            continue
        if company.get("enabled", True) is False:
            log(f"skipping {company['name']}: disabled in search scope")
            continue
        ats = company.get("ats")
        if ats not in active_ats:
            log(f"skipping {company['name']}: {ats} not in active_ats scope")
            continue
        fetcher = FETCHERS.get(ats)
        if not fetcher:
            log(f"skipping {company['name']}: unknown ats '{ats}'")
            continue
        log(f"fetching {company['name']} ({ats}:{company['slug']})")
        raw = fetcher(company["slug"])
        matches = filter_postings(raw, company)
        log(f"  {len(raw)} postings fetched, {len(matches)} matched filters")
        all_matches.extend(matches)

    postings, archive = diff_and_write(all_matches)
    log(f"done: {len(postings)} active postings, {len(archive)} archived")


if __name__ == "__main__":
    main()
