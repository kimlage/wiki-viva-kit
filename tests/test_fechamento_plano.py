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


class _BudgetConfig(WikiConfig):
    pass


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


def test_command_reference_flags_undocumented(tmp_path, monkeypatch):
    audit = _load("scripts/wiki_audit.py", "wa_cmdref")
    ref = tmp_path / "memorias/sistema/wiki/referencia-comandos.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("# Ref\n\n| [wiki_a.py](x) | a | a |\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py", "scripts/wiki_b.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors)
    assert any("undocumented CLI: wiki_b.py" in e for e in errors)


def test_command_reference_flags_ghost_doc(tmp_path, monkeypatch):
    audit = _load("scripts/wiki_audit.py", "wa_cmdref2")
    ref = tmp_path / "memorias/sistema/wiki/referencia-comandos.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("| [wiki_a.py](x) | a | a |\n| [wiki_fantasma.py](y) | b | b |\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py"])
    errors: list[str] = []
    audit.audit_command_reference(errors)
    assert any("documented but nonexistent CLI: wiki_fantasma.py" in e for e in errors)


# ---------------------------------------------------------------------------
# Archiving: pure helpers
# ---------------------------------------------------------------------------


def test_archive_shift_relative_links():
    arq = _load("scripts/wiki_archive.py", "wa_arq")
    text = "[a](../x.md) [b](eventos/README.md) [c](https://ex.com) [d](#sec)"
    out = arq.shift_relative_links(text, depth=1)
    assert "[a](../../x.md)" in out
    assert "[b](../eventos/README.md)" in out
    assert "[c](https://ex.com)" in out  # URL intact
    assert "[d](#sec)" in out  # anchor intact


def test_archive_add_stale_exempt_idempotent():
    arq = _load("scripts/wiki_archive.py", "wa_arq2")
    page = "---\npage_id: p\n---\n\n# corpo\n"
    once = arq.add_stale_exempt(page)
    assert "stale_exempt: true" in once
    assert arq.add_stale_exempt(once) == once


def test_archive_frontmatter_value():
    arq = _load("scripts/wiki_archive.py", "wa_arq3")
    text = '---\ngate_state: superseded\nevent_ref: memorias/x.md\n---\ncorpo gate_state: outro\n'
    assert arq.frontmatter_value(text, "gate_state") == "superseded"
    assert arq.frontmatter_value(text, "event_ref") == "memorias/x.md"
    assert arq.frontmatter_value(text, "inexistente") == ""
