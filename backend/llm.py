"""Multi-provider LLM wrapper — one function per task so prompt/model changes
touch a single call site each. Each task's provider+model is configurable at
runtime (Setup > gear icon), stored via config.save_llm_settings. Every task
function returns parsed JSON, never raw prose.

Only official API keys are supported. A ChatGPT Plus / Claude Pro / Gemini
Advanced *subscription login* has no programmatic API to call — there is no
"punch in your consumer login" integration path, by design (see CLAUDE.md's
existing decision that this app uses a real Anthropic API key, not a
claude.ai login).
"""

import json
import re

import db
import vault
from config import get_llm_settings

# Curated "popular model" defaults per provider — always paired with a free-
# text override in the UI, since this list will drift as new models ship.
#
# price_in/price_out are USD per 1M tokens, used only to estimate $ cost for
# the usage tracker (backend/db.py's llm_usage table). Anthropic's prices are
# verified against Anthropic's own current published pricing. OpenAI's and
# Google's are deliberately left as None (not independently verified this
# session) — the usage tracker still logs real token counts for those calls,
# it just won't total a $ estimate for them until real prices are filled in.
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic (Claude)",
        "models": [
            {"id": "claude-opus-4-8", "label": "Claude Opus 4.8 (most capable)", "price_in": 5.00, "price_out": 25.00},
            # $2/$10 is Sonnet 5's introductory pricing through 2026-08-31; reverts to $3/$15 after.
            {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (balanced, default)", "price_in": 2.00, "price_out": 10.00},
            {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5 (fastest / cheapest)", "price_in": 1.00, "price_out": 5.00},
        ],
    },
    "openai": {
        "label": "OpenAI (GPT)",
        "models": [
            {"id": "gpt-5", "label": "GPT-5", "price_in": None, "price_out": None},
            {"id": "gpt-5-mini", "label": "GPT-5 mini", "price_in": None, "price_out": None},
            {"id": "gpt-4o", "label": "GPT-4o", "price_in": None, "price_out": None},
        ],
    },
    "google": {
        "label": "Google (Gemini)",
        "models": [
            {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "price_in": None, "price_out": None},
            {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "price_in": None, "price_out": None},
        ],
    },
}

TASKS = {
    "extract_resume_profile": {
        "label": "Extract resume profile",
        "description": "Reads your resume text and produces skills, industries, "
                        "job-posting keywords, and a summary.",
    },
    "triage_message": {
        "label": "Triage inbound leads",
        "description": "Reads each Telegram/Slack/manual-capture message and decides "
                        "whether it's a real hiring opportunity worth following up on.",
    },
    "draft_cold_email": {
        "label": "Draft cold outreach email",
        "description": "Writes the subject and body of the automated email sent to a contact.",
    },
    "classify_sentiment": {
        "label": "Classify reply sentiment",
        "description": "Reads a reply to a cold outreach email and flags a negative/opt-out "
                        "response for automatic suppression (decision #20).",
    },
}

DEFAULT_ASSIGNMENT = {"provider": "anthropic", "model": "claude-sonnet-5"}


def get_all_providers():
    """The static PROVIDERS table merged with any user-added custom
    (OpenAI-API-compatible) providers stored in config.json's
    llm.providers.<id> — those carry their own label/models/base_url since
    they aren't hardcoded here (see config.save_custom_provider)."""
    settings = get_llm_settings()
    merged = dict(PROVIDERS)
    for provider_id, meta in settings["providers"].items():
        if meta.get("custom"):
            merged[provider_id] = {
                "label": meta.get("label", provider_id),
                "models": meta.get("models", []),
                "base_url": meta.get("base_url"),
                "custom": True,
            }
    return merged


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        # No closing "}" anywhere usually means the response was cut off before
        # finishing — most often the max_tokens budget for this task was too
        # low for how much the model had to say (raise it in the relevant
        # task function below), not a formatting problem with the response.
        raise ValueError(
            "LLM response appears to have been cut off before finishing (no closing '}' found — "
            f"likely hit the max_tokens limit). Raw response: {text!r}"
        )
    return json.loads(match.group(0))


def _call_anthropic(api_key, model, system_prompt, user_content, max_tokens):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response.usage.input_tokens, response.usage.output_tokens


def _call_openai(api_key, model, system_prompt, user_content, max_tokens, base_url=None):
    import openai
    client = openai.OpenAI(api_key=api_key, base_url=base_url) if base_url else openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    text = response.choices[0].message.content or ""
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0
    return text, input_tokens, output_tokens


def _call_google(api_key, model, system_prompt, user_content, max_tokens):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
        ),
    )
    text = response.text or ""
    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) or 0 if usage else 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0 if usage else 0
    return text, input_tokens, output_tokens


_DISPATCH = {"anthropic": _call_anthropic, "openai": _call_openai, "google": _call_google}


def _estimate_cost(provider, model, input_tokens, output_tokens):
    """None when this provider/model has no verified per-token pricing in
    PROVIDERS — see the module docstring above PROVIDERS. Custom providers
    never have price_in/price_out set, so this always returns None for them,
    same as OpenAI/Google's currently-unpriced models."""
    models = get_all_providers().get(provider, {}).get("models", [])
    meta = next((m for m in models if m["id"] == model), None)
    if not meta or meta.get("price_in") is None or meta.get("price_out") is None:
        return None
    return (input_tokens * meta["price_in"] + output_tokens * meta["price_out"]) / 1_000_000


