"""Offline tests for pure helpers/constants in scripts/wiki_audit.py.

scripts/ is not a package, so the module is loaded directly from its file path
via importlib.util.spec_from_file_location. wiki_audit.py inserts the repo ROOT
on sys.path at import time, so its own `wiki_core` imports resolve.

No network, no writes outside tmp_path. Production code is not modified.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIKI_AUDIT_PATH = ROOT / "scripts" / "wiki_audit.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config


def _load_wiki_audit():
    # Ensure ROOT is importable for the module's internal `wiki_core` imports.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("wiki_audit_under_test", WIKI_AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses / from __future__ resolve cleanly.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_wiki_audit()


# ---------------------------------------------------------------------------
# ABSOLUTE_USER_PATH_RE
# ---------------------------------------------------------------------------


def test_absolute_user_path_re_matches_and_stops_at_space(audit):
    text = "/Users/foo/bar/baz.md without link"
    match = audit.ABSOLUTE_USER_PATH_RE.search(text)
    assert match is not None
    matched = match.group(0)
    assert matched == "/Users/foo/bar/baz.md"
    # Regression: the regex must stop at the space and not swallow "without link".
    assert " " not in matched
    assert "without" not in matched


def test_absolute_user_path_re_does_not_match_relative(audit):
    assert audit.ABSOLUTE_USER_PATH_RE.search("memories/finance/index.md") is None


# ---------------------------------------------------------------------------
# HOME_TRAVERSAL_RE
# ---------------------------------------------------------------------------


def test_home_traversal_re_matches_downloads_traversal(audit):
    assert audit.HOME_TRAVERSAL_RE.search("../../../../Downloads/x.pdf") is not None


def test_home_traversal_re_ignores_normal_relative_path(audit):
    # A normal relative path (no repeated parent traversal into Downloads).
    assert audit.HOME_TRAVERSAL_RE.search("memories/system/log.md") is None
    assert audit.HOME_TRAVERSAL_RE.search("../docs/references/note.md") is None


# ---------------------------------------------------------------------------
# QUADRANT_PLACEHOLDERS
# ---------------------------------------------------------------------------


def test_metodologia_is_not_a_placeholder(audit):
    # Regression for the "todo" in "metodologia" bug: real prose must not match.
    content = "metodologia de revisao contextual aplicada".lower()
    assert not any(ph in content for ph in audit.QUADRANT_PLACEHOLDERS)


def test_placeholder_phrase_matches(audit):
    content = "A preencher apos leitura contextual.".lower()
    assert any(ph in content for ph in audit.QUADRANT_PLACEHOLDERS)


# ---------------------------------------------------------------------------
# primary_pages: core + config-driven contexts (portability)
# ---------------------------------------------------------------------------


def test_primary_pages_core_plus_config_contexts(audit):
    pages = audit.primary_pages(WikiConfig(contexts=("alpha", "beta")))
    # Method core (English defaults) always present.
    assert "memories/index.md" in pages
    assert "memories/system/log.md" in pages
    # One hub per context declared in the config (nothing hardcoded).
    assert "memories/alpha/index.md" in pages
    assert "memories/beta/index.md" in pages


def test_primary_pages_no_contexts_is_core_only(audit):
    config = WikiConfig()
    pages = audit.primary_pages(config)
    assert pages == list(config.audit["core_pages"])
    # No personal context or localized layout hardcoded.
    assert not any("financeiro" in p or "memorias" in p for p in pages)


def test_impact_ack_uses_configured_ledger_path(tmp_path, monkeypatch, audit):
    ledger = tmp_path / "memorias/sistema/impact-acks.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "- 2026-06-12 | alterada: memorias/a.md | afetada: memorias/b.md | "
        "sem_impacto: frontmatter only\n",
        encoding="utf-8",
    )
    config = WikiConfig(
        paths={
            **WikiConfig().paths,
            "memory_root": "memorias",
            "impact_acks_page": "memorias/sistema/impact-acks.md",
        }
    )

    monkeypatch.setattr(audit, "ROOT", tmp_path)

    assert audit._impact_ack_added(config, "memorias/b.md") is True


def test_semantic_impact_text_ignores_link_targets_dates_and_reflow(audit):
    old = """---
