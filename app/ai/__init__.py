"""
The AI-facing boundary layer: read-only tools a future agent will call,
each a thin wrapper around a Backend Service — see app/ai/lead_context_tool.py
for the first one. Nothing here calls an LLM; this package only exists so
an agent (once one exists) has a well-defined, deterministic surface to
call instead of touching repositories or the database directly.

Required flow: AI Agent -> AI Tool (here) -> Backend Service -> Repository -> Supabase.
"""
