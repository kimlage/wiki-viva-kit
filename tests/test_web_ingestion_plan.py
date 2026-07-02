from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.ingestion_plan import build_ingestion_plan, run_ingestion_step


def _config() -> WikiConfig:
    return WikiConfig(repo_id="test", default_context="system", contexts=("example",))


def test_ingestion_plan_exposes_pipeline_and_commands(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text("# Source\n\nSynthetic note.\n", encoding="utf-8")

    plan = build_ingestion_plan(tmp_path, _config(), "source.md", context="system")

    assert plan["ok"] is True
    assert plan["source_id"]
    stages = {stage["id"]: stage for stage in plan["stages"]}
    assert stages["source_triage"]["status"] == "complete"
    assert stages["proposal_preview"]["command"] == [
        "python3",
        "scripts/wiki_new_ingest.py",
        "--source",
        "source.md",
        "--context",
        "system",
        "--dry-run",
    ]
    assert stages["ingest_dry_run"]["status"] == "ready"
    assert stages["proposal_write"]["status"] == "waiting"
    assert stages["llm_request_emit"]["writes"] is True


def test_ingestion_plan_blocks_secret_source(tmp_path: Path) -> None:
    raw_secret = "sk-proj-" + ("b" * 42)
    (tmp_path / "source.md").write_text(f"OPENAI_API_KEY={raw_secret}\n", encoding="utf-8")

    plan = build_ingestion_plan(tmp_path, _config(), "source.md", context="system")

    assert plan["ok"] is False
    assert plan["next_blocked_stage"]["id"] == "source_triage"
    assert plan["triage"]["secret_block"] is True
    assert raw_secret not in str(plan)


def test_ingestion_write_step_is_dry_run_by_default(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text("# Source\n", encoding="utf-8")

    result = run_ingestion_step(tmp_path, _config(), "source.md", "system", "proposal_write", dry_run=True)

    assert result["ok"] is True
    assert result["results"][0]["dry_run"] is True
    assert result["results"][0]["stdout"] == "dry run: command not executed"


def test_ingestion_step_rejects_unknown_step(tmp_path: Path) -> None:
    result = run_ingestion_step(tmp_path, _config(), "source.md", "system", "unsafe", dry_run=True)

    assert result["ok"] is False
    assert result["error"] == "unknown ingestion step"
