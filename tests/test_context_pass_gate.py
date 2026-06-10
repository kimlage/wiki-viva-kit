"""Integrity of the LLM pass gate (findings 12 and 17 of the critical review).

- audit_context_pass_gate: corrupt request JSON becomes an ERROR (not a skip).
- --record-result: validates PROVENANCE (cache_key of an emitted request).

No network; writes only in tmp_path; auditor ROOT monkeypatched.
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


def _load(path_rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_corrupt_request_is_error_not_skipped(tmp_path, monkeypatch):
    # Finding 12: corrupt JSON disarmed the gate silently.
    audit = _load("scripts/wiki_audit.py", "wa_gate")
    req_dir = tmp_path / "data/derived/wiki/extraction-events"
    req_dir.mkdir(parents=True)
    (req_dir / "x-llm-context-request.json").write_text("{ truncado", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    errors: list[str] = []
    audit.audit_context_pass_gate(errors, WikiConfig())
    assert any("unreadable" in e or "JSON" in e for e in errors)


def test_record_result_rejects_unrequested_cache_key(tmp_path, monkeypatch):
    # Finding 17: a fabricated result with a made-up cache_key closed the gate.
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate")

    class _Paths:
        extraction_events = tmp_path / "ee"
        llm_cache = tmp_path / "cache"

    _Paths.extraction_events.mkdir(parents=True)
    _Paths.llm_cache.mkdir(parents=True)
    # An emitted request with a real cache_key.
    (_Paths.extraction_events / "s-llm-context-request.json").write_text(
        json.dumps({"chunks": [{"cache_key": "real-key-1"}]}), encoding="utf-8"
    )

    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"cache_key": "inventado-999"}), encoding="utf-8")
    rc = cp._record_results(_Paths(), str(forged))
    assert rc == 2  # rejected for provenance


def test_record_result_allows_known_cache_key(tmp_path, monkeypatch):
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate2")
    monkeypatch.setattr(cp, "ROOT", tmp_path)  # for out.relative_to(ROOT) in the print

    class _Paths:
        extraction_events = tmp_path / "ee"
        llm_cache = tmp_path / "cache"

    _Paths.extraction_events.mkdir(parents=True)
    _Paths.llm_cache.mkdir(parents=True)
    (_Paths.extraction_events / "s-llm-context-request.json").write_text(
        json.dumps({"chunks": [{"cache_key": "real-key-1"}]}), encoding="utf-8"
    )
    # Valid result with a known cache_key (complete schema).
    result = {
        "cache_key": "real-key-1",
        "source_id": "s",
        "chunk_id": "c",
        "prompt_version": "v1",
        "schema_version": "wiki_llm_context_pass.v2",
        "model_profile": "deep_context",
        "produced_by": "agente",
        "quadrants": {
            "interior_individual": "x",
            "exterior_individual": "x",
            "interior_collective": "x",
            "exterior_collective": "x",
        },
        "claims": [],
        "decisions": [],
        "actions": [],
        "risks": [],
        "uncertainties": [],
        "relationships": [],
        "sensitivity": {"has_pii": False},
    }
    payload = tmp_path / "ok.json"
    payload.write_text(json.dumps(result), encoding="utf-8")
    rc = cp._record_results(_Paths(), str(payload))
    assert rc == 0
