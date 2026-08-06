"""Thin wrapper around the Anthropic API — one function per task so prompt/
model changes touch a single call site each. All three are stubs the later
phases wire real callers into; each returns parsed JSON, never raw prose.
"""

import json
import re

import anthropic

from config import load_config

_client = None
_model = None


def _get_client():
    global _client, _model
    if _client is None:
        cfg = load_config()
        _client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"])
        _model = cfg.get("anthropic_model", "claude-sonnet-5")
    return _client, _model


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text!r}")
    return json.loads(match.group(0))


def _call_json(system_prompt, user_content, max_tokens=1024):
    client, model = _get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt + "\n\nRespond with a single JSON object only, no other text.",
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
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
    return _call_json(system_prompt, user_content)


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
    return _call_json(system_prompt, user_content)


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
    return _call_json(system_prompt, user_content)
