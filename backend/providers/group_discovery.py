"""GroupDiscoveryProvider — scans public directories for Telegram/Discord
communities matching a keyword (decision #9: automated *discovery* only,
never automated joining — WhatsApp/Slack have no public directory and stay
manual-add, per Setup's existing quick-capture box). Both implementations
scrape public, unauthenticated HTML pages rather than calling a real API —
there isn't one for either directory — so per Open Risk #5 these are the
same fragility class as any HTML scraper: a layout change on t.me or
Disboard needs a selector update here, not a redesign. Results only ever
feed a review list for the user to manually join; nothing here joins
anything.
"""

import re
from abc import ABC, abstractmethod

import requests
from bs4 import BeautifulSoup

USER_AGENT = "job-search-command-center/1.0 (personal job search tool)"


class GroupDiscoveryProvider(ABC):
    id = None

    @abstractmethod
    def search(self, keyword):
        """Returns a list of {"name": str, "url": str, "description": str, "source": provider id}."""
        raise NotImplementedError


class TelegramDirectoryProvider(GroupDiscoveryProvider):
    """t.me has no real public search endpoint. This checks a single
    candidate channel slug (the keyword, slugified) via its public preview
    page (t.me/s/<slug>) — genuine keyword discovery needs a curated seed
    list of channel usernames from Settings to check one by one, not blind
    guessing against arbitrary keywords. Kept as a narrow, honest building
    block rather than faking a search API that doesn't exist."""
    id = "telegram_directory"

    def search(self, keyword):
        slug = re.sub(r"[^a-zA-Z0-9_]", "", keyword)
        if not slug:
            return []
        url = f"https://t.me/s/{slug}"
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        title_el = soup.select_one(".tgme_channel_info_header_title")
        if not title_el:
            return []
        desc_el = soup.select_one(".tgme_channel_info_description")
        return [{
            "name": title_el.get_text(strip=True),
            "url": url,
            "description": desc_el.get_text(strip=True) if desc_el else "",
            "source": self.id,
        }]


class DiscordDirectoryProvider(GroupDiscoveryProvider):
    """Disboard's public server-search listing page. Selectors below are a
    best-effort guess at Disboard's current markup, not verified live this
    session — expect this to need a touch-up the first time it's actually
    run against production HTML (same caveat as any unverified scraper)."""
    id = "discord_directory"
    SEARCH_URL = "https://disboard.org/search"

    def search(self, keyword):
        try:
            resp = requests.get(
                self.SEARCH_URL, params={"keyword": keyword},
                headers={"User-Agent": USER_AGENT}, timeout=10,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for card in soup.select(".server-search-list .server-info"):
            name_el = card.select_one(".server-name")
            if not name_el:
                continue
            link_el = card.find_parent("a")
            desc_el = card.select_one(".server-description")
            results.append({
                "name": name_el.get_text(strip=True),
                "url": ("https://disboard.org" + link_el["href"]) if link_el and link_el.has_attr("href") else self.SEARCH_URL,
                "description": desc_el.get_text(strip=True) if desc_el else "",
                "source": self.id,
            })
        return results


REGISTRY = {p.id: p() for p in [TelegramDirectoryProvider, DiscordDirectoryProvider]}


def get_provider(provider_id):
    return REGISTRY.get(provider_id)
