"""Integrity of the LLM pass gate (findings 12 and 17 of the critical review).

- audit_context_pass_gate: corrupt request JSON becomes an ERROR (not a skip);
  ORPHAN requests (query- prefix or chunks file gone) are skipped with an
  aggregated warning instead of locking the gate red permanently.
- --record-result: validates PROVENANCE (cache_key of an emitted request),
  including when there is NO request on disk at all (no silent escape).
- write_result: cache_key must be a sha256 hex digest (path traversal block).

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
from wiki_core.llm.context_pass import write_result

HEX_KEY = "a" * 64


def _load(path_rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _seed_request(tmp_path, source_id: str, cache_keys: list[str], *, with_chunks: bool = True):
    req_dir = tmp_path / "data/derived/wiki/extraction-events"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / f"{source_id}-llm-context-request.json").write_text(
        json.dumps(
            {"source_id": source_id, "chunks": [{"cache_key": k} for k in cache_keys]}
        ),
        encoding="utf-8",
    )
    if with_chunks:
        chunks_dir = tmp_path / "data/derived/wiki/chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        (chunks_dir / f"{source_id}.json").write_text(
            json.dumps({"chunks": []}), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# audit_context_pass_gate
# ---------------------------------------------------------------------------


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


def test_pending_request_with_live_chunks_is_error(tmp_path, monkeypatch):
    # A live source (chunks file on disk) with a pending chunk keeps failing.
    audit = _load("scripts/wiki_audit.py", "wa_gate_live")
    _seed_request(tmp_path, "live-source", ["pending-key"], with_chunks=True)
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_context_pass_gate(errors, WikiConfig(), warnings)
    assert any("pending LLM pass" in e for e in errors)
    assert warnings == []


def test_orphan_query_request_is_warning_not_error(tmp_path, monkeypatch):
    # source_id with the query- prefix never has a chunks file: skipping it
    # avoids a permanently red gate; it is reported as an aggregated warning.
    audit = _load("scripts/wiki_audit.py", "wa_gate_query")
    _seed_request(tmp_path, "query-abc123def456", ["pending-key"], with_chunks=False)
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_context_pass_gate(errors, WikiConfig(), warnings)
    assert errors == []
    assert len(warnings) == 1
    assert "orphan" in warnings[0]
    assert "query-abc123def456" in warnings[0]


def test_orphan_gcd_source_request_is_warning_not_error(tmp_path, monkeypatch):
    # The chunks file data/derived/wiki/chunks/<source_id>.json no longer exists
    # (source re-edited/gc'd): the stale request must not lock the gate.
    audit = _load("scripts/wiki_audit.py", "wa_gate_gc")
    _seed_request(tmp_path, "gone-source", ["pending-key"], with_chunks=False)
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_context_pass_gate(errors, WikiConfig(), warnings)
    assert errors == []
    assert len(warnings) == 1
    assert "orphan" in warnings[0] and "gone-source" in warnings[0]


def test_orphan_warnings_are_aggregated(tmp_path, monkeypatch):
    # Multiple orphans produce ONE aggregated warning, not one per request.
    audit = _load("scripts/wiki_audit.py", "wa_gate_agg")
    _seed_request(tmp_path, "query-aaa", ["k1"], with_chunks=False)
    _seed_request(tmp_path, "lost-source", ["k2"], with_chunks=False)
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_context_pass_gate(errors, WikiConfig(), warnings)
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0].startswith("2 orphan")


# ---------------------------------------------------------------------------
# --record-result provenance
# ---------------------------------------------------------------------------


def _paths_stub(tmp_path):
    class _Paths:
        extraction_events = tmp_path / "ee"
        llm_cache = tmp_path / "cache"

    _Paths.extraction_events.mkdir(parents=True, exist_ok=True)
    _Paths.llm_cache.mkdir(parents=True, exist_ok=True)
    return _Paths()


def _complete_result(key: str) -> dict:
    return {
        "cache_key": key,
        "source_id": "s",
        "chunk_id": "c",
        "prompt_version": "v1",
        "schema_version": "wiki_llm_context_pass.v2",
        "model_profile": "deep_context",
        "produced_by": "agent",
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


def test_record_result_rejects_unrequested_cache_key(tmp_path, monkeypatch):
    # Finding 17: a fabricated result with a made-up cache_key closed the gate.
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate")
    paths = _paths_stub(tmp_path)
    # An emitted request with a real cache_key.
    (paths.extraction_events / "s-llm-context-request.json").write_text(
        json.dumps({"chunks": [{"cache_key": "real-key-1"}]}), encoding="utf-8"
    )

    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"cache_key": "made-up-999"}), encoding="utf-8")
    rc = cp._record_results(paths, str(forged))
    assert rc == 2  # rejected for provenance


def test_record_result_rejects_when_no_request_on_disk(tmp_path, capsys):
    # Zero requests on disk must REJECT (the old `and known` guard let any
    # result through when extraction-events was empty) with guidance to use
    # --allow-unrequested for the legitimate cases.
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate_empty")
    paths = _paths_stub(tmp_path)  # extraction_events exists but is empty

    payload = tmp_path / "res.json"
    payload.write_text(json.dumps(_complete_result(HEX_KEY)), encoding="utf-8")
    rc = cp._record_results(paths, str(payload))
    assert rc == 2
    err = capsys.readouterr().err
    assert "no emitted context request found on disk" in err
    assert "--allow-unrequested" in err


def test_record_result_allow_unrequested_bypasses_provenance(tmp_path, monkeypatch):
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate_allow")
    monkeypatch.setattr(cp, "ROOT", tmp_path)  # for out.relative_to(ROOT) in the print
    paths = _paths_stub(tmp_path)  # no request on disk

    payload = tmp_path / "res.json"
    payload.write_text(json.dumps(_complete_result(HEX_KEY)), encoding="utf-8")
    rc = cp._record_results(paths, str(payload), allow_unrequested=True)
    assert rc == 0
    assert (paths.llm_cache / f"{HEX_KEY}.json").exists()


def test_record_result_allows_known_cache_key(tmp_path, monkeypatch):
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate2")
    monkeypatch.setattr(cp, "ROOT", tmp_path)  # for out.relative_to(ROOT) in the print
    paths = _paths_stub(tmp_path)
    (paths.extraction_events / "s-llm-context-request.json").write_text(
        json.dumps({"chunks": [{"cache_key": HEX_KEY}]}), encoding="utf-8"
    )
    # Valid result with a known cache_key (complete schema).
    payload = tmp_path / "ok.json"
    payload.write_text(json.dumps(_complete_result(HEX_KEY)), encoding="utf-8")
    rc = cp._record_results(paths, str(payload))
    assert rc == 0


def test_emitted_cache_keys_warns_on_corrupt_request(tmp_path, capsys):
    # A corrupt request shrinks the known-key set: surfaced on stderr, not silent.
    cp = _load("scripts/wiki_llm_context_pass.py", "cp_gate_corrupt")
    paths = _paths_stub(tmp_path)
    (paths.extraction_events / "good-llm-context-request.json").write_text(
        json.dumps({"chunks": [{"cache_key": HEX_KEY}]}), encoding="utf-8"
    )
    (paths.extraction_events / "bad-llm-context-request.json").write_text(
        "{ truncated", encoding="utf-8"
    )
    keys = cp._emitted_cache_keys(paths)
    assert keys == {HEX_KEY}
    err = capsys.readouterr().err
    assert "WARN" in err and "bad-llm-context-request.json" in err


# ---------------------------------------------------------------------------
# write_result: cache_key shape (path traversal block)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        "../../memorias/sistema/log",  # traversal
        "made-up-999",  # not hex
        "A" * 64,  # uppercase hex is not what cache_key() produces
        "a" * 63,  # wrong length
        "",
    ],
)
def test_write_result_rejects_non_sha256_cache_key(tmp_path, bad_key):
    with pytest.raises(ValueError, match="cache_key"):
        write_result(tmp_path / "cache", _complete_result(bad_key))
    # Nothing escaped the cache dir (nor was written at all).
    assert not (tmp_path / "cache").exists()


def test_write_result_accepts_sha256_cache_key(tmp_path):
    out = write_result(tmp_path / "cache", _complete_result(HEX_KEY))
    assert out == tmp_path / "cache" / f"{HEX_KEY}.json"
    assert out.exists()
