"""Contact-resolution orchestrator (plan Phase 2, decisions #5/#6/#7).

Walks the configured EnrichmentProvider chain (free company-page scraper
first, then paid fallbacks — see providers/enrichment.py) for one company,
then labels each result with a contact tier (named-decision-maker /
named-junior / generic-inbox) using a size-aware decision-maker title list.
All tiers are returned, never silently filtered (decision #5) — the caller
decides what to do with a generic-inbox contact, this module doesn't drop it.
"""

import json
from urllib.parse import urlparse

import db
from providers import enrichment as enrichment_providers

DEFAULT_DECISION_MAKER_TITLES = [
    "founder", "co-founder", "owner", "ceo", "cmo", "creative director",
    "head of marketing", "head of creative", "head of brand", "head of content",
    "vp marketing", "vp creative", "marketing director", "brand director",
    "director of marketing", "director of creative",
]
DEFAULT_SIZE_THRESHOLDS = {"small_max": 50, "large_min": 250}


def get_decision_maker_titles():
    raw = db.get_setting("enrichment_decision_maker_titles")
    return json.loads(raw) if raw else list(DEFAULT_DECISION_MAKER_TITLES)


def save_decision_maker_titles(titles):
    db.set_setting("enrichment_decision_maker_titles", json.dumps(titles, ensure_ascii=False))


def get_size_thresholds():
    raw = db.get_setting("enrichment_size_thresholds")
    return json.loads(raw) if raw else dict(DEFAULT_SIZE_THRESHOLDS)


def save_size_thresholds(thresholds):
    db.set_setting("enrichment_size_thresholds", json.dumps(thresholds, ensure_ascii=False))


def get_provider_order(industry=None):
    """Global default, optionally overridden per industry (decision #7).
    Falls back to providers.enrichment.DEFAULT_ORDER if nothing is
    configured yet."""
    by_industry = json.loads(db.get_setting("enrichment_provider_order_by_industry", "{}") or "{}")
    if industry and industry in by_industry:
        return by_industry[industry]
    raw = db.get_setting("enrichment_provider_order")
    return json.loads(raw) if raw else list(enrichment_providers.DEFAULT_ORDER)


def save_provider_order(order, industry=None):
    if industry:
        by_industry = json.loads(db.get_setting("enrichment_provider_order_by_industry", "{}") or "{}")
        by_industry[industry] = order
        db.set_setting("enrichment_provider_order_by_industry", json.dumps(by_industry, ensure_ascii=False))
    else:
        db.set_setting("enrichment_provider_order", json.dumps(order, ensure_ascii=False))


def domain_from_url(url):
    if not url:
        return None
    netloc = urlparse(url if "://" in url else f"https://{url}").netloc
    return netloc.split(":")[0] or None


def label_tier(contact, decision_maker_titles):
    """Decision #6 (size-aware targeting) is only partially implementable
    today — no company-size data source exists yet (would need its own
    enrichment integration, e.g. Clearbit; out of scope for what this
    session had credentials for), so tiering currently runs title-match-only
    regardless of company size. company_size stays a parameter so wiring in
    a real size signal later is additive, not a rewrite of this function."""
    if not contact.get("name"):
        return "generic_inbox"
    role = (contact.get("role") or "").lower()
    if any(title.lower() in role for title in decision_maker_titles):
        return "named_decision_maker"
    return "named_junior"


def enrich_company(company_name, company_url, industry=None, company_size=None):
    """Runs the provider chain in configured order, stopping at the first
    provider that returns at least one contact (keeps paid-API usage to a
    minimum — decision #7's "free first" framing). Returns a list of
    {"name", "role", "email", "source", "tier"} — every tier included,
    nothing filtered out here (decision #5).

    When "Dry run mode" (Settings > Pipeline) is on, the configured chain is
    bypassed entirely in favor of providers.enrichment.MockEnrichmentProvider
    — no team-page scrape, no paid API call, regardless of what's ordered/
    keyed elsewhere."""
    domain = domain_from_url(company_url)
    decision_maker_titles = get_decision_maker_titles()
    order = ["mock"] if db.get_setting("dry_run_mode", "false") == "true" else get_provider_order(industry)

    for provider_id in order:
        provider = enrichment_providers.get_provider(provider_id)
        if not provider:
            continue
        results = provider.find_contacts(company_name, domain)
        if results:
            for r in results:
                r["tier"] = label_tier(r, decision_maker_titles)
            return results
    return []
