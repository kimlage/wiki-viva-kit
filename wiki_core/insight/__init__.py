"""Minimal insight job: closes the Information -> Insight loop.

Gathers already-existing signals (score events, indexed chunks, memory pages)
about a theme, assembles a context PACKET and emits an insight PROPOSAL for a
human gate. Does NOT write canonical memory and does NOT call a model: the
synthesis is delegated to the agent running the repo (same architecture as the
LLM pass).
"""

from __future__ import annotations

from .job import InsightJobResult, INSIGHT_PROPOSAL_FIELDS, run

__all__ = ["run", "InsightJobResult", "INSIGHT_PROPOSAL_FIELDS"]
