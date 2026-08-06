"""Loads local backend config (API keys, host/port) from config.json.

config.json is gitignored — never commit real secrets. config.example.json
documents the expected keys; copy it to config.json and fill in real values.
"""

import json
import os

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
EXAMPLE_PATH = os.path.join(CONFIG_DIR, "config.example.json")


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"backend/config.json not found. Copy {EXAMPLE_PATH} to {CONFIG_PATH} "
            "and fill in your own values (never commit this file)."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def mask_key(key):
    """Never round-trip a full secret back to the browser — show enough to
    confirm which key is saved (last 4 chars) without exposing it."""
    if not key:
        return ""
    if len(key) <= 4:
        return "••••"
    return "••••" + key[-4:]


def get_llm_settings():
    """Returns {"providers": {provider_id: {"api_key": str}}, "assignments":
    {task_id: {"provider": str, "model": str}}}. Falls back to the legacy
    flat anthropic_api_key/anthropic_model fields for the anthropic provider
    if the new llm.providers.anthropic key was never set — so existing
    config.json files from before multi-provider support keep working
    without a manual edit."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    assignments = dict(llm_cfg.get("assignments") or {})
    if "anthropic" not in providers and cfg.get("anthropic_api_key"):
        providers["anthropic"] = {"api_key": cfg["anthropic_api_key"]}
    return {"providers": providers, "assignments": assignments}


def save_llm_settings(keys=None, assignments=None):
    """keys: {provider_id: api_key} — a non-empty value sets/replaces that
    provider's key, an explicitly empty string clears it, absent keys are
    left untouched. assignments: {task_id: {"provider", "model"}} — merged
    into the existing assignment map."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    existing_assignments = dict(llm_cfg.get("assignments") or {})

    for provider_id, api_key in (keys or {}).items():
        if api_key:
            providers[provider_id] = {"api_key": api_key}
        elif provider_id in providers:
            del providers[provider_id]

    existing_assignments.update(assignments or {})

    cfg["llm"] = {"providers": providers, "assignments": existing_assignments}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
