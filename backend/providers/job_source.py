"""JobSourceProvider — thin adapter over scripts/fetch_postings.py's
per-ATS fetchers (Greenhouse/Lever/SmartRecruiters), so Phase 1's postings
sync and future niche-API sources can be iterated uniformly (plan §4).
scripts/fetch_postings.py itself stays untouched and stdlib-only — GitHub
Actions runs it unattended (see CLAUDE.md) — this module imports it as a
module, it doesn't fork or duplicate its logic.
"""

import importlib.util
import os
from abc import ABC, abstractmethod

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FETCH_POSTINGS_PATH = os.path.join(REPO_ROOT, "scripts", "fetch_postings.py")


def _load_fetch_postings_module():
    spec = importlib.util.spec_from_file_location("fetch_postings", _FETCH_POSTINGS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_fp = _load_fetch_postings_module()


class JobSourceProvider(ABC):
    id = None

    @abstractmethod
    def fetch(self, slug):
        """Returns a list of raw posting dicts: {id, title, location,
        description, url, contract_type} — same shape fetch_postings.py's
        fetchers already produce, pre-filtering."""
        raise NotImplementedError


class GreenhouseProvider(JobSourceProvider):
    id = "greenhouse"

    def fetch(self, slug):
        return _fp.fetch_greenhouse(slug)


class LeverProvider(JobSourceProvider):
    id = "lever"

    def fetch(self, slug):
        return _fp.fetch_lever(slug)


class SmartRecruitersProvider(JobSourceProvider):
    id = "smartrecruiters"

    def fetch(self, slug):
        return _fp.fetch_smartrecruiters(slug)


REGISTRY = {p.id: p() for p in [GreenhouseProvider, LeverProvider, SmartRecruitersProvider]}


def get_provider(ats_id):
    return REGISTRY.get(ats_id)


def filter_postings(raw_postings, company):
    """Reuses fetch_postings.py's own include/exclude/location filtering
    logic verbatim — the plan's regex-based filter isn't being replaced,
    only fed through the provider abstraction (scoring in backend/scoring.py
    is a separate, additive rank on top of what already passes this filter)."""
    return _fp.filter_postings(raw_postings, company)