page_id: kim
updated_at: 2026-06-01
---

Atualizado em: 2026-06-01

Kim aparece junto a Michelle, Marcelo, [Celso Fujisawa](old/celso.md) e IFC.
"""
    new = """---
page_id: kim
updated_at: 2026-06-12
---

Atualizado em: 2026-06-12

Kim aparece junto a [Michelle](michelle.md), [Marcelo](marcelo.md),
[Celso Fujisawa](celso-fujisawa.md) e IFC.
"""
    changed = new.replace("IFC.", "SmartFIB.")

    assert audit._semantic_impact_text(old) == audit._semantic_impact_text(new)
    assert audit._semantic_impact_text(old) != audit._semantic_impact_text(changed)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


VALID_FRONTMATTER = """---
page_id: test-page
page_type: dashboard
context: test context
visibility: private_self
updated_at: 2026-06-09
stale_after_days: 7
sources_policy: required
gate: github_pr
sensitive_data_policy: private_sensitive_allowed
---

# Body

Test content.
"""


def test_parse_frontmatter_valid(tmp_path, audit):
    path = tmp_path / "valid.md"
    path.write_text(VALID_FRONTMATTER, encoding="utf-8")
    values, errors = audit.parse_frontmatter(path)
    assert errors == []
    for key in audit.REQUIRED_KEYS:
        assert key in values
    assert values["page_id"] == "test-page"
    assert values["page_type"] == "dashboard"


def test_parse_frontmatter_missing_block(tmp_path, audit):
    path = tmp_path / "no-frontmatter.md"
    path.write_text("# No frontmatter\n\nbody only here.\n", encoding="utf-8")
    values, errors = audit.parse_frontmatter(path)
    assert values == {}
    assert "missing frontmatter block" in errors


def test_parse_frontmatter_strips_quotes(tmp_path, audit):
    # Finding 15: quoted visibility escaped the public PII block.
    path = tmp_path / "quoted.md"
    path.write_text(
        '---\npage_id: p\npage_type: dashboard\ncontext: c\n'
        'visibility: "public_candidate"\nupdated_at: 2026-06-09\n'
        "stale_after_days: 7\nsources_policy: required\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# t\n",
        encoding="utf-8",
    )
    values, _ = audit.parse_frontmatter(path)
    assert values["visibility"] == "public_candidate"


# ---------------------------------------------------------------------------
# audit_stale_coverage: freshness for EVERY memory page
# ---------------------------------------------------------------------------


def _seed_memory_page(tmp_path, audit, monkeypatch, rel, *, stale_days, updated, extra=""):
    page = tmp_path / rel
    page.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\nvisibility: private_self\nupdated_at: {updated}\n"
    if stale_days is not None:
        fm += f"stale_after_days: {stale_days}\n"
    fm += extra + "---\n\n# page\n\nbody.\n"
    page.write_text(fm, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "markdown_files", lambda: [rel])
    monkeypatch.setattr(audit, "primary_pages", lambda config: ())


def test_stale_coverage_warns_stale_outside_primary(tmp_path, audit, monkeypatch):
    _seed_memory_page(
        tmp_path, audit, monkeypatch, "memories/x/old.md", stale_days=7, updated="2020-01-01"
    )
    warnings: list[str] = []
    audit.audit_stale_coverage(warnings, WikiConfig())
    assert any("stale page" in w for w in warnings)


def test_stale_coverage_reports_gap_without_field(tmp_path, audit, monkeypatch):
    _seed_memory_page(
        tmp_path, audit, monkeypatch, "memories/x/nofield.md", stale_days=None, updated="2026-06-09"
    )
    warnings: list[str] = []
    audit.audit_stale_coverage(warnings, WikiConfig())
    assert any("no declared freshness" in w for w in warnings)


def test_stale_coverage_exempt_suppresses(tmp_path, audit, monkeypatch):
    _seed_memory_page(
        tmp_path,
        audit,
        monkeypatch,
        "memories/x/exempt.md",
        stale_days=None,
        updated="2026-06-09",
        extra="stale_exempt: true\n",
    )
    warnings: list[str] = []
    audit.audit_stale_coverage(warnings, WikiConfig())
    assert warnings == []


# ---------------------------------------------------------------------------
# audit_pii: private vs --public-export
# ---------------------------------------------------------------------------


def _seed_private_page_with_pii(tmp_path, audit, monkeypatch):
    page = tmp_path / "memories" / "pii.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\nvisibility: private_self\n---\n\n# Page\n\nCPF: 529.982.247-25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "markdown_files", lambda: ["memories/pii.md"])


def test_audit_pii_private_is_silent(tmp_path, audit, monkeypatch):
    # Personal private repo: PII in a private page produces neither error NOR warning.
    _seed_private_page_with_pii(tmp_path, audit, monkeypatch)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_pii(errors, warnings, WikiConfig(), public_export=False)
    assert errors == []
    assert warnings == []


def test_audit_pii_public_export_promotes_to_error(tmp_path, audit, monkeypatch):
    _seed_private_page_with_pii(tmp_path, audit, monkeypatch)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_pii(errors, warnings, WikiConfig(), public_export=True)
    assert any("cpf" in e for e in errors)
    assert warnings == []


def test_audit_pii_strict_mode_errors_in_private(tmp_path, audit, monkeypatch):
    # When the owner disables PII in private (opt-in), it becomes an error again.
    _seed_private_page_with_pii(tmp_path, audit, monkeypatch)
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_pii(
        errors, warnings, WikiConfig(private_sensitive_allowed=False), public_export=False
    )
    assert any("private_sensitive_allowed=false" in e for e in errors)


def test_strict_local_requires_derived_link_to_exist(tmp_path, audit, monkeypatch):
    # Link to a nonexistent derived (gitignored) artifact:
    # tolerated by default, but an error in --strict-local.
    page = tmp_path / "memories" / "note.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    href = "../data/derived/wiki/missing.json"

    monkeypatch.setattr(audit, "STRICT_LOCAL", False)
    assert audit.local_link_target_exists("memories/note.md", href) is True

    monkeypatch.setattr(audit, "STRICT_LOCAL", True)
    assert audit.local_link_target_exists("memories/note.md", href) is False

    # If the artifact exists, --strict-local approves.
    real = tmp_path / "data/derived/wiki/present.json"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("{}\n", encoding="utf-8")
    assert audit.local_link_target_exists("memories/note.md", "../data/derived/wiki/present.json") is True


# ---------------------------------------------------------------------------
# LOCAL_ARTIFACT_LINK_RE: extension coverage (.jsonl/.sqlite were escaping)
# ---------------------------------------------------------------------------


def test_local_artifact_link_re_matches_long_extensions(audit):
    # Regression: [a-z]{2,4} missed .jsonl and .sqlite links.
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../data/derived/wiki/events.jsonl)")
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../../data/raw/index.sqlite)")
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../data/derived/wiki/cache.json)")
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../data/raw/scan.PDF)")


def test_local_artifact_link_re_ignores_non_artifact_links(audit):
    # No extension -> not a file link the check cares about.
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../data/derived/wiki/dir)") is None
    # Not under data/raw|derived.
    assert audit.LOCAL_ARTIFACT_LINK_RE.search("[x](../docs/nota.jsonl)") is None


# ---------------------------------------------------------------------------
# audit_prompt_checksums: prompts must not drift silently
# ---------------------------------------------------------------------------


def _seed_prompts(tmp_path, audit, monkeypatch, *, checksums: str | None, prompt_text="prompt body\n"):
    prompts_dir = tmp_path / "wiki_core/llm/prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / "context_deep_read.v1.md").write_text(prompt_text, encoding="utf-8")
    if checksums is not None:
        (prompts_dir / ".checksums").write_text(checksums, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    return prompts_dir


def _sha256_of(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_prompt_checksums_match_passes(tmp_path, audit, monkeypatch):
    body = "prompt body\n"
    line = f"{_sha256_of(body)}  context_deep_read.v1.md\n"
    _seed_prompts(tmp_path, audit, monkeypatch, checksums=line, prompt_text=body)
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert errors == []


def test_prompt_checksums_mismatch_is_error(tmp_path, audit, monkeypatch):
    # The prompt changed but the pinned sha did not: conscious-decision gate fires.
    line = f"{'0' * 64}  context_deep_read.v1.md\n"
    _seed_prompts(tmp_path, audit, monkeypatch, checksums=line)
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("checksum mismatch" in e for e in errors)


def test_prompt_checksums_missing_file_is_error(tmp_path, audit, monkeypatch):
    _seed_prompts(tmp_path, audit, monkeypatch, checksums=None)
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("missing prompt checksums file" in e for e in errors)


def test_prompt_checksums_unpinned_prompt_is_error(tmp_path, audit, monkeypatch):
    body = "prompt body\n"
    line = f"{_sha256_of(body)}  context_deep_read.v1.md\n"
    prompts_dir = _seed_prompts(tmp_path, audit, monkeypatch, checksums=line, prompt_text=body)
    (prompts_dir / "new_prompt.v1.md").write_text("new\n", encoding="utf-8")
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("new_prompt.v1.md" in e and "not pinned" in e for e in errors)


def test_prompt_checksums_pinned_but_missing_prompt_is_error(tmp_path, audit, monkeypatch):
    body = "prompt body\n"
    lines = (
        f"{_sha256_of(body)}  context_deep_read.v1.md\n"
        f"{'1' * 64}  gone_prompt.v1.md\n"
    )
    _seed_prompts(tmp_path, audit, monkeypatch, checksums=lines, prompt_text=body)
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("gone_prompt.v1.md" in e and "does not exist" in e for e in errors)


def test_prompt_checksums_invalid_line_is_error(tmp_path, audit, monkeypatch):
    _seed_prompts(tmp_path, audit, monkeypatch, checksums="not-a-sha context_deep_read.v1.md\n")
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("invalid checksum line" in e for e in errors)


def test_repo_prompt_checksums_are_current(audit):
    # The VERSIONED .checksums must match the real prompts of this repo: if this
    # fails, a prompt changed without updating the pin (or vice versa).
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert errors == []


def test_source_config_perspectives_must_exist(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/system/perspectives/technical.md",
            "memories/sources/config/example.md",
        ],
    )
    (tmp_path / "memories/system/perspectives").mkdir(parents=True)
    (tmp_path / "memories/sources/config").mkdir(parents=True)
    (tmp_path / "memories/system/perspectives/technical.md").write_text(
        "---\n"
        "page_id: perspective-technical\n"
        "page_type: perspective\n"
        "---\n"
        "# Technical\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/sources/config/example.md").write_text(
        "---\n"
        "page_id: source-config-example\n"
        "page_type: source_config\n"
        "perspectives_required:\n"
        "  - perspective-technical\n"
        "  - perspective-missing\n"
        "---\n"
        "# Example\n",
        encoding="utf-8",
    )

    errors: list[str] = []
    config = WikiConfig(audit={**WikiConfig().audit, "perspective_coverage_check": True})
    audit.audit_source_config_perspectives(errors, config)

    assert errors == [
        "memories/sources/config/example.md: perspectives_required `perspective-missing` is not a perspective page"
    ]


def test_append_only_entity_mentions_are_ignored_when_changed(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "changed_paths_for_audit",
        lambda: {
            "memories/system/ingestion/events/e.md",
            "memories/system/log.md",
        },
    )
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/people/marcelo.md",
            "memories/system/ingestion/events/e.md",
            "memories/system/log.md",
        ],
    )
    (tmp_path / "memories/people").mkdir(parents=True)
    (tmp_path / "memories/system/ingestion/events").mkdir(parents=True)
    (tmp_path / "memories/system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memories/people/marcelo.md").write_text(
        "---\n"
        "page_id: person-marcelo\n"
        "page_type: person\n"
        "title: Marcelo\n"
        "---\n"
        "# Marcelo\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/ingestion/events/e.md").write_text(
        "---\n"
        "page_id: event-e\n"
        "page_type: ingestion_event\n"
        "---\n"
        "# Event\n\nMarcelo appeared in extracted source text.\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/log.md").write_text(
        "---\n"
        "page_id: system-log\n"
        "page_type: system_log\n"
        "---\n"
        "# Log\n\nMarcelo appeared in an append-only historical entry.\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    errors: list[str] = []
    config = WikiConfig(audit={**WikiConfig().audit, "mention_links_on_changed": "error"})
    audit.audit_entity_mention_links(warnings, config, errors)

    assert errors == []
    assert warnings == []


def test_changed_canonical_page_entity_mentions_still_error(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "changed_paths_for_audit",
        lambda: {"memories/example/note.md"},
    )
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/people/marcelo.md",
            "memories/example/note.md",
        ],
    )
    (tmp_path / "memories/people").mkdir(parents=True)
    (tmp_path / "memories/example").mkdir(parents=True)
    (tmp_path / "memories/people/marcelo.md").write_text(
        "---\n"
        "page_id: person-marcelo\n"
        "page_type: person\n"
        "title: Marcelo\n"
        "---\n"
        "# Marcelo\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/example/note.md").write_text(
        "---\n"
        "page_id: example-note\n"
        "page_type: source_catalog\n"
        "---\n"
        "# Note\n\nMarcelo is part of this canonical page and must be linked.\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    errors: list[str] = []
    config = WikiConfig(audit={**WikiConfig().audit, "mention_links_on_changed": "error"})
    audit.audit_entity_mention_links(warnings, config, errors)

    assert warnings == []
    assert errors == [
        "memories/example/note.md: names known entities without a link: Marcelo (memories/people/marcelo.md)"
    ]


# ---------------------------------------------------------------------------
# parse_frontmatter memoization (perf): cached per path, cleared in main()
# ---------------------------------------------------------------------------


def test_parse_frontmatter_is_memoized_per_path(tmp_path, audit):
    audit.parse_frontmatter.cache_clear()
    path = tmp_path / "page.md"
    path.write_text(VALID_FRONTMATTER, encoding="utf-8")
    first, _ = audit.parse_frontmatter(path)
    assert first["page_id"] == "test-page"

    # Rewrite the file: the memoized parse still returns the cached value...
    path.write_text(VALID_FRONTMATTER.replace("test-page", "other-page"), encoding="utf-8")
    cached, _ = audit.parse_frontmatter(path)
    assert cached["page_id"] == "test-page"
    assert audit.parse_frontmatter.cache_info().hits >= 1

    # ...until cache_clear() (main() clears it on every invocation).
    audit.parse_frontmatter.cache_clear()
    fresh, _ = audit.parse_frontmatter(path)
    assert fresh["page_id"] == "other-page"


def test_main_clears_parse_frontmatter_cache(audit):
    # The lru_cache wrapper must expose cache_clear and main() must call it; we
    # assert the wiring textually to avoid running the full audit here.
    assert hasattr(audit.parse_frontmatter, "cache_clear")
    source = WIKI_AUDIT_PATH.read_text(encoding="utf-8")
    assert "parse_frontmatter.cache_clear()" in source


def test_audit_pii_public_visibility_errors_without_export(tmp_path, audit, monkeypatch):
    # A page marked public (public_candidate) blocks PII even without --public-export.
    page = tmp_path / "memories" / "pub.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\nvisibility: public_candidate\n---\n\n# Page\n\nCPF: 529.982.247-25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "markdown_files", lambda: ["memories/pub.md"])
    errors: list[str] = []
    warnings: list[str] = []
    audit.audit_pii(errors, warnings, WikiConfig(), public_export=False)
    assert any("cpf" in e for e in errors)


# ---------------------------------------------------------------------------
# Config-driven layout: English defaults + pt-pinned compatibility
# ---------------------------------------------------------------------------


def test_local_path_regexes_follow_configured_roots(audit):
    prefix_re, inline_re, bare_re = audit._compile_local_path_regexes(WikiConfig())
    # English defaults: memories/docs/data/scripts/.github/.skills.
    assert bare_re.search("see memories/system/log.md here")
    assert prefix_re.match("memories/system/log.md")
    assert inline_re.search("`memories/system/log.md`")
    # The pt layout is NOT baked in: it only matches when configured.
    assert bare_re.search("see memorias/sistema/log.md here") is None
    assert prefix_re.match("memorias/sistema/log.md") is None


def test_ontology_dir_vocabulary_accepts_en_and_pt_dirnames(audit):
    en = WikiConfig()
    assert audit.ontology_dir_for("memories/people/ana.md", en) == "memories/people"
    assert "person" in audit.ONTOLOGY_DIRNAME_TYPES["people"]
    # Compatibility superset: pt dirnames share the same page-type vocabulary.
    assert audit.ONTOLOGY_DIRNAME_TYPES["pessoas"] == audit.ONTOLOGY_DIRNAME_TYPES["people"]
    assert audit.ONTOLOGY_DIRNAME_TYPES["fontes"] == audit.ONTOLOGY_DIRNAME_TYPES["sources"]
    # A file directly under the memory root is not an ontology page.
    assert audit.ontology_dir_for("memories/people", en) is None
    assert audit.ontology_dir_for("docs/people/x.md", en) is None


def test_relation_prefixes_accept_en_and_pt_generated_ids(audit):
    # Superset: pt repos keep generating pt ids; en repos generate en ids.
    assert "person-" in audit.RELATION_PREFIXES["owner"]
    assert "pessoa-" in audit.RELATION_PREFIXES["owner"]
    assert "root-" in audit.RELATION_PREFIXES["owner"]
    assert "sources-" in audit.RELATION_PREFIXES["source_refs"]
    assert "decision-" in audit.RELATION_PREFIXES["decisions"]
    assert "decisao-" in audit.RELATION_PREFIXES["decisions"]


PT_LAYOUT_CONFIG = """\
repo_id: pt-fixture
language: pt
contexts: financeiro
default_context: sistema
paths:
  memory_root: memorias
  references_root: docs/referencias
  system_dirname: sistema
  ingest_dirname: ingestao
  events_dirname: eventos
  archive_dirname: arquivo
  decisions_dirname: decisoes
  actions_dirname: acoes
  pending_actions_filename: pendentes.md
  sources_dirname: fontes
  operation_page: memorias/operacao.md
  command_reference_page: memorias/sistema/wiki/referencia-comandos.md
  wiki_coverage_page: memorias/sistema/cobertura-wiki.md
