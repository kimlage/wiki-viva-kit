from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wiki_core.config import WikiConfig
from wiki_core.web.content import build_page_content, sidecar_name, write_content_sidecars
from wiki_core.web.snapshot import (
    _summary,
    build_snapshot,
    prepare_snapshot_artifacts,
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


def test_action_fields_resolve_verified_pages_and_pinned_artifacts(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text().replace("source_refs:", '''next_action: "Read [source](sources/manifest.md)."
blocker_reason: "See [receipt](../../docs/receipt.json)."
action_dialogue:
  - text: "[Receipt](../../docs/receipt.json), [alias](../../docs/alias.json), [directory](../../alias-dir/receipt.json), [space](<../../docs/spaço receipt.json>) and [missing](../../untracked.json)."
source_refs:'''))
    _write(tmp_path / "docs/receipt.json", '{"result":"received", "integrated":false}\n')
    (tmp_path / "docs/alias.json").symlink_to("receipt.json")
    (tmp_path / "alias-dir").symlink_to("docs", target_is_directory=True)
    _write(tmp_path / "docs/spaço receipt.json", "second receipt")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "receipt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:example/synthetic-wiki.git"], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True)
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    head = snapshot["git.json"]["head"]
    _write(tmp_path / "untracked.json", "not published")
    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    links = {link["href"]: link for link in payload["resolved_links"]}
    assert links["sources/manifest.md"]["page_id"] == "example-source"
    assert links["../../docs/receipt.json"] == {
        "kind": "artifact", "text": "Receipt", "href": "../../docs/receipt.json",
        "path": "docs/receipt.json", "domain": "github.com",
        "url": f"https://github.com/example/synthetic-wiki/blob/{head}/docs/receipt.json",
    }
    assert links["../../untracked.json"]["kind"] == "missing"
    assert links["../../docs/alias.json"]["kind"] == "missing"
    assert links["../../alias-dir/receipt.json"]["kind"] == "missing"
    assert links["../../docs/spaço receipt.json"]["url"].endswith("/docs/spa%C3%A7o%20receipt.json")
    from wiki_core.web.repository_links import published_blob_links
    blobs = published_blob_links(tmp_path, snapshot["git.json"])
    assert "docs/alias.json" not in blobs
    assert "untracked.json" not in blobs
    # A later local edit must never rewrite the snapshot's immutable URL.
    _write(tmp_path / "docs/receipt.json", "later observation")
    (tmp_path / "docs/alias.json").unlink()
    (tmp_path / "docs/alias.json").symlink_to("../memories/index.md")
    (tmp_path / "alias-dir").unlink()
    (tmp_path / "alias-dir").symlink_to("memories", target_is_directory=True)
    assert build_page_content(tmp_path, config, "example-hub", snapshot)["resolved_links"] == payload["resolved_links"]
    assert published_blob_links(tmp_path, {**snapshot["git.json"], "published_head": False}) == {}
    assert published_blob_links(tmp_path, {**snapshot["git.json"], "head": "HEAD"}) == {}
    assert published_blob_links(tmp_path, {**snapshot["git.json"], "published_head": "true"}) == {}
    assert published_blob_links(tmp_path, {**snapshot["git.json"], "worktree": {"clean": False}}) == {}
    assert published_blob_links(tmp_path, {**snapshot["git.json"], "proposal": {"human_gate_state": "ready_for_review"}}) == {}
    assert published_blob_links(tmp_path, {}) == {}