def get_monthly_spend_cap():
    """0/None means disabled (default) — the plan flags this as
    "recommended, not yet confirmed" (Open Risk #6), so it never silently
    blocks anything until a user explicitly sets a cap > 0 in Settings."""
    raw = db.get_setting("monthly_spend_cap_usd")
    return float(raw) if raw else 0


def save_monthly_spend_cap(cap_usd):
    db.set_setting("monthly_spend_cap_usd", str(cap_usd))


def _call_json(system_prompt, user_content, task, max_tokens=1024):
    cap = get_monthly_spend_cap()
    if cap > 0 and db.get_monthly_llm_cost() >= cap:
        raise RuntimeError(
            f"Monthly LLM spend cap (${cap:.2f}) reached — raise it in Settings to keep using LLM features this month."
        )

    settings = get_llm_settings()
    assignment = settings["assignments"].get(task) or DEFAULT_ASSIGNMENT
    provider = assignment["provider"]
    model = assignment["model"]

    provider_settings = settings["providers"].get(provider) or {}
    api_key = provider_settings.get("api_key")
    if not api_key:
        provider_label = get_all_providers().get(provider, {}).get("label", provider)
        if provider_settings.get("has_key") and vault.is_initialized() and not vault.is_unlocked():
            raise RuntimeError(f"Vault is locked — unlock it to use {provider_label}.")
        raise RuntimeError(
            f"No API key configured for {provider_label}. Add one in Setup > LLM settings."
        )

    system_with_json_instruction = system_prompt + "\n\nRespond with a single JSON object only, no other text."

    if provider_settings.get("custom"):
        # Custom providers are always OpenAI-API-compatible, called at their
        # own base_url — see config.save_custom_provider.
        text, input_tokens, output_tokens = _call_openai(
            api_key, model, system_with_json_instruction, user_content, max_tokens,
            base_url=provider_settings.get("base_url"),
        )
    else:
        call_fn = _DISPATCH.get(provider)
        if not call_fn:
            raise RuntimeError(f"Unknown LLM provider: {provider}")
        text, input_tokens, output_tokens = call_fn(api_key, model, system_with_json_instruction, user_content, max_tokens)

    try:
        cost = _estimate_cost(provider, model, input_tokens, output_tokens)
        db.log_llm_usage(task, provider, model, input_tokens, output_tokens, cost)
    except Exception:
        pass  # usage tracking must never break the actual feature it's tracking

    return _extract_json(text)


def extract_resume_profile(resume_text):
    """Returns {"skills": [...], "industries": [...], "keywords": [...], "summary": "..."}"""
    system_prompt = (
        "You extract a structured job-search profile from a resume: relevant skills, "
        "industry clusters the candidate is a fit for, and specific keywords a job-posting "
        "filter should match on (job titles, tools, specialties). Be concrete and specific "
        "to this resume, not generic."
    )
    user_content = (
        "Resume:\n\n" + resume_text + "\n\n"
        'Return JSON: {"skills": [...], "industries": [...], "keywords": [...], "summary": "1-2 sentences"}'
    )
    # Detailed resumes can legitimately produce dozens of skills/industries/
    # keywords — the previous 1024-token default was too tight and silently
    # truncated the JSON mid-response (see _extract_json's truncation error).
    return _call_json(system_prompt, user_content, "extract_resume_profile", max_tokens=4096)


def triage_message(text, source):
    """Returns {"is_opportunity": bool, "point_of_contact": str|null, "reason": "..."}"""
    system_prompt = (
        "You triage a single chat message from a job-search-related community to decide "
        "whether it describes a hiring opportunity or names a point of contact worth "
        "following up with. Be conservative — most messages are noise."
    )
    user_content = (
        f"Source: {source}\nMessage:\n\n{text}\n\n"
        'Return JSON: {"is_opportunity": bool, "point_of_contact": string or null, "reason": "1 sentence"}'
    )
    return _call_json(system_prompt, user_content, "triage_message")


def classify_sentiment(reply_text):
    """Returns {"sentiment": "positive"|"neutral"|"negative", "reason": "..."}.
    "negative" drives auto-suppression (decision #20) — kept deliberately
    narrow (explicit opt-out/unsubscribe/hostile) so a merely lukewarm or
    ambiguous reply never silently suppresses a real contact."""
    system_prompt = (
        "You classify a reply to a cold outreach job-search email. 'negative' means an explicit "
        "opt-out, unsubscribe request, or a clearly hostile/annoyed response — be conservative, "
        "only use this for unambiguous cases. 'positive' means genuine interest or a concrete next "
        "step. 'neutral' covers everything else (auto-reply, out-of-office, unclear, noncommittal)."
    )
    user_content = (
        f"Reply:\n\n{reply_text}\n\n"
        'Return JSON: {"sentiment": "positive"|"neutral"|"negative", "reason": "1 sentence"}'
    )
    return _call_json(system_prompt, user_content, "classify_sentiment")


def draft_cold_email(contact, context):
    """contact: dict with company/name/role. context: dict with resume summary + lead/posting info.
    Returns {"subject": "...", "body": "..."}"""
    system_prompt = (
        "You draft a short, specific cold outreach email from a candidate to a point of "
        "contact at a company, referencing the concrete opportunity context given. No "
        "generic filler, no over-selling. Plain text body, no markdown."
    )
    user_content = (
        f"Contact: {json.dumps(contact, ensure_ascii=False)}\n"
        f"Context: {json.dumps(context, ensure_ascii=False)}\n\n"
        'Return JSON: {"subject": "...", "body": "..."}'
    )
    return _call_json(system_prompt, user_content, "draft_cold_email")
