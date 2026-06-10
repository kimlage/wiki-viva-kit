"""Tests for the insight job (Information -> Insight).

Builds a minimal repo in tmp_path (via the ingestion orchestrator, which
generates index + score-event), runs the insight job and ensures it GATHERS
evidence, EMITS packet + proposal in data/derived (gitignored) and NEVER writes
canonical memory. No network; nothing is written outside tmp_path.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.ingest import run as ingest_run
from wiki_core.insight import run as insight_run

THEME = "gate de honestidade"
TEXT = ("o " + THEME + " mantem a wiki viva honesta e rastreavel ") * 60
DATE = dt.date(2026, 6, 9)


def _seed(tmp_path: Path) -> WikiConfig:
    config = WikiConfig(repo_id="insight-wiki", owner_label="Dono")
    src = tmp_path / "fonte.md"
    src.write_text("# Tema\n\n" + TEXT + "\n", encoding="utf-8")
    # generates manifest -> chunks -> index -> score-event
    ingest_run(str(src), "sistema", tmp_path, config)
    page = tmp_path / "memorias" / "sistema" / "nota.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(f"# Nota\n\nUma nota que cita o {THEME} no contexto sistema.\n", encoding="utf-8")
    return config


def test_insight_job_gathers_and_emits(tmp_path: Path) -> None:
    config = _seed(tmp_path)
    result = insight_run(THEME, "sistema", tmp_path, config, date=DATE)

    # Gathered real evidence.
    assert result.event_count >= 1  # ingestar_fonte_valida
    assert result.chunk_count >= 1  # FTS found the theme
    assert result.page_count >= 1   # the note cites the theme

    # Emitted packet + proposal, both in data/derived (gitignored), never memory.
    assert result.packet_path and result.packet_path.startswith("data/derived/")
    assert result.proposal_path and result.proposal_path.startswith("data/derived/")
    assert (tmp_path / result.packet_path).exists()
    assert (tmp_path / result.proposal_path).exists()

    packet = json.loads((tmp_path / result.packet_path).read_text(encoding="utf-8"))
    assert packet["kind"] == "insight_request"
    assert packet["theme"] == THEME
    assert packet["evidence"]["chunks"], "the packet must carry the gathered chunks"
    assert "proposal_fields" in packet

    # Honesty: the proposal starts as a candidate, not canonical truth.
    proposal = (tmp_path / result.proposal_path).read_text(encoding="utf-8")
    assert "status_epistemologico: candidato" in proposal


def test_insight_job_never_writes_canonical_memory(tmp_path: Path) -> None:
    config = _seed(tmp_path)
    before = {p.relative_to(tmp_path).as_posix() for p in (tmp_path / "memorias").rglob("*.md")}
    insight_run(THEME, "sistema", tmp_path, config, date=DATE)
    after = {p.relative_to(tmp_path).as_posix() for p in (tmp_path / "memorias").rglob("*.md")}
    assert before == after, "the insight job must not create/alter memory pages"


def test_insight_job_dry_run_writes_nothing(tmp_path: Path) -> None:
    config = WikiConfig()
    result = insight_run("tema qualquer", "sistema", tmp_path, config, write=False)
    assert result.packet_path is None
    assert result.proposal_path is None
    assert not (tmp_path / "data/derived/wiki/insight-jobs").exists()
