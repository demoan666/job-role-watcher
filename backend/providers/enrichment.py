"""EnrichmentProvider — finds named contacts at a company (plan decision #7).
Chain order is configurable in Settings (global default + per-industry
override); company-page scraping is free and tried first, paid APIs are
optional fallbacks. Every paid provider is gated on its own key (vault-first,
plaintext config.json fallback, same pattern as llm.py) and fails closed —
returns an empty list, never raises — when unconfigured, so an unfinished
provider never breaks the enrichment chain for the ones that *are* set up.
"""

import re
from abc import ABC, abstractmethod
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import vault

USER_AGENT = "job-search-command-center/1.0 (personal job search tool)"
TEAM_PAGE_PATHS = ["/team", "/about/team", "/about-us/team", "/company/team", "/leadership", "/about"]
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


class EnrichmentProvider(ABC):
    id = None

    @abstractmethod
    def find_contacts(self, company_name, company_domain, role_hint=None):
        """Returns a list of {"name": str|None, "role": str|None,
        "email": str|None, "source": provider id}."""
        raise NotImplementedError


class CompanyPageScraperProvider(EnrichmentProvider):
    """Free, tried first (decision #7). Looks for a /team-style page on the
    company's own site and pulls name/role pairs + any visible email
    addresses. Real but deliberately shallow — team-page HTML structure
    varies too much across companies for anything more than a best-effort
    heuristic; a miss here just falls through to the next provider in chain,
    it doesn't fail the whole lookup."""
    id = "company_page_scraper"

    def find_contacts(self, company_name, company_domain, role_hint=None):
        if not company_domain:
            return []
        for path in TEAM_PAGE_PATHS:
            url = urljoin(f"https://{company_domain}", path)
            try:
                resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            except requests.RequestException:
                continue
            if resp.status_code != 200:
                continue
            found = self._extract(BeautifulSoup(resp.text, "html.parser"))
            if found:
                return found
        return []

    def _extract(self, soup):
        found = []
        for card in soup.select("[class*=team], [class*=member], [class*=staff], [class*=people]"):
            heading = card.find(["h2", "h3", "h4"])
            if not heading:
                continue
            name = heading.get_text(strip=True)
            if not name or len(name.split()) > 5:
                continue
            role_el = card.find(["p", "span"], class_=re.compile("title|role|position", re.I))
            found.append({
                "name": name,
                "role": role_el.get_text(strip=True) if role_el else None,
                "email": None,
                "source": self.id,
            })
        for email in sorted(set(EMAIL_RE.findall(soup.get_text()))):
            found.append({"name": None, "role": None, "email": email, "source": self.id})
        return found


def _config_secret(vault_key, config_path_parts):
    """vault-first, plaintext-config-fallback lookup for a single enrichment
    API key — same precedence as llm.py's key resolution."""
    if vault.is_initialized() and vault.is_unlocked():
        key = vault.get_secret(vault_key)
        if key:
            return key
    import config
    try:
        cfg = config.load_config()
    except FileNotFoundError:
        return None
    node = cfg
    for part in config_path_parts:
        node = (node or {}).get(part)
    return node or None


class HunterProvider(EnrichmentProvider):
    """Hunter.io domain-search API — the default paid fallback per decision
    #7 (free tier: 25-50 searches/mo). Real API integration; fails closed
    with an empty list when no key is configured, matching this app's
    existing "integration point never crashes the rest of the app"
    convention (see CLAUDE.md)."""
    id = "hunter"
    BASE_URL = "https://api.hunter.io/v2/domain-search"

    def find_contacts(self, company_name, company_domain, role_hint=None):
        api_key = _config_secret("enrichment:hunter", ["enrichment", "hunter_api_key"])
        if not api_key or not company_domain:
            return []
        try:
            resp = requests.get(
                self.BASE_URL,
                params={"domain": company_domain, "api_key": api_key, "limit": 10},
                timeout=15,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        data = resp.json().get("data", {})
        return [
            {
                "name": " ".join(filter(None, [e.get("first_name"), e.get("last_name")])) or None,
                "role": e.get("position"),
                "email": e.get("value"),
                "source": self.id,
            }
            for e in data.get("emails", [])
        ]


class _UnimplementedEnrichmentProvider(EnrichmentProvider):
    """Placeholder for the alternate/industry-specific providers named in
    decision #7 (RocketReach, Apollo, ContactOut, Snov/FindyMail) — this
    session had no accounts/keys for any of them. Selectable in Settings
    like any real provider (so the order/selection UI doesn't need to know
    which ones are "real" yet), but find_contacts() fails closed with an
    empty list. Wire up the real API call in a subclass following
    HunterProvider's shape above once a key exists — do not guess at an
    unverified API contract."""

    def __init__(self, provider_id, label):
        self.id = provider_id
        self.label = label

    def find_contacts(self, company_name, company_domain, role_hint=None):
        return []


ROCKETREACH = _UnimplementedEnrichmentProvider("rocketreach", "RocketReach")
APOLLO = _UnimplementedEnrichmentProvider("apollo", "Apollo")
CONTACTOUT = _UnimplementedEnrichmentProvider("contactout", "ContactOut")
SNOV = _UnimplementedEnrichmentProvider("snov", "Snov/FindyMail")

REGISTRY = {
    p.id: p for p in [CompanyPageScraperProvider(), HunterProvider(), ROCKETREACH, APOLLO, CONTACTOUT, SNOV]
}
DEFAULT_ORDER = ["company_page_scraper", "hunter", "rocketreach", "apollo", "contactout", "snov"]


def get_provider(provider_id):
    return REGISTRY.get(provider_id)