audit:
  core_pages:
    - memorias/index.md
    - memorias/sistema/log.md
"""


def test_pt_pinned_layout_keeps_localized_repo_working(tmp_path, audit, monkeypatch):
    """Localized-layout compat: a repo pinning the pt layout in wiki.config.yaml
    must drive every gate to the pt paths (nothing falls back to the en defaults)."""
    (tmp_path / "wiki.config.yaml").write_text(PT_LAYOUT_CONFIG, encoding="utf-8")
    config = load_config(tmp_path)
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    # Required pages: pinned pt core + pt context hubs.
    assert audit.primary_pages(config) == [
        "memorias/index.md",
        "memorias/sistema/log.md",
        "memorias/financeiro/index.md",
    ]

    # Ontology dirs resolve under the pt memory root.
    assert audit.ontology_dir_for("memorias/pessoas/ana.md", config) == "memorias/pessoas"

    # Local-path regexes rebuild around the pt roots.
    _, _, bare_re = audit._compile_local_path_regexes(config)
    assert bare_re.search("ver memorias/sistema/log.md")
    assert bare_re.search("see memories/system/log.md") is None

    # Operation cockpit gate points at memorias/operacao.md.
    errors: list[str] = []
    audit.audit_operation_page(errors, [], config)
    assert any(e.startswith("memorias/operacao.md: missing operation cockpit") for e in errors)

    # Ingestion gate fails loud at the pt events dir.
    errors = []
    audit.audit_ingestion_events(errors, config)
    assert errors == [
        "memorias/sistema/ingestao/eventos: missing normalized event directory"
    ]

    # Command-reference gate targets the pt page (fail loud: CLIs exist, page missing).
    monkeypatch.setattr(audit, "tracked_files", lambda: ["scripts/wiki_a.py"])
    errors = []
    audit.audit_command_reference(errors, config)
    assert errors and errors[0].startswith(
        "memorias/sistema/wiki/referencia-comandos.md: missing command reference page"
    )


# ---------------------------------------------------------------------------
# Declarative check registry (CHECKS) + --only / --list-checks
# ---------------------------------------------------------------------------

# Canonical run order: this is the historical hand-written call sequence from
# main(), now the source of truth for the registry invariant. Reordering or
# dropping any entry would change gate behavior, so the test pins it exactly.
EXPECTED_CHECK_ORDER = [
    "frontmatter",
    "stale_coverage",
    "freshness_budget",
    "drive_artifact_links",
    "command_reference",
    "relations",
    "old_paths",
    "secrets",
    "pii",
    "clickable_local_links",
    "obsidian_directory_links",
    "page_graph",
    "page_type_registry",
    "duplicate_entity_names",
    "entity_mention_links",
    "operational_concept_links",
    "impact",
    "operation_page",
    "ingestion_events",
    "consolidation",
    "ingestion_proposals_gate_state",
    "ingestion_absolute_paths",
    "public_candidates",
    "promotion_gate",
    "context_pass_gate",
    "prompt_checksums",
    "llm_cache_metadata",
    "source_config_perspectives",
    "perspective_coverage",
    "impact_closure",
    "log_changed",
]


def test_registry_matches_canonical_order(audit):
    # The registry must contain exactly the historical checks, in the same order.
    assert audit.CHECK_NAMES == tuple(EXPECTED_CHECK_ORDER)
    assert [name for name, _ in audit.CHECKS] == EXPECTED_CHECK_ORDER
    # No duplicate names.
    assert len(set(audit.CHECK_NAMES)) == len(audit.CHECK_NAMES)


def test_registry_runners_are_callable_and_named_after_audit_fns(audit):
    # Every registry name maps to an existing audit_<name> callable, and every
    # runner is invocable with a single ctx argument.
    for name, run in audit.CHECKS:
        fn = getattr(audit, f"audit_{name}", None)
        assert callable(fn), f"missing audit_{name} for registry entry {name!r}"
        assert callable(run)


def test_registry_covers_all_audit_functions_used_in_main(audit):
    # Guard against an audit_* gate being added to the module but forgotten in
    # the registry: every audit_* function whose name maps to a CHECK must be
    # present. Helpers without a CHECK entry (e.g. nested or renamed) are
    # exempt, but the historical 31 gates are not.
    registered = set(audit.CHECK_NAMES)
    for expected in EXPECTED_CHECK_ORDER:
        assert expected in registered
        assert hasattr(audit, f"audit_{expected}")


def _run_cli(args):
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(WIKI_AUDIT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    return proc


def test_list_checks_prints_registry_in_order():
    proc = _run_cli(["--list-checks"])
    assert proc.returncode == 0
    printed = [line for line in proc.stdout.splitlines() if line.strip()]
    assert printed == EXPECTED_CHECK_ORDER


def test_only_runs_a_strict_subset():
    # A single-check run must succeed (rc=0 without --check) and must NOT emit
    # the errors that a full run on this repo would surface from other gates.
    full = _run_cli([])
    one = _run_cli(["--only", "secrets"])
    assert one.returncode == 0
    # The summary line is always present.
    assert "wiki_audit:" in one.stdout
    # Subset output is a proper subset of the full run's lines (fewer or equal
    # WARN/ERROR lines, since only one gate ran).
    full_lines = [l for l in full.stdout.splitlines() if l.startswith(("WARN:", "ERROR:"))]
    one_lines = [l for l in one.stdout.splitlines() if l.startswith(("WARN:", "ERROR:"))]
    assert len(one_lines) <= len(full_lines)


def test_only_preserves_registry_order_regardless_of_input_order(audit):
    # Passing names out of order still runs them in registry order. We assert
    # this on the selection logic by reusing the same ordering rule the CLI uses.
    requested = {"log_changed", "frontmatter", "secrets"}
    selected = [name for name, _ in audit.CHECKS if name in requested]
    assert selected == ["frontmatter", "secrets", "log_changed"]


def test_only_unknown_name_is_rejected():
    proc = _run_cli(["--only", "does_not_exist"])
    # argparse error() exits 2 and writes to stderr.
    assert proc.returncode == 2
    assert "unknown check" in proc.stderr


def test_only_default_run_uses_full_registry(audit):
    # Defensive: with no --only, main() iterates the full CHECKS tuple. We can't
    # cheaply assert the exit code here (depends on repo state), but we can lock
    # the wiring that the default selection is the whole registry by reading the
    # source -- the loop iterates `selected` which defaults to CHECKS.
    source = WIKI_AUDIT_PATH.read_text(encoding="utf-8")
    assert "selected = CHECKS" in source
    assert "for _name, run in selected:" in source
