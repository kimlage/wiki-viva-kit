"""Parity tests for the per-language string tables that drive GENERATED output.

Contract: every table maps language -> {key: template}; "pt" and "en" must carry
exactly the same keys, and each key's template must use exactly the same
{placeholders} in both languages (a divergence makes .format() crash — or
silently drop data — for one language only).

Covered tables: COCKPIT_STRINGS (scripts/wiki_operation_compile.py),
PROPOSAL_STRINGS (scripts/wiki_new_ingest.py), INSIGHT_STRINGS
(wiki_core/insight/job.py) and — when present in the tree — the karma display
tables (BADGE_DISPLAY/LEVEL_DISPLAY in wiki_core/score/karma.py). Values may be
nested (dicts/tuples); they are flattened to {path: string} before comparing.

scripts/ is not a package, so the script-level tables are loaded from their file
paths via importlib (same pattern as tests/test_operation_compile.py).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wiki_core.score.karma as karma_module
from wiki_core.consolidate import CONSOLIDATE_STRINGS
from wiki_core.insight.job import INSIGHT_STRINGS, _proposal_markdown

PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_i18n_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OPERATION_COMPILE = _load_script("wiki_operation_compile")
NEW_INGEST = _load_script("wiki_new_ingest")

TABLES: dict[str, dict[str, object]] = {
    "COCKPIT_STRINGS": OPERATION_COMPILE.COCKPIT_STRINGS,
    "PROPOSAL_STRINGS": NEW_INGEST.PROPOSAL_STRINGS,
    "INSIGHT_STRINGS": INSIGHT_STRINGS,
    "CONSOLIDATE_STRINGS": CONSOLIDATE_STRINGS,
}
# Karma display tables: registered only if present in the tree (they may not
# exist on older checkouts; when they do, they obey the same pt/en contract).
for _karma_table in ("BADGE_DISPLAY", "LEVEL_DISPLAY"):
    _table = getattr(karma_module, _karma_table, None)
    if isinstance(_table, dict) and "pt" in _table and "en" in _table:
        TABLES[f"karma.{_karma_table}"] = _table


def _flatten(value: object, prefix: str = "") -> dict[str, str]:
    """Flatten nested table values into {path: template-string}."""
    if isinstance(value, str):
        return {prefix: value}
    flat: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            flat.update(_flatten(child, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            flat.update(_flatten(child, f"{prefix}[{index}]"))
        return flat
    raise TypeError(f"unsupported value in string table at {prefix!r}: {type(value)!r}")


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_pt_and_en_have_identical_keys(table_name: str) -> None:
    table = TABLES[table_name]
    assert "pt" in table and "en" in table, f"{table_name}: missing pt/en language"
    pt_keys = _flatten(table["pt"]).keys()
    en_keys = _flatten(table["en"]).keys()
    assert pt_keys == en_keys, (
        f"{table_name}: key drift between pt and en: "
        f"pt-only={sorted(pt_keys - en_keys)}, en-only={sorted(en_keys - pt_keys)}"
    )


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_pt_and_en_have_identical_placeholders_per_key(table_name: str) -> None:
    table = TABLES[table_name]
    flat_pt = _flatten(table["pt"])
    flat_en = _flatten(table["en"])
    for key in flat_pt.keys() & flat_en.keys():
        pt_placeholders = set(PLACEHOLDER_RE.findall(flat_pt[key]))
        en_placeholders = set(PLACEHOLDER_RE.findall(flat_en[key]))
        assert pt_placeholders == en_placeholders, (
            f"{table_name}[{key!r}]: placeholder drift: "
            f"pt={sorted(pt_placeholders)} en={sorted(en_placeholders)}"
        )


def test_insight_chunk_bullet_comes_from_language_table() -> None:
    # The per-chunk evidence bullet is rendered via INSIGHT_STRINGS, so the
    # proposal body follows config.language ("fonte" in pt, "source" in en).
    chunks = [{"chunk_id": "chunk-1", "source_id": "source-1"}]
    date = dt.date(2026, 6, 9)
    pt = _proposal_markdown("theme", "system", date, [], chunks, [], language="pt")
    en = _proposal_markdown("theme", "system", date, [], chunks, [], language="en")
    assert "  - `chunk-1` (fonte `source-1`)" in pt
    assert "(source `source-1`)" not in pt
    assert "  - `chunk-1` (source `source-1`)" in en
    assert "(fonte `source-1`)" not in en


def test_new_ingest_source_name_fallback_is_one_functional_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # build_proposal (page_id/rebase_key) and main() (proposal file name) must
    # derive the fallback name from the SAME constant; they used to diverge
    # ("source" vs "fonte"), breaking the rebase/supersede match.
    assert NEW_INGEST.DEFAULT_SOURCE_NAME == "source"
    # Pin the English default layout: the host repo's wiki.config.yaml may pin a
    # localized layout (e.g. pt), and the page_id prefix follows the config.
    from wiki_core.config import WikiConfig
    from wiki_core.paths import WikiPaths

    en_config = WikiConfig()
    monkeypatch.setattr(NEW_INGEST, "CONFIG", en_config)
    monkeypatch.setattr(NEW_INGEST, "PATHS", WikiPaths(ROOT, en_config))
    proposal = NEW_INGEST.build_proposal(
        "https://example.com/", "system", dt.date(2026, 6, 9), "draft", "en"
    )
    assert "page_id: ingestion-2026-06-09-system-source" in proposal
    assert "rebase_key: system-source" in proposal


def test_new_ingest_page_id_prefix_follows_localized_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Compatibility for localized repos: a pt-pinned config keeps generating ids
    # in the pt vocabulary (ingest dirname drives the page_id prefix).
    from wiki_core.config import WikiConfig
    from wiki_core.paths import WikiPaths

    pt_config = WikiConfig(
        language="pt",
        default_context="sistema",
        paths={
            **WikiConfig().paths,
            "memory_root": "memorias",
            "system_dirname": "sistema",
            "ingest_dirname": "ingestao",
            "events_dirname": "eventos",
        },
    )
    monkeypatch.setattr(NEW_INGEST, "CONFIG", pt_config)
    monkeypatch.setattr(NEW_INGEST, "PATHS", WikiPaths(ROOT, pt_config))
    proposal = NEW_INGEST.build_proposal(
        "https://example.com/", "sistema", dt.date(2026, 6, 9), "draft", "pt"
    )
    assert "page_id: ingestao-2026-06-09-sistema-source" in proposal
    assert "rebase_key: sistema-source" in proposal
    assert "event_ref: memorias/sistema/ingestao/eventos/2026-06-09-sistema-source.md" in proposal
    assert "[eventos/](eventos/README.md)" in proposal
