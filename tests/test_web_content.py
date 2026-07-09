from __future__ import annotations

import json
import subprocess
from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.content import build_page_content, sidecar_name, write_content_sidecars
from wiki_core.web.snapshot import (
    _summary,
    build_snapshot,
    snapshot_contract_errors,
    write_snapshot,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "wiki@example.test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Wiki Test"], cwd=root, check=True)


def _sample_repo(root: Path) -> WikiConfig:
    _write(
        root / "memories/index.md",
        """---
page_id: root
page_type: root_index
title: "Root"
context: system
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Root

The root links to [Example](example/index.md) with **bold pessoal** text and `code`.
""",
    )
    _write(
        root / "memories/example/index.md",
        """---
page_id: example-hub
page_type: context_hub
title: "Example"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
moc_parent: memories/index.md
source_refs:
  - memories/example/sources/manifest.md
---

# Example

Linked back to [Root](../index.md) and out to [Anthropic](https://www.anthropic.com/page).
Broken [ghost](missing.md) link stays honest.
""",
    )
    _write(
        root / "memories/example/sources/manifest.md",
        """---
page_id: example-source
page_type: source
title: "Example Source"
context: example
visibility: private_self
updated_at: 2026-07-01
stale_after_days: 30
---

# Example Source

Evidence record.
""",
    )
    _init_git(root)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "sample"], cwd=root, check=True, capture_output=True)
    return WikiConfig(repo_id="sample", contexts=("example",))


def test_summary_strips_markdown_and_flags_truncation() -> None:
    text, truncated = _summary("This has **bold pessoal**, `backticks` and a [Vivo](vivo.md) link.")
    assert text == "This has bold pessoal, backticks and a Vivo link."
    assert truncated is False

    long_body = " ".join(
        f"Sentence number {index} carries operational weight." for index in range(30)
    )
    cut, was_truncated = _summary(long_body)
    assert was_truncated is True
    assert len(cut) <= 262
    # Never mid-word: the cut ends at a sentence boundary or an ellipsis.
    assert cut.endswith(".") or cut.endswith("…")


def test_page_records_expose_summary_flags_and_children_counts(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    pages = {page["id"]: page for page in snapshot["pages.json"]["pages"]}
    assert "**" not in pages["root"]["summary"]
    assert "`" not in pages["root"]["summary"]
    assert "(example/index.md)" not in pages["root"]["summary"]
    assert pages["root"]["summary_truncated"] is False
    assert pages["root"]["moc_children_count"] == 1
    assert snapshot["manifest.json"]["content_sidecars"] is False


def test_build_page_content_resolves_links_backlinks_and_sources(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    assert payload["ok"] is True
    assert payload["page"]["page_id"] == "example-hub"
    assert "# Example" in payload["body"]

    by_kind = {}
    for link in payload["resolved_links"]:
        by_kind.setdefault(link["kind"], []).append(link)
    assert by_kind["page"][0]["page_id"] == "root"
    assert by_kind["external"][0]["domain"] == "www.anthropic.com"
    assert by_kind["missing"][0]["text"] == "ghost"

    assert any(item["page_id"] == "root" for item in payload["backlinks"])
    refs = payload["source_refs"]
    assert refs and refs[0]["resolved"] is True and refs[0]["page_id"] == "example-source"

    missing = build_page_content(tmp_path, config, "no-such-page", snapshot)
    assert missing["ok"] is False


def test_content_sidecars_written_behind_flag(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    out_dir = tmp_path / "out"

    written = write_snapshot(tmp_path, out_dir, config, clean=True, content_sidecars=True)
    sidecar = out_dir / "content" / sidecar_name("example-hub")
    assert sidecar.is_file()
    sidecar_rel = f"content/{sidecar_name('example-hub')}"
    assert sidecar_rel in written
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert sidecar_rel in manifest["files"]
    assert sidecar_rel in manifest["integrity"]
    loaded = {
        name: json.loads((out_dir / name).read_text(encoding="utf-8"))
        for name in manifest["files"]
    }
    assert snapshot_contract_errors(loaded) == []

    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z", content_sidecars=True)
    assert snapshot["manifest.json"]["content_sidecars"] is True
    names = {sidecar_name(page["id"]) for page in snapshot["pages.json"]["pages"]}
    assert len(names) == len(snapshot["pages.json"]["pages"])


def test_page_content_rejects_files_outside_memory_root(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    _write(tmp_path / "secrets.md", "outside memory root")
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    snapshot["pages.json"]["pages"].append(
        {"id": "escape", "path": "../secrets.md", "title": "escape", "context": "x"}
    )
    payload = build_page_content(tmp_path, config, "escape", snapshot)
    assert payload["ok"] is False


def test_write_content_sidecars_is_deterministic(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    first = write_content_sidecars(tmp_path, config, snapshot, tmp_path / "a")
    second = write_content_sidecars(tmp_path, config, snapshot, tmp_path / "b")
    for page_id, path in first.items():
        assert path.read_text(encoding="utf-8") == second[page_id].read_text(encoding="utf-8")
