from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

import scripts.wiki_new as wiki_new
from wiki_core.frontmatter import parse_frontmatter


KIT_ROOT = Path(__file__).resolve().parents[1]


def _source_authoring_repo(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    (root / "docs/references/templates/wiki").mkdir(parents=True)
    shutil.copy2(KIT_ROOT / "wiki.page-types.yaml", root / "wiki.page-types.yaml")
    shutil.copy2(
        KIT_ROOT / "docs/references/templates/wiki/source.md",
        root / "docs/references/templates/wiki/source.md",
    )
    (root / "wiki.config.yaml").write_text(
        'repo_id: source-authoring-test\n'
        'owner_label: "Synthetic Owner"\n'
        'contexts: system\n',
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("dry_run", [False, True])
def test_wiki_new_source_produces_contract_valid_initial_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    dry_run: bool,
) -> None:
    root = _source_authoring_repo(tmp_path)
    output = "memories/sources/synthetic-calendar-feed.md"
    argv = [
        "wiki_new.py",
        "--type",
        "source",
        "--title",
        "Synthetic calendar feed",
        "--context",
        "system",
        "--output",
        output,
    ]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(sys, "argv", argv)

    assert wiki_new.main() == 0
    rendered = capsys.readouterr().out
    if dry_run:
        assert not (root / output).exists()
    else:
        assert rendered.strip() == output
        rendered = (root / output).read_text(encoding="utf-8")

    values, _body = parse_frontmatter(rendered)
    assert values["owner"] == "synthetic-owner"
    assert values["sync"]["last_status"] == "never"
    assert values["ingestion_state"] == "unread"
    assert values["last_ingested_at"] == ""
    assert values["source_lifecycle"] == {
        "state": "configured",
        "freshness_state": "never_synced",
        "last_attempt_state": "never",
        "pipeline_stage": "configured",
        "pipeline_stage_timestamps": {},
        "adoption_state": "pending",
        "blocked_reason": "",
        "emitted_page_ids": [],
        "emitted_action_ids": [],
        "proposal_ids": [],
        "accepted_ref": "",
        "reviewed_no_change_receipt": "",
        "secret_safe_log_refs": [],
    }
