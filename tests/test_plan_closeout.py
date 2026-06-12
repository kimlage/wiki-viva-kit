"""Closeout of the critical-review plan: archiving, freshness budget and
doc-code gate. No network; writes only in tmp_path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig


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
