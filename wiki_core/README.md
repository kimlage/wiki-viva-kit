# wiki_core

Deterministic Python core for the wiki viva kit.

This package owns configuration loading, source manifests, extraction, chunking,
indexes, gates, graph checks, page types, score events, quality telemetry,
Wilber/AQAL quadrant contracts, the local web cockpit read/action model and
portable export/import helpers. The web package also owns safe source triage
and proposal-branch Git workflow contracts for the localhost operator API. It
intentionally does not embed an LLM client.

Agent-facing commands live in [scripts](../scripts/README.md).
