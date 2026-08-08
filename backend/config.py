"""Loads local backend config (API keys, host/port) from config.json.

config.json is gitignored — never commit real secrets. config.example.json
documents the expected keys; copy it to config.json and fill in real values.

Once the credential vault (backend/vault.py) is initialized, LLM provider
API keys and the Gmail client secret move out of this plaintext file and
into the encrypted vault — see get_llm_settings/save_llm_settings below.
Until a user opts into the vault, this file keeps working exactly as before
(this repo's own config.json already has real working keys in it — the vault
must never silently break that for someone who hasn't set a master password
yet).
"""

import json
import os

import vault

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


def write_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")


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
    without a manual edit.

    Once the vault is initialized, a provider's "api_key" field here is
    populated from the vault (empty string if the vault is locked — callers
    that need the real key for an actual LLM call, not just a masked
    display, should check vault.is_unlocked() themselves and surface a clear
    "unlock the vault" error rather than silently treating locked as
    unconfigured)."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    assignments = dict(llm_cfg.get("assignments") or {})
    if "anthropic" not in providers and cfg.get("anthropic_api_key"):
        providers["anthropic"] = {"api_key": cfg["anthropic_api_key"]}

    if vault.is_initialized():
        for provider_id, meta in providers.items():
            if not meta.get("has_key"):
                continue
            key = vault.get_secret(f"llm:{provider_id}") if vault.is_unlocked() else ""
            providers[provider_id] = dict(meta, api_key=key or "")

    return {"providers": providers, "assignments": assignments}


def save_llm_settings(keys=None, assignments=None):
    """keys: {provider_id: api_key} — a non-empty value sets/replaces that
    provider's key, an explicitly empty string clears it, absent keys are
    left untouched. assignments: {task_id: {"provider", "model"}} — merged
    into the existing assignment map. Only touches the "api_key" field of an
    existing entry — a custom provider's label/base_url/models (see
    save_custom_provider) are left alone.

    Once the vault is initialized, keys are written to the vault (requires
    it to be unlocked — raises vault.VaultLockedError otherwise) and
    config.json only records a non-secret has_key marker."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    existing_assignments = dict(llm_cfg.get("assignments") or {})

    use_vault = vault.is_initialized()
    for provider_id, api_key in (keys or {}).items():
        if use_vault:
            existing = providers.get(provider_id) or {}
            if api_key:
                vault.set_secret(f"llm:{provider_id}", api_key)
                providers[provider_id] = dict(existing, has_key=True)
                providers[provider_id].pop("api_key", None)
            else:
                vault.delete_secret(f"llm:{provider_id}")
                if existing.get("custom"):
                    providers[provider_id] = dict(existing, has_key=False)
                    providers[provider_id].pop("api_key", None)
                elif provider_id in providers:
                    del providers[provider_id]
        elif api_key:
            providers[provider_id] = dict(providers.get(provider_id) or {}, api_key=api_key)
        elif provider_id in providers:
            if providers[provider_id].get("custom"):
                providers[provider_id] = dict(providers[provider_id], api_key="")
            else:
                del providers[provider_id]

    existing_assignments.update(assignments or {})

    cfg["llm"] = {"providers": providers, "assignments": existing_assignments}
    write_config(cfg)


def save_custom_provider(provider_id, label, base_url, models, api_key=""):
    """Adds or replaces a custom (OpenAI-API-compatible) provider — covers
    any vendor not built into llm.PROVIDERS (Groq, DeepSeek, OpenRouter, a
    local Ollama server, etc.) as long as it speaks the OpenAI chat-completions
    shape at a custom base_url. models: list of {"id": str, "label": str}.
    Metadata lives alongside the api_key in the same llm.providers.<id> slot
    built-in providers use for just their key — marked "custom": True so
    llm.get_all_providers() knows to pull label/base_url/models from here
    instead of the hardcoded PROVIDERS table.

    When the vault is initialized, the key itself is stored there (same as
    save_llm_settings) and only a has_key marker stays in config.json."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    existing = providers.get(provider_id) or {}
    entry = {"label": label, "base_url": base_url, "models": models, "custom": True}
    if vault.is_initialized():
        if api_key:
            vault.set_secret(f"llm:{provider_id}", api_key)
            entry["has_key"] = True
        else:
            entry["has_key"] = existing.get("has_key", False)
    else:
        entry["api_key"] = api_key if api_key else existing.get("api_key", "")
    providers[provider_id] = entry
    llm_cfg["providers"] = providers
    cfg["llm"] = llm_cfg
    write_config(cfg)


def delete_custom_provider(provider_id):
    """No-op if provider_id isn't a custom entry — refuses to delete a
    built-in provider's key through this path."""
    cfg = load_config()
    llm_cfg = cfg.get("llm") or {}
    providers = dict(llm_cfg.get("providers") or {})
    if providers.get(provider_id, {}).get("custom"):
        del providers[provider_id]
        llm_cfg["providers"] = providers
        cfg["llm"] = llm_cfg
        write_config(cfg)
        if vault.is_initialized() and vault.is_unlocked():
            vault.delete_secret(f"llm:{provider_id}")
