from __future__ import annotations

import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.briefs import (
    BriefStore,
    compose_brief,
    normalize_spec,
    sanitize_theme,
)
from wiki_core.web.snapshot import build_snapshot

SNAPSHOT_AT = "2026-07-01"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> WikiConfig:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    _write(root / "AGENTS.md", "# Agents\nFollow the hard rules.\n")
    _write(root / "wiki.config.yaml", "repo_id: brief-test\ndefault_context: system\n")
    _write(
        root / "memories/index.md",
        """---
page_id: root
page_type: root_index
title: "Root"
context: system
visibility: private_self
updated_at: 2026-06-20
stale_after_days: 60
---

# Root

Links to [Finance](finance/index.md).
""",
    )
    _write(
        root / "memories/finance/index.md",
        """---
page_id: finance-hub
page_type: context_hub
title: "Finance hub"
context: finance
visibility: private_self
updated_at: 2026-01-01
stale_after_days: 30
moc_parent: memories/index.md
---

# Finance hub

The stale hub with no cited source. Body text to ground the brief.
""",
    )
    _write(
        root / "memories/finance/note.md",
        """---
page_id: finance-note
page_type: context_note
title: "Finance note"
context: finance
visibility: private_self
updated_at: 2026-06-25
stale_after_days: 30
moc_parent: memories/finance/index.md
---

# Finance note

A content note with no source_refs — an evidence candidate.
""",
    )
    return load_config(root)


def _snapshot(root: Path, config: WikiConfig) -> dict:
    return build_snapshot(root, config, mode="local_operator", generated_at=SNAPSHOT_AT)


def test_sanitize_theme() -> None:
    assert sanitize_theme("Refresh Finance!!") == "refresh-finance"
    assert sanitize_theme("") == "update"
    assert sanitize_theme("", fallback="ingest") == "ingest"


def test_normalize_spec_defaults() -> None:
    norm = normalize_spec({})
    assert norm["mission_kind"] is None
    assert norm["materialize"] == "refs"
    assert norm["grounding"]["page_ids"] == []
    bad = normalize_spec({"mission_kind": "nonsense", "materialize": "weird"})
    assert bad["mission_kind"] is None
    assert bad["materialize"] == "refs"


def test_compose_has_five_sections_and_provenance(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    result = compose_brief(
        tmp_path,
        config,
        snapshot,
        spec={"mission_kind": "refresh", "theme": "refresh finance", "grounding": {"page_ids": ["finance-hub"]},
              "intent": "re-verify the numbers"},
    )
    text = result["text"]
    for header in (
        "## 1 · Conventions",
        "## 2 · State of the wiki",
        "## 3 · Targets",
        "## 4 · Operator intent",
        "## 5 · Output contract",
    ):
        assert header in text, header
    # Evidence cites its source and matches real state.
    assert "freshness_state=stale" in text
    assert "_[pages.json / freshness.json]_" in text
    assert "re-verify the numbers" in text
    # Contract pins the branch prefix + theme.
    assert "wiki/refresh-finance" in text
    # Header cites the SNAPSHOT date, not wall-clock.
    assert SNAPSHOT_AT in text


def test_compose_is_deterministic(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    spec = {"mission_kind": "refresh", "theme": "x", "grounding": {"page_ids": ["finance-hub"]}}
    a = compose_brief(tmp_path, config, snapshot, spec=spec)
    b = compose_brief(tmp_path, config, snapshot, spec=spec)
    assert a["text"] == b["text"]
    assert a["brief_sha"] == b["brief_sha"]
    assert a["size_chars"] == len(a["text"])


def test_compose_overdue_days(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    result = compose_brief(tmp_path, config, snapshot, spec={"grounding": {"page_ids": ["finance-hub"]}})
    # finance-hub: updated 2026-01-01, window 30d, snapshot 2026-07-01 → ~121d past.
    assert "past its window" in result["text"]


def test_compose_state_report_missions(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    result = compose_brief(
        tmp_path,
        config,
        snapshot,
        spec={"mission_kind": "state", "grounding": {"state_report": {"scope": "missions", "limit": 5}}},
    )
    text = result["text"]
    assert "Top" in text and "problem page(s)" in text
    assert "finance-hub" in text
    assert len(result["context_pages"]) >= 1


def test_compose_materialize_full_embeds_conventions(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    refs = compose_brief(tmp_path, config, snapshot, spec={"materialize": "refs", "grounding": {"page_ids": ["finance-hub"]}})
    full = compose_brief(tmp_path, config, snapshot, spec={"materialize": "full", "grounding": {"page_ids": ["finance-hub"]}})
    assert "Follow the hard rules." not in refs["text"]
    assert "Follow the hard rules." in full["text"]  # AGENTS.md embedded
    assert full["size_chars"] > refs["size_chars"]


def test_compose_target_paths_collected(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    result = compose_brief(tmp_path, config, snapshot, spec={"grounding": {"page_ids": ["finance-hub", "finance-note"]}})
    assert "memories/finance/index.md" in result["target_paths"]
    assert "memories/finance/note.md" in result["target_paths"]


def test_store_roundtrip_and_edit(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    composed = compose_brief(tmp_path, config, snapshot, spec={"grounding": {"page_ids": ["finance-hub"]}})
    store = BriefStore(tmp_path, config)
    saved = store.save_new(composed)
    brief_id = saved["brief_id"]
    assert saved["status"] == "draft"
    assert saved["brief_sha"] == composed["brief_sha"]
    # target hashes captured for the launch-time staleness guard.
    assert saved["target_hashes"]["memories/finance/index.md"] != "absent"

    fetched = store.get(brief_id)
    assert fetched is not None and fetched["text"] == composed["text"]

    listed = store.list()
    assert any(r["brief_id"] == brief_id for r in listed)

    edited = store.update_text(brief_id, composed["text"] + "\n\nEXTRA LINE\n")
    assert edited is not None and edited.get("ok") is not False
    assert edited["brief_sha"] != composed["brief_sha"]
    assert "EXTRA LINE" in store.get(brief_id)["text"]


def test_store_edit_rejected_when_not_draft(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    snapshot = _snapshot(tmp_path, config)
    composed = compose_brief(tmp_path, config, snapshot, spec={"grounding": {"page_ids": ["finance-hub"]}})
    store = BriefStore(tmp_path, config)
    saved = store.save_new(composed)
    store.set_status(saved["brief_id"], "executed", job_id="jXYZ")
    result = store.update_text(saved["brief_id"], "new text")
    assert result is not None and result.get("ok") is False

    discarded = store.set_status(saved["brief_id"], "discarded")
    assert discarded is not None and discarded["status"] == "discarded"
    assert discarded["job_id"] == "jXYZ"


def test_store_get_unknown_returns_none(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    store = BriefStore(tmp_path, config)
    assert store.get("bnope") is None
    assert store.list() == []
