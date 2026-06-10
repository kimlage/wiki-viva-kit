"""E2E: proves the LLM pass gate closes (red -> green).

Runs the real ingestion chain (`wiki_core.ingest.run`) over a versioned fixture
source, confirms the auditor FAILS while the cache is empty
(required_context_pass) and, after writing the recorded RESULT of the deep read
(versioned fixture, in the format the agent produces), confirms the SAME auditor
PASSES. No network, no model: the "LLM pass" is a recorded, versioned result —
exactly what the skill writes to the cache in production.

Why it exists: raw data and cache (`data/derived/**`) are never versioned, so
the only honest way to prove the loop closing in CI is to replay a recorded
result against the real modules.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.ingest import run
from wiki_core.llm import write_result

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "e2e"
PILOT_SOURCE = FIXTURES / "pilot_source.md"
RESULT_SAMPLE = FIXTURES / "context_pass_result.sample.json"


def _load_wiki_audit():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "wiki_audit_e2e", ROOT / "scripts" / "wiki_audit.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_wiki_audit()


def _request_for(root: Path, source_id: str) -> dict:
    path = root / "data/derived/wiki/extraction-events" / f"{source_id}-llm-context-request.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_context_pass_gate_red_then_green(tmp_path, audit, monkeypatch):
    config = WikiConfig(repo_id="e2e-wiki", owner_label="Piloto E2E")

    # 1. Real ingestion of the fixture source (manifest -> chunks -> index -> request).
    result = run(str(PILOT_SOURCE), "sistema", tmp_path, config)
    assert result.chunk_count >= 1
    assert result.request_path is not None
    assert result.llm_context_status == "pending"

    # The auditor looks at ROOT/data/derived/wiki/...; point it at the ingestion tmp.
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    # 2. RED: empty cache + required_context_pass=true -> auditor fails.
    errors: list[str] = []
    audit.audit_context_pass_gate(errors, config)
    assert errors, "auditor should fail while there is a chunk without a result"
    # The pending-pass message lives in scripts/wiki_audit.py (auditor group); assert
    # on the request-file path it embeds, which is translation-independent.
    assert any("-llm-context-request.json" in e for e in errors)

    # 3. Write the recorded RESULT (fixture) for each chunk of the request, using
    #    the chunk's real cache_key (what the skill does via --record-result).
    template = json.loads(RESULT_SAMPLE.read_text(encoding="utf-8"))
    request = _request_for(tmp_path, result.source_id)
    cache_dir = tmp_path / "data/derived/wiki/llm-cache"
    for chunk in request["chunks"]:
        recorded = dict(template)
        recorded["cache_key"] = chunk["cache_key"]
        recorded["source_id"] = result.source_id
        recorded["chunk_id"] = chunk["chunk_id"]
        # write_result revalidates the schema (filled quadrants, sensitivity...).
        out = write_result(cache_dir, recorded)
        assert out.exists()

    # 4. GREEN: the SAME auditor now passes (no pending chunk).
    errors_after: list[str] = []
    audit.audit_context_pass_gate(errors_after, config)
    assert errors_after == [], f"gate should close green, but: {errors_after}"

    # 5. Coherence: rebuilding the request shows pending=0 and the auditor's
    #    metadata cache (prompt_version/schema_version/cache_key) also passes.
    rebuilt = run(str(PILOT_SOURCE), "sistema", tmp_path, config)
    assert rebuilt.pending_llm_calls == 0
    assert rebuilt.llm_context_status == "recorded"

    meta_errors: list[str] = []
    audit.audit_llm_cache_metadata(meta_errors)
    assert meta_errors == []


def test_recorded_result_fixture_is_schema_valid():
    """The versioned fixture is, by itself, a valid LLM pass result."""
    from wiki_core.llm import validate_result

    template = json.loads(RESULT_SAMPLE.read_text(encoding="utf-8"))
    assert validate_result(template) == []
