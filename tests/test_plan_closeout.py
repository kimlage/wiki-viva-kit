"""Closeout of the critical-review plan: archiving, freshness budget and
doc-code gate. No network; writes only in tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig
from wiki_core.upgrade import (
    compare_portable_files,
    load_mapping,
    upgrade_package_sha256,
)


def _load(path_rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path_rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Freshness budget (gate that bites)
# ---------------------------------------------------------------------------


def test_freshness_budget_bites_over_budget():
    audit = _load("scripts/wiki_audit.py", "wa_budget")
    config = WikiConfig(audit={"freshness_budget": 2})
    errors: list[str] = []
    warnings = ["a.md: stale page", "b.md: stale page", "c.md: stale page", "x.md: another warning"]
    audit.audit_freshness_budget(errors, warnings, config)
    assert any("freshness budget exceeded" in e for e in errors)


def test_freshness_budget_quiet_within_budget():
    audit = _load("scripts/wiki_audit.py", "wa_budget2")
    config = WikiConfig(audit={"freshness_budget": 5})
    errors: list[str] = []
    warnings = ["a.md: stale page", "b.md: stale page"]
    audit.audit_freshness_budget(errors, warnings, config)
    assert errors == []


def test_freshness_budget_disabled_by_default():
    audit = _load("scripts/wiki_audit.py", "wa_budget3")
    errors: list[str] = []
    audit.audit_freshness_budget(errors, ["a.md: stale page"] * 100, WikiConfig())
    assert errors == []


# ---------------------------------------------------------------------------
# Doc-code gate (command reference)
# ---------------------------------------------------------------------------

# English default from WikiConfig.paths["command_reference_page"]; localized
# repos pin their own page in wiki.config.yaml.
CMD_REF_REL = WikiConfig().paths["command_reference_page"]


def test_command_reference_flags_undocumented(tmp_path, monkeypatch):
    audit = _load("scripts/wiki_audit.py", "wa_cmdref")
    ref = tmp_path / CMD_REF_REL
    ref.parent.mkdir(parents=True)
    ref.write_text("# Ref\n\n| [wiki_a.py](x) | a | a |\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py", "scripts/wiki_b.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors, WikiConfig())
    assert any("undocumented CLI: wiki_b.py" in e for e in errors)


def test_command_reference_flags_ghost_doc(tmp_path, monkeypatch):
    audit = _load("scripts/wiki_audit.py", "wa_cmdref2")
    ref = tmp_path / CMD_REF_REL
    ref.parent.mkdir(parents=True)
    ref.write_text("| [wiki_a.py](x) | a | a |\n| [wiki_ghost.py](y) | b | b |\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors, WikiConfig())
    assert any("documented but nonexistent CLI: wiki_ghost.py" in e for e in errors)


def test_command_reference_missing_page_fails_loud(tmp_path, monkeypatch):
    # Silent-gate fix: tracked wiki CLIs with no reference page is an ERROR
    # (the gate used to return silently and doc-code drift went unchecked).
    audit = _load("scripts/wiki_audit.py", "wa_cmdref3")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors, WikiConfig())
    assert errors and errors[0].startswith(f"{CMD_REF_REL}: missing command reference page")


def test_command_reference_inapplicable_without_clis(tmp_path, monkeypatch):
    # No tracked wiki CLIs: the gate is inapplicable, not broken — stays quiet.
    audit = _load("scripts/wiki_audit.py", "wa_cmdref4")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/other_tool.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors, WikiConfig())
    assert errors == []


# ---------------------------------------------------------------------------
# Archiving: pure helpers
# ---------------------------------------------------------------------------


def test_archive_shift_relative_links():
    arq = _load("scripts/wiki_archive.py", "wa_arq")
    text = "[a](../x.md) [b](events/README.md) [c](https://ex.com) [d](#sec)"
    out = arq.shift_relative_links(text, depth=1)
    assert "[a](../../x.md)" in out
    assert "[b](../events/README.md)" in out
    assert "[c](https://ex.com)" in out  # URL intact
    assert "[d](#sec)" in out  # anchor intact


def test_archive_add_stale_exempt_idempotent():
    arq = _load("scripts/wiki_archive.py", "wa_arq2")
    page = "---\npage_id: p\n---\n\n# body\n"
    once = arq.add_stale_exempt(page)
    assert "stale_exempt: true" in once
    assert arq.add_stale_exempt(once) == once


def test_archive_frontmatter_value():
    arq = _load("scripts/wiki_archive.py", "wa_arq3")
    text = '---\ngate_state: superseded\nevent_ref: memories/x.md\n---\nbody gate_state: other\n'
    assert arq.frontmatter_value(text, "gate_state") == "superseded"
    assert arq.frontmatter_value(text, "event_ref") == "memories/x.md"
    assert arq.frontmatter_value(text, "missing") == ""


def test_archive_frontmatter_requires_fence_on_line_zero():
    arq = _load("scripts/wiki_archive.py", "wa_arq4")
    # '---' only appears in the BODY (horizontal rules): there is no frontmatter,
    # so no key must be read and stale_exempt must not be injected mid-body.
    text = "# Title\n\nintro\n\n---\ngate_state: superseded\n---\n\nmore body\n"
    assert arq.frontmatter_value(text, "gate_state") == ""
    assert arq.add_stale_exempt(text) == text
    assert arq.frontmatter_value("", "gate_state") == ""
    assert arq.add_stale_exempt("") == ""


def test_archive_add_stale_exempt_with_body_rule():
    arq = _load("scripts/wiki_archive.py", "wa_arq5")
    # Real frontmatter at line 0 + a horizontal rule later in the body: the flag
    # goes inside the frontmatter, the body rule stays untouched.
    page = "---\npage_id: p\n---\n\nbody\n\n---\n\nfooter\n"
    out = arq.add_stale_exempt(page)
    assert out.startswith("---\npage_id: p\nstale_exempt: true\n---\n")
    assert out.endswith("\nbody\n\n---\n\nfooter\n")


# ---------------------------------------------------------------------------
# Quality report gate: ratchet budgets
# ---------------------------------------------------------------------------


def _quality_report(summary_overrides: dict[str, int]) -> dict:
    summary = {
        "bad_repetition_blocks": 0,
        "low_information_density_pages": 0,
    }
    summary.update(summary_overrides)
    return {"summary": summary}


def test_quality_report_check_fails_over_low_density_budget(monkeypatch, capsys):
    quality_cli = _load("scripts/wiki_quality_report.py", "wqr_budget")
    monkeypatch.setattr(quality_cli, "load_config", lambda _root: WikiConfig())
    monkeypatch.setattr(
        quality_cli,
        "build_quality_report",
        lambda _root, _config: _quality_report({"low_information_density_pages": 2}),
    )

    result = quality_cli.main(["--format", "json", "--check", "--max-low-density", "1"])

    assert result == 1
    assert "low_information_density_pages=2" in capsys.readouterr().err


def test_quality_report_check_accepts_ratchet_budgets(monkeypatch):
    quality_cli = _load("scripts/wiki_quality_report.py", "wqr_budget_ok")
    monkeypatch.setattr(quality_cli, "load_config", lambda _root: WikiConfig())
    monkeypatch.setattr(
        quality_cli,
        "build_quality_report",
        lambda _root, _config: _quality_report(
            {"low_information_density_pages": 2, "bad_repetition_blocks": 1}
        ),
    )

    result = quality_cli.main(
        [
            "--format",
            "json",
            "--check",
            "--max-low-density",
            "2",
            "--max-bad-repetition",
            "1",
        ]
    )

    assert result == 0


def test_quality_report_check_reads_configured_budgets(monkeypatch):
    quality_cli = _load("scripts/wiki_quality_report.py", "wqr_config_budget")
    monkeypatch.setattr(
        quality_cli,
        "load_config",
        lambda _root: WikiConfig(
            audit={"quality_max_low_density": 2, "quality_max_bad_repetition": 1}
        ),
    )
    monkeypatch.setattr(
        quality_cli,
        "build_quality_report",
        lambda _root, _config: _quality_report(
            {"low_information_density_pages": 2, "bad_repetition_blocks": 1}
        ),
    )

    result = quality_cli.main(["--format", "json", "--check"])

    assert result == 0


# ---------------------------------------------------------------------------
# Toolkit drift: single `git diff` for shared-content comparison
# ---------------------------------------------------------------------------


def test_toolkit_drift_single_diff(tmp_path, monkeypatch):
    import subprocess

    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_test")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@test")
    git("config", "user.name", "test")
    (tmp_path / "wiki_core").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "wiki_core" / "a.py").write_text("v1\n", encoding="utf-8")
    (tmp_path / "scripts" / "wiki_x.py").write_text("x1\n", encoding="utf-8")
    (tmp_path / "scripts" / "personal.py").write_text("p1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("branch", "refbranch")
    (tmp_path / "wiki_core" / "a.py").write_text("v2\n", encoding="utf-8")
    (tmp_path / "scripts" / "wiki_x.py").write_text("x2\n", encoding="utf-8")
    (tmp_path / "scripts" / "personal.py").write_text("p2\n", encoding="utf-8")  # not toolkit
    (tmp_path / "wiki_core" / "new.py").write_text("only-head\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "head")

    monkeypatch.setattr(drift_mod, "ROOT", tmp_path)
    monkeypatch.setattr(drift_mod, "IGNORE_FILE", tmp_path / ".toolkit-drift-ignore")
    report = drift_mod.drift("refbranch")
    assert report["content_differs"] == ["scripts/wiki_x.py", "wiki_core/a.py"]
    assert report["only_in_head"] == ["wiki_core/new.py"]
    assert report["only_in_ref"] == []


def test_toolkit_drift_ref_path_compares_checkouts(tmp_path, monkeypatch):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_path_test")
    current = tmp_path / "current"
    ref = tmp_path / "ref"
    for root in (current, ref):
        (root / "wiki_core").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "tests" / "__pycache__").mkdir(parents=True)
    (current / "wiki_core" / "a.py").write_text("current\n", encoding="utf-8")
    (ref / "wiki_core" / "a.py").write_text("ref\n", encoding="utf-8")
    (current / "scripts" / "wiki_only_current.py").write_text("x\n", encoding="utf-8")
    (ref / "scripts" / "wiki_only_ref.py").write_text("y\n", encoding="utf-8")
    (current / "tests" / "__pycache__" / "ignored.pyc").write_bytes(b"cache")
    (ref / "tests" / "__pycache__" / "ignored.pyc").write_bytes(b"other-cache")

    monkeypatch.setattr(drift_mod, "ROOT", current)
    monkeypatch.setattr(drift_mod, "IGNORE_FILE", current / ".toolkit-drift-ignore")

    report = drift_mod.drift_against_path(ref)

    assert report["content_differs"] == ["wiki_core/a.py"]
    assert report["only_in_head"] == ["scripts/wiki_only_current.py"]
    assert report["only_in_ref"] == ["scripts/wiki_only_ref.py"]


def _package_drift_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    kit = tmp_path / "kit"
    consumer = tmp_path / "consumer"
    kit.mkdir()
    consumer.mkdir()

    def write(root: Path, relative: str, text: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    portable = {
        "wiki_core/shared.py": "core-v1\n",
        "scripts/wiki_shared.py": "script-v1\n",
        "apps/wiki-cockpit/src/shared.ts": "export const value = 1;\n",
    }
    consumer_owned = {
        "tests/public_only.py": "assert True\n",
        ".github/workflows/wiki.yml": "name: public\n",
        "wiki.config.yaml": "repo_id: public\n",
        "apps/wiki-cockpit/public/wiki-cockpit.config.json": '{"repo":"public"}\n',
    }
    for relative, text in {**portable, **consumer_owned}.items():
        write(kit, relative, text)

    subprocess.run(["git", "init", "-q"], cwd=kit, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=kit, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=kit, check=True)
    subprocess.run(["git", "add", "-A"], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "portable source"], cwd=kit, check=True)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kit, text=True
    ).strip()

    package = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml").read_text(
            encoding="utf-8"
        )
    )
    package["release"]["source_sha"] = source_sha
    package_path = kit / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_text(
        yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", package_path.relative_to(kit)], cwd=kit, check=True
    )
    subprocess.run(["git", "commit", "-qm", "package authority"], cwd=kit, check=True)

    for relative, text in portable.items():
        write(consumer, relative, text)
    write(consumer, "tests/private_only.py", "assert 2 + 2 == 4\n")
    write(consumer, ".github/workflows/wiki.yml", "name: private\n")
    write(consumer, "wiki.config.yaml", "repo_id: private\n")
    write(
        consumer,
        "apps/wiki-cockpit/public/wiki-cockpit.config.json",
        '{"repo":"private"}\n',
    )
    return kit, consumer, source_sha


def test_toolkit_drift_ref_path_uses_package_allowlist_and_pinned_source(
    tmp_path, monkeypatch
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_package_test")
    kit, consumer, source_sha = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)

    # A later source-worktree edit is not release authority; the pinned Git
    # tree remains byte-identical to the consumer.
    (kit / "wiki_core/shared.py").write_text("later-unpinned-edit\n", encoding="utf-8")
    report = drift_mod.portable_drift_against_path(kit)

    assert report["source_sha"] == source_sha
    assert report["source_mode"] == "pinned_git_tree"
    assert report["package_source"] == "committed_head"
    assert report["package"] == "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
    assert report["package_sha256"] == upgrade_package_sha256(
        load_mapping(kit / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml")
    )
    assert len(report["package_blob_sha256"]) == 64
    assert report["drift_total"] == 0
    assert report["only_in_head"] == []
    assert report["only_in_ref"] == []
    assert report["content_differs"] == []


def test_toolkit_drift_ref_path_rejects_real_portable_drift(
    tmp_path, monkeypatch, capsys
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_package_drift_test")
    kit, consumer, _ = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    (consumer / "wiki_core/shared.py").write_text("consumer-diverged\n", encoding="utf-8")

    exit_code = drift_mod.main(["--ref-path", str(kit), "--check"])
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert exit_code == 1
    assert payload["ref"] == "<reference-kit>"
    assert payload["drift_total"] == 1
    assert payload["content_differs"] == ["wiki_core/shared.py"]
    assert str(kit) not in output.out + output.err


@pytest.mark.parametrize("authority_failure", ["missing_package", "missing_source"])
def test_toolkit_drift_ref_path_fails_closed_without_authority(
    tmp_path, monkeypatch, authority_failure, capsys
):
    drift_mod = _load(
        "scripts/wiki_toolkit_drift.py", f"wtd_authority_{authority_failure}_test"
    )
    kit, consumer, _ = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    package_path = kit / drift_mod.PACKAGE_REL
    if authority_failure == "missing_package":
        package_path.unlink()
    else:
        package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
        package["release"]["source_sha"] = "f" * 40
        package_path.write_text(
            yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", package_path.relative_to(kit)], cwd=kit, check=True)
        subprocess.run(["git", "commit", "-qm", "missing source"], cwd=kit, check=True)

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3
    output = capsys.readouterr()
    assert str(kit) not in output.out + output.err


def test_toolkit_drift_ref_path_fails_closed_on_unsafe_ignore(
    tmp_path, monkeypatch, capsys
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_package_ignore_test")
    kit, consumer, _ = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    (consumer / ".toolkit-drift-ignore").write_text("wiki_core/**\n", encoding="utf-8")

    exit_code = drift_mod.main(["--ref-path", str(kit), "--check"])
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert exit_code == 1
    assert payload["drift_total"] == 0
    assert payload["unsafe_ignore_patterns"] == ["wiki_core/**"]
    assert "DRIFT POLICY" in output.err


@pytest.mark.parametrize(
    "treeish", [None, "", "HEAD", "main", "abc1234", "HEAD^{tree}"]
)
def test_toolkit_drift_ref_path_rejects_non_sha_treeish(
    tmp_path, monkeypatch, treeish
):
    drift_mod = _load(
        "scripts/wiki_toolkit_drift.py",
        "wtd_treeish_" + str(treeish).replace("^", "x"),
    )
    kit, consumer, _ = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    package_path = kit / drift_mod.PACKAGE_REL
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    package["release"]["source_sha"] = treeish
    package_path.write_text(
        yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", package_path.relative_to(kit)], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "invalid treeish"], cwd=kit, check=True)

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3


def test_toolkit_drift_ref_path_rejects_tree_object_sha(
    tmp_path, monkeypatch
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_tree_object_test")
    kit, consumer, source_sha = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    tree_sha = subprocess.check_output(
        ["git", "rev-parse", f"{source_sha}^{{tree}}"], cwd=kit, text=True
    ).strip()
    package_path = kit / drift_mod.PACKAGE_REL
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    package["release"]["source_sha"] = tree_sha
    package_path.write_text(
        yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", package_path.relative_to(kit)], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "tree object"], cwd=kit, check=True)

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3


def test_toolkit_drift_ref_path_rejects_non_ancestor_commit(
    tmp_path, monkeypatch
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_orphan_commit_test")
    kit, consumer, source_sha = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    source_tree = subprocess.check_output(
        ["git", "rev-parse", f"{source_sha}^{{tree}}"], cwd=kit, text=True
    ).strip()
    orphan_sha = subprocess.check_output(
        ["git", "commit-tree", source_tree, "-m", "orphan source"],
        cwd=kit,
        text=True,
    ).strip()
    package_path = kit / drift_mod.PACKAGE_REL
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    package["release"]["source_sha"] = orphan_sha
    package_path.write_text(
        yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", package_path.relative_to(kit)], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "orphan authority"], cwd=kit, check=True)

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3


def test_toolkit_drift_ref_path_rejects_git_replace_refs(
    tmp_path, monkeypatch
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_replace_ref_test")
    kit, consumer, source_sha = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    (kit / "wiki_core/shared.py").write_text("core-v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "wiki_core/shared.py"], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "replacement payload"], cwd=kit, check=True)
    replacement_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kit, text=True
    ).strip()
    subprocess.run(
        ["git", "replace", source_sha, replacement_sha], cwd=kit, check=True
    )
    (consumer / "wiki_core/shared.py").write_text("core-v2\n", encoding="utf-8")

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3


def test_portable_compare_ignores_replace_objects_even_after_precheck(
    tmp_path, monkeypatch, capsys
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_replace_race_test")
    kit, consumer, source_sha = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    (kit / "wiki_core/shared.py").write_text("core-v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "wiki_core/shared.py"], cwd=kit, check=True)
    subprocess.run(["git", "commit", "-qm", "replacement payload"], cwd=kit, check=True)
    replacement_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=kit, text=True
    ).strip()
    subprocess.run(
        ["git", "replace", source_sha, replacement_sha], cwd=kit, check=True
    )
    (consumer / "wiki_core/shared.py").write_text("core-v2\n", encoding="utf-8")

    real_check_output = drift_mod.subprocess.check_output

    def hide_replace_precheck(args, *call_args, **call_kwargs):
        if list(args) == ["git", "replace", "-l"]:
            return "" if call_kwargs.get("text") else b""
        return real_check_output(args, *call_args, **call_kwargs)

    monkeypatch.setattr(drift_mod.subprocess, "check_output", hide_replace_precheck)
    exit_code = drift_mod.main(["--ref-path", str(kit), "--check"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["content_differs"] == ["wiki_core/shared.py"]

    package = load_mapping(kit / drift_mod.PACKAGE_REL)
    direct = compare_portable_files(
        kit,
        consumer,
        package,
        source_sha=source_sha,
        git_no_replace_objects=True,
    )
    assert direct["content_differs"] == ["wiki_core/shared.py"]


def test_toolkit_drift_ref_path_rejects_uncommitted_package_mutation(
    tmp_path, monkeypatch
):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_package_mutation_test")
    kit, consumer, _ = _package_drift_fixture(tmp_path)
    monkeypatch.setattr(drift_mod, "ROOT", consumer)
    package_path = kit / drift_mod.PACKAGE_REL
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    package["portable_import"]["allow"] = ["wiki_core/nonexistent.py"]
    package_path.write_text(
        yaml.safe_dump(package, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    assert drift_mod.main(["--ref-path", str(kit), "--check"]) == 3


def test_toolkit_drift_package_argument_cannot_be_silently_ignored(tmp_path):
    drift_mod = _load("scripts/wiki_toolkit_drift.py", "wtd_package_cli_test")

    with pytest.raises(SystemExit) as error:
        drift_mod.main(
            ["--ref", "HEAD", "--package", str(tmp_path / "missing.yaml"), "--check"]
        )

    assert error.value.code == 2
