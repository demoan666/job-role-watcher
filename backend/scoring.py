"""Rule-based weighted posting scorer (plan Phase 1, decisions #12 and #14).
Cheap and deterministic — no LLM call — narrows/ranks the pool the unified
send queue (Phase 3) works from. Decision #14's "hybrid" scoring (rule-based
narrows, LLM re-ranks the shortlist for nuance) isn't built yet: llm.py has
no posting-scoring task today, deliberately left out until the unified queue
actually needs it — this module is the "rule-based-only mode" half of that
decision on its own, and stays useful even if the LLM half never lands.
"""

import json
import re
from datetime import date

import db

DEFAULT_WORK_MODE_WEIGHTS = {"remote": 0.6, "hybrid": 0.3, "onsite": 0.1}
RECENCY_HALF_LIFE_DAYS = 21


def get_work_mode_weights():
    """Normalized so remote+hybrid+onsite always sum to 1, per decision #12
    — a user typing 5/3/1 in Settings is treated the same as 0.5/0.3/0.2."""
    raw = db.get_setting("scoring_work_mode_weights")
    weights = json.loads(raw) if raw else dict(DEFAULT_WORK_MODE_WEIGHTS)
    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def save_work_mode_weights(weights):
    db.set_setting("scoring_work_mode_weights", json.dumps(weights, ensure_ascii=False))


def infer_work_mode(posting):
    """Postings only carry a remote bool + free-text location (see
    scripts/fetch_postings.py) — hybrid/onsite aren't distinguished
    upstream, so this infers from location text. Unknown/empty location
    defaults to "onsite" (conservative — never assume remote without a
    signal)."""
    location = (posting.get("location") or "").lower()
    if posting.get("remote") or "remote" in location:
        return "remote"
    if "hybrid" in location:
        return "hybrid"
    return "onsite"


def _keyword_score(title, keywords):
    if not keywords:
        return 0.5  # no profile set up yet — neutral, not a penalty
    title_l = title.lower()
    hits = sum(1 for kw in keywords if kw and re.search(r"\b" + re.escape(kw.lower()) + r"\b", title_l))
    # A couple of solid title hits should already saturate — requiring most
    # of a large keyword list to match a single job title isn't realistic.
    return min(1.0, hits / max(1, len(keywords) * 0.3))


def _industry_score(cluster, industries):
    if not industries:
        return 0.5
    return 1.0 if cluster and cluster in industries else 0.2


def _recency_score(first_seen):
    if not first_seen:
        return 0.5
    try:
        days_old = (date.today() - date.fromisoformat(first_seen)).days
    except ValueError:
        return 0.5
    return 0.5 ** (max(0, days_old) / RECENCY_HALF_LIFE_DAYS)


def score_posting(posting, profile_keywords, profile_industries, work_mode_weights=None):
    """Returns (score: float 0-1, breakdown: dict) — breakdown is stored
    alongside the score (postings.score_breakdown_json) so the frontend can
    show "why" a posting ranked where it did, not just the number."""
    weights = work_mode_weights or get_work_mode_weights()
    work_mode = infer_work_mode(posting)
    breakdown = {
        "keyword": _keyword_score(posting.get("title", ""), profile_keywords),
        "industry": _industry_score(posting.get("cluster"), profile_industries),
        "work_mode": weights.get(work_mode, 0.1),
        "recency": _recency_score(posting.get("first_seen")),
        "work_mode_tag": work_mode,
    }
    score = (
        0.40 * breakdown["keyword"]
        + 0.20 * breakdown["industry"]
        + 0.25 * breakdown["work_mode"]
        + 0.15 * breakdown["recency"]
    )
    return round(score, 4), breakdown
