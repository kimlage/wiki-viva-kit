from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.source_triage import triage_source


def _config() -> WikiConfig:
    return WikiConfig(repo_id="test", default_context="system", contexts=("example",))


def test_triage_source_builds_manifest_and_targets_for_local_file(tmp_path: Path) -> None:
    (tmp_path / "memories/system").mkdir(parents=True)
    (tmp_path / "memories/system/input.md").write_text("# Input\n\nOperational note.\n", encoding="utf-8")
    (tmp_path / "wiki.targets.yaml").write_text(
        """system:
  pages:
    - memories/index.md
    - memories/system/wiki-viva-kit.md
  entities:
    - holon-system
""",
        encoding="utf-8",
    )

    result = triage_source(tmp_path, _config(), "memories/system/input.md", context="system")

    assert result["ok"] is True
    assert result["source_type"] == "markdown"
    assert result["exists"] is True
    assert result["source_id"]
    assert result["risk_flags"] == []
    assert result["targets"]["target_pages"] == ["memories/index.md", "memories/system/wiki-viva-kit.md"]
    assert result["targets"]["target_entities"] == ["holon-system"]
    assert "run_ingest_dry_run" in result["next_steps"]


def test_triage_source_blocks_access_secret_without_leaking_value(tmp_path: Path) -> None:
    raw_secret = "sk-proj-" + ("a" * 42)
    (tmp_path / "source.md").write_text(f"OPENAI_API_KEY={raw_secret}\n", encoding="utf-8")

    result = triage_source(tmp_path, _config(), "source.md", context="system")

    assert result["ok"] is False
    assert result["secret_block"] is True
    assert "secret_block" in result["risk_flags"]
    assert result["findings"][0]["category"] == "secret"
    assert raw_secret not in result["findings"][0]["excerpt"]
    assert result["next_steps"] == ["remove_or_redact_access_secret_before_ingestion", "rerun_source_triage"]


def test_triage_source_reports_missing_and_remote_sources(tmp_path: Path) -> None:
    missing = triage_source(tmp_path, _config(), "missing.md", context="example")
    assert missing["ok"] is True
    assert missing["exists"] is False
    assert "file_not_found" in missing["risk_flags"]
    assert missing["next_steps"] == ["fix_source_path_or_use_remote_url", "rerun_source_triage"]

    remote = triage_source(tmp_path, _config(), "https://example.test/wiki", context="unknown")
    assert remote["ok"] is True
    assert remote["context"] == "system"
    assert remote["source_type"] == "url"
    assert "remote_freshness_required" in remote["risk_flags"]