def test_action_field_links_remain_inert_without_published_origin(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    page = tmp_path / "memories/example/index.md"
    page.write_text(page.read_text().replace("source_refs:", 'next_action: "Read [local](../../docs/receipt.json) or [escape](../../../escape.json)."\nsource_refs:'))
    _write(tmp_path / "docs/receipt.json", "retained")
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")
    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    assert all(link["kind"] == "missing" for link in payload["resolved_links"] if link["text"] in {"local", "escape"})


@pytest.mark.parametrize("href", ["https://[broken", "https://example.test／unsafe"])
@pytest.mark.parametrize("field", ["action_dialogue", "blocker_reason", "next_action"])
def test_malformed_action_urls_do_not_break_reader_or_sidecars(
    tmp_path: Path, href: str, field: str,
) -> None:
    config = _sample_repo(tmp_path)
    page = tmp_path / "memories/example/index.md"
    text = f"Read [evidence]({href}) and [source](sources/manifest.md)."
    encoded = json.dumps(text, ensure_ascii=False)
    entry = (f"action_dialogue:\n  - text: {encoded}\n" if field == "action_dialogue"
             else f"{field}: {encoded}\n")
    page.write_text(page.read_text().replace("source_refs:", entry + "source_refs:"))
    before = page.read_bytes()
    snapshot = build_snapshot(tmp_path, config, generated_at="2026-07-01T00:00:00Z")

    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    assert payload["ok"] is True
    links = {link["href"]: link for link in payload["resolved_links"]}
    assert links[href] == {"kind": "missing", "text": "evidence", "href": href, "target": href}
    assert links["sources/manifest.md"]["page_id"] == "example-source"
    written = write_content_sidecars(tmp_path, config, snapshot, tmp_path / "site")
    assert json.loads(written["example-hub"].read_text()) == payload
    assert page.read_bytes() == before


@pytest.mark.parametrize("remote", ["https://secret@github.com/example/wiki", "https://github.com.evil.test/example/wiki", "file:///private/repo", "ssh://user@host/repo", "https://github.com/../wiki"])
def test_repository_display_url_rejects_credentials_or_unknown_hosts(remote: str) -> None:
    from wiki_core.web.git_ops import _repository_web_url
    assert _repository_web_url(remote) is None


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


def test_page_content_rejects_body_from_newer_filesystem_revision(
    tmp_path: Path,
) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(
        tmp_path, config, generated_at="2026-07-01T00:00:00Z"
    )
    old_snapshot_id = snapshot["manifest.json"]["snapshot_id"]
    page_path = tmp_path / "memories/example/index.md"
    page_path.write_text(
        page_path.read_text(encoding="utf-8")
        + "\nThis body exists only in revision B.\n",
        encoding="utf-8",
    )

    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    expected_content_sha = next(
        page["content_sha256"]
        for page in snapshot["pages.json"]["pages"]
        if page["id"] == "example-hub"
    )

    assert payload == {
        "ok": False,
        "error": "page changed since snapshot; refresh required",
        "error_code": "snapshot_revision_mismatch",
        "page_id": "example-hub",
        "snapshot_id": old_snapshot_id,
        "expected_content_sha256": expected_content_sha,
        "actual_content_sha256": payload["actual_content_sha256"],
    }
    assert "body" not in payload


def test_sidecar_freeze_fails_if_page_changes_after_snapshot(tmp_path: Path) -> None:
    config = _sample_repo(tmp_path)
    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
        content_sidecars=True,
    )
    page_path = tmp_path / "memories/example/index.md"
    page_path.write_text(
        page_path.read_text(encoding="utf-8") + "\nConcurrent edit.\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="page changed since snapshot"):
        prepare_snapshot_artifacts(
            tmp_path, config, snapshot, content_sidecars=True
        )


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


@pytest.mark.parametrize("literal", [".nan", ".inf", "-.inf"])
def test_non_finite_frontmatter_never_reaches_a_content_sidecar_or_promotion(
    tmp_path: Path,
    literal: str,
) -> None:
    config = _sample_repo(tmp_path)
    page = tmp_path / "memories/example/index.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "stale_after_days: 30\n",
            f"stale_after_days: 30\nnon_finite_probe: {literal}\n",
            1,
        ),
        encoding="utf-8",
    )
    snapshot = build_snapshot(
        tmp_path,
        config,
        generated_at="2026-07-01T00:00:00Z",
        content_sidecars=True,
    )

    payload = build_page_content(tmp_path, config, "example-hub", snapshot)
    assert payload == {
        "ok": False,
        "error": "page frontmatter contains a non-finite number",
        "error_code": "content_frontmatter_non_finite",
        "page_id": "example-hub",
        "snapshot_id": snapshot["manifest.json"]["snapshot_id"],
    }

    target = tmp_path / "published"
    with pytest.raises(ValueError, match="non-finite number"):
        write_snapshot(
            tmp_path,
            target,
            config,
            clean=True,
            content_sidecars=True,
        )
    assert not target.exists()
