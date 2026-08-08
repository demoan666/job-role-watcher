"""Provider adapters — job source, enrichment, email, group discovery.

Same shape as backend/llm.py's provider dispatch (decision #8): every
external dependency category gets a small ABC and one or more
implementations behind it, so a new provider is additive, never a rewrite
of the call sites that use it.
"""
