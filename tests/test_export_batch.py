"""Tests for the Batches exporter (cost lever, no LLM client).

Verifies that the exporter is deterministic, respects result_exists and produces
the Message Batches API envelope with custom_id = cache_key. No network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths


def _load_exporter():
    spec = importlib.util.spec_from_file_location(
        "wiki_export_batch", ROOT / "scripts" / "wiki_export_batch.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ingest(tmp_path: Path):
    (tmp_path / "wiki.config.yaml").write_text("repo_id: t\nlanguage: en\n", encoding="utf-8")
    config = load_config(tmp_path)
    src = tmp_path / "source.md"
    src.write_text("# Doc\n\n" + ("operational text about ingestion and the gate. " * 80) + "\n", encoding="utf-8")
    result = run(str(src), "system", tmp_path, config, write=True)
    return config, result


def test_export_batch_shape(tmp_path: Path) -> None:
    exporter = _load_exporter()
    config, result = _ingest(tmp_path)
    paths = WikiPaths(tmp_path, config)
    files = list(paths.extraction_events.glob("*-llm-context-request.json"))
    assert files

    reqs = exporter.build_batch_requests(
        files, model="claude-haiku-4-5", max_tokens=1500, include_cached=False
    )
    assert len(reqs) == result.chunk_count
    r0 = reqs[0]
    assert r0["custom_id"], "custom_id must be the chunk cache_key"
    assert r0["params"]["model"] == "claude-haiku-4-5"
    assert r0["params"]["max_tokens"] == 1500
    assert r0["params"]["messages"][0]["role"] == "user"
    assert "CHUNK" in r0["params"]["messages"][0]["content"]


def test_export_batch_deterministic(tmp_path: Path) -> None:
    exporter = _load_exporter()
    config, _ = _ingest(tmp_path)
    paths = WikiPaths(tmp_path, config)
    files = list(paths.extraction_events.glob("*-llm-context-request.json"))
    a = exporter.build_batch_requests(files, model="m", max_tokens=10, include_cached=False)
    b = exporter.build_batch_requests(files, model="m", max_tokens=10, include_cached=False)
    assert a == b


def test_export_batch_custom_id_matches_request(tmp_path: Path) -> None:
    import json

    exporter = _load_exporter()
    config, _ = _ingest(tmp_path)
    paths = WikiPaths(tmp_path, config)
    files = list(paths.extraction_events.glob("*-llm-context-request.json"))
    keys = set()
    for f in files:
        for chunk in json.loads(f.read_text(encoding="utf-8"))["chunks"]:
            keys.add(chunk["cache_key"])
    reqs = exporter.build_batch_requests(files, model="m", max_tokens=10, include_cached=False)
    assert all(r["custom_id"] in keys for r in reqs)


def test_export_batch_warns_on_invalid_request_json(tmp_path: Path, capsys) -> None:
    import json

    exporter = _load_exporter()
    bad = tmp_path / "bad-llm-context-request.json"
    bad.write_text("{not valid json", encoding="utf-8")
    good = tmp_path / "good-llm-context-request.json"
    good.write_text(
        json.dumps({"prompt": "p", "chunks": [{"cache_key": "k1", "chunk_id": "c1", "text": "t"}]}),
        encoding="utf-8",
    )
    reqs = exporter.build_batch_requests([bad, good], model="m", max_tokens=10, include_cached=False)
    # the corrupt file is skipped WITH a stderr warning; the good one still exports
    assert [r["custom_id"] for r in reqs] == ["k1"]
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "bad-llm-context-request.json" in err
