"""Cold-start reconstruction smoke test (Track R / Phase 2.4).

The whole product of ingestion -- the SQLite index, the chunks, and the LLM
cache -- is gitignored. So a clean clone (a fresh CI runner, a new machine, a
disaster-recovery checkout) starts with NO derived state. This test is the
executable proof that the derived state is REPRODUCIBLE: from a synthetic source
we ingest, then we DELETE the volatile index exactly like a fresh clone would
lack it, rebuild it from the persisted chunks alone, and confirm a search still
returns a hit.

It is deliberately offline and fast:
  * SO synthetic fixtures -- no PII, no real source, no network.
  * No real LLM call. The pipeline only EMITS the ``-request.json`` context
    packet (the deep read stays delegated to the agent); we never invoke a model,
    so nothing here needs a key or the network. The cold-start property under
    test is the deterministic index reconstruction, not the LLM pass.

Companion policy doc: ``docs/operacao/reconstrucao-estado-derivado.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.index.sqlite import build_index, check_index, search
from wiki_core.ingest import run
from wiki_core.paths import WikiPaths

# Synthetic, PII-free body with a rare needle word ("zarquon") to prove the
# search hit comes from THIS source and not from coincidental fixture text.
NEEDLE = "zarquon"
SYNTHETIC_BODY = (
    f"cold start reconstruction smoke fixture {NEEDLE} deterministic pipeline "
    "rebuild derived index from chunks " * 30
).strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_cold_start_rebuilds_index_from_chunks(tmp_path: Path) -> None:
    """Ingest -> drop the index -> rebuild from chunks -> a search still hits.

    Mirrors a clean clone: the chunks are the persisted intermediate, the SQLite
    index is volatile and must be reconstructible without re-extracting.
    """
    config = WikiConfig(repo_id="cold-start-wiki", owner_label="Cold Start")
    paths = WikiPaths(tmp_path, config)

    # 1. Ingest a synthetic source. The pipeline writes chunks AND the index, and
    #    only emits the LLM context packet (no model is called).
    src = tmp_path / "synthetic-source.md"
    _write(src, "# Synthetic source\n\n" + SYNTHETIC_BODY + "\n")
    result = run(str(src), "system", tmp_path, config)

    assert not result.blocked
    assert result.chunk_count > 0
    assert result.chunks_indexed == result.chunk_count

    chunks_file = paths.chunks / f"{result.source_id}.json"
    db_path = paths.indexes / "wiki.sqlite"
    assert chunks_file.exists(), "chunks are the persisted intermediate we rebuild from"
    assert db_path.exists()

    # The freshly-built index answers the search.
    warm_hits = search(db_path, NEEDLE)
    assert warm_hits, "the warm index should answer before we simulate a cold clone"
    assert {hit["source_id"] for hit in warm_hits} == {result.source_id}

    # 2. Simulate a CLEAN CLONE: the entire volatile index directory is absent
    #    (the index is gitignored; chunks remain because they are the rebuild
    #    input we keep). check_index reports it gone.
    db_path.unlink()
    assert not db_path.exists()
    assert check_index(db_path) == {"exists": False, "chunks": 0, "sources": 0}
    assert search(db_path, NEEDLE) == [], "no index -> no hits (cold state)"

    # 3. RECONSTRUCT the derived state from the chunks directory alone. This is
    #    the documented recovery path (build_index = full rebuild from chunks/).
    rebuild = build_index(paths.chunks, db_path)
    assert rebuild["sources_indexed"] == 1
    assert rebuild["chunks_indexed"] == result.chunk_count
    assert db_path.exists()

    # 4. The rebuilt index is equivalent: the same search returns the same hit.
    cold_hits = search(db_path, NEEDLE)
    assert cold_hits, "rebuilt-from-cold index must answer the same search"
    assert {hit["source_id"] for hit in cold_hits} == {result.source_id}
    assert {hit["chunk_id"] for hit in cold_hits} == {hit["chunk_id"] for hit in warm_hits}

    status = check_index(db_path)
    assert status["exists"] is True
    assert status["sources"] == 1
    assert status["chunks"] == result.chunk_count


def test_cold_start_is_offline_and_self_contained(tmp_path: Path) -> None:
    """Guard rails for the smoke test: nothing leaks outside tmp_path and the
    reconstruction needs no model output (the LLM cache is never required to make
    a search hit)."""
    config = WikiConfig()
    paths = WikiPaths(tmp_path, config)
    src = tmp_path / "synthetic-source.md"
    _write(src, "# Synthetic source\n\n" + SYNTHETIC_BODY + "\n")

    result = run(str(src), "system", tmp_path, config)

    # The LLM cache holds no real result (deep read is delegated, not run here),
    # yet the rebuilt index answers regardless -- proving the search path does not
    # depend on a model having run.
    db_path = paths.indexes / "wiki.sqlite"
    db_path.unlink()
    build_index(paths.chunks, db_path)
    assert search(db_path, NEEDLE), "search must work with an empty LLM cache"

    # Everything the pipeline produced lives under tmp_path (no writes elsewhere).
    derived_root = paths.derived_root
    assert derived_root.is_dir()
    for produced in derived_root.rglob("*"):
        assert tmp_path in produced.resolve().parents or produced.resolve() == tmp_path
    assert result.source_id  # sanity: the run actually happened
