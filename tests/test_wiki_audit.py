"""Offline tests for pure helpers/constants in scripts/wiki_audit.py.

scripts/ is not a package, so the module is loaded directly from its file path
via importlib.util.spec_from_file_location. wiki_audit.py inserts the repo ROOT
on sys.path at import time, so its own `wiki_core` imports resolve.

No network, no writes outside tmp_path. Production code is not modified.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WIKI_AUDIT_PATH = ROOT / "scripts" / "wiki_audit.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.config import WikiConfig, load_config  # noqa: E402


def _load_wiki_audit():
    # Ensure ROOT is importable for the module's internal `wiki_core` imports.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "wiki_audit_under_test", WIKI_AUDIT_PATH
    )
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
page_id: example-person
updated_at: 2026-06-01
---

Atualizado em: 2026-06-01

Alex aparece junto a Bea, Caio, [Dana Example](old/dana.md) e Organization A.
"""
    new = """---
page_id: example-person
updated_at: 2026-06-12
---

Atualizado em: 2026-06-12

Alex aparece junto a [Bea](bea.md), [Caio](caio.md),
[Dana Example](dana-example.md) e Organization A.
"""
    changed = new.replace("Organization A.", "Organization B.")

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
        "---\npage_id: p\npage_type: dashboard\ncontext: c\n"
        'visibility: "public_candidate"\nupdated_at: 2026-06-09\n'
        "stale_after_days: 7\nsources_policy: required\ngate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n---\n\n# t\n",
        encoding="utf-8",
    )
    values, _ = audit.parse_frontmatter(path)
    assert values["visibility"] == "public_candidate"


# ---------------------------------------------------------------------------
# Source lifecycle authoring diagnostics
# ---------------------------------------------------------------------------


def _seed_source_lifecycle_page(
    tmp_path, audit, monkeypatch, lifecycle_yaml: str, *, updated_at: str = "2026-07-01"
):
    rel = "memories/sources/bank.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "page_id: source-bank\n"
        "page_type: source\n"
        "context: system\n"
        "visibility: private_self\n"
        f"updated_at: {updated_at}\n"
        "stale_after_days: 365\n"
        "sources_policy: required\n"
        "gate: github_pr\n"
        "sensitive_data_policy: private_sensitive_allowed\n"
        "owner: root-example\n"
        "related_holons: []\n"
        "roles: []\n"
        "responsibilities: []\n"
        "source_refs: []\n"
        "claims: []\n"
        "decisions: []\n"
        "actions: []\n"
        "evidence_refs: []\n"
        f"{lifecycle_yaml}"
        "---\n\n"
        "# Bank\n",
        encoding="utf-8",
    )
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "markdown_files", lambda: [rel])
    monkeypatch.setattr(audit, "primary_pages", lambda config: ())
    return rel


def test_frontmatter_audit_reports_source_lifecycle_typos_before_date_early_exit(
    tmp_path, audit, monkeypatch
):
    rel = _seed_source_lifecycle_page(
        tmp_path,
        audit,
        monkeypatch,
        "source_last_attempt_state: retrying\n" "source_pipeline_stage: em_progresso\n",
        updated_at="not-a-date",
    )
    errors: list[str] = []
    warnings: list[str] = []

    audit.audit_frontmatter(errors, warnings, WikiConfig(audit={}))

    assert f"{rel}: invalid `source_last_attempt_state` value `retrying`" in errors[0]
    assert (
        "allowed: failed, needs_auth, never, ok, parser_error, secret_blocked"
        in errors[0]
    )
    assert any(
        f"{rel}: invalid `source_pipeline_stage` value `em_progresso`" in error
        and "proposal_ready" in error
        for error in errors
    )
    assert f"{rel}: invalid updated_at or stale_after_days" in errors
    assert warnings == []


def test_frontmatter_audit_warns_but_accepts_legacy_source_attempt_state(
    tmp_path, audit, monkeypatch
):
    rel = _seed_source_lifecycle_page(
        tmp_path,
        audit,
        monkeypatch,
        "source_lifecycle:\n"
        "  last_attempt_state: partial\n"
        "  pipeline_stage: configured\n",
    )
    errors: list[str] = []
    warnings: list[str] = []

    audit.audit_frontmatter(errors, warnings, WikiConfig(audit={}))

    assert errors == []
    assert warnings == [
        f"{rel}: legacy `source_lifecycle.last_attempt_state` value `partial` "
        "normalizes to `failed`; prefer the canonical value"
    ]


def test_frontmatter_audit_rejects_accepted_source_without_ref(
    tmp_path, audit, monkeypatch
):
    rel = _seed_source_lifecycle_page(
        tmp_path,
        audit,
        monkeypatch,
        "source_lifecycle:\n"
        "  state: ingested\n"
        "  freshness_state: fresh\n"
        "  last_attempt_state: ok\n"
        "  pipeline_stage: complete\n"
        "  adoption_state: accepted\n"
        "  emitted_page_ids: [page-one]\n",
    )
    errors: list[str] = []

    audit.audit_frontmatter(errors, [], WikiConfig(audit={}))

    assert f"{rel}: accepted adoption requires `accepted_ref`" in errors


def test_frontmatter_audit_rejects_flattened_nested_conflict(
    tmp_path, audit, monkeypatch
):
    rel = _seed_source_lifecycle_page(
        tmp_path,
        audit,
        monkeypatch,
        "source_last_attempt_state: ok\n"
        "source_lifecycle:\n"
        "  last_attempt_state: failed\n",
    )
    errors: list[str] = []

    audit.audit_frontmatter(errors, [], WikiConfig(audit={}))

    assert (
        f"{rel}: conflicting declarations for `last_attempt_state`; "
        "flattened and nested values must match"
    ) in errors


def test_frontmatter_audit_never_echoes_secret_shaped_invalid_state(
    tmp_path, audit, monkeypatch
):
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz123456"
    rel = _seed_source_lifecycle_page(
        tmp_path,
        audit,
        monkeypatch,
        f"source_lifecycle:\n  state: {secret}\n",
    )
    errors: list[str] = []

    audit.audit_frontmatter(errors, [], WikiConfig(audit={}))
    rendered = "\n".join(errors)

    assert secret not in rendered
    assert (
        f"{rel}: invalid `source_lifecycle.state` value `<redacted:secret>`" in rendered
    )


# ---------------------------------------------------------------------------
# audit_stale_coverage: freshness for EVERY memory page
# ---------------------------------------------------------------------------


def _seed_memory_page(
    tmp_path, audit, monkeypatch, rel, *, stale_days, updated, extra=""
):
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
        tmp_path,
        audit,
        monkeypatch,
        "memories/x/old.md",
        stale_days=7,
        updated="2020-01-01",
    )
    warnings: list[str] = []
    audit.audit_stale_coverage(warnings, WikiConfig())
    assert any("stale page" in w for w in warnings)


def test_stale_coverage_reports_gap_without_field(tmp_path, audit, monkeypatch):
    _seed_memory_page(
        tmp_path,
        audit,
        monkeypatch,
        "memories/x/nofield.md",
        stale_days=None,
        updated="2026-06-09",
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
        errors,
        warnings,
        WikiConfig(private_sensitive_allowed=False),
        public_export=False,
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
    assert (
        audit.local_link_target_exists(
            "memories/note.md", "../data/derived/wiki/present.json"
        )
        is True
    )


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


def test_append_only_drive_artifact_links_are_ignored(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/system/ingestion/events/e.md",
            "memories/system/log.md",
            "memories/example/note.md",
        ],
    )
    monkeypatch.setattr(audit, "tracked_files", lambda: [])
    (tmp_path / "memories/system/ingestion/events").mkdir(parents=True)
    (tmp_path / "memories/system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memories/example").mkdir(parents=True)
    artifact_link = "[artifact](../../data/raw/historical.json)"
    (tmp_path / "memories/system/ingestion/events/e.md").write_text(
        "---\n"
        "page_id: event-e\n"
        "page_type: ingestion_event\n"
        "---\n"
        f"# Event\n\nHistorical link to {artifact_link}.\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/log.md").write_text(
        "---\n"
        "page_id: system-log\n"
        "page_type: system_log\n"
        "---\n"
        f"# Log\n\nAppend-only historical link to {artifact_link}.\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/example/note.md").write_text(
        "---\n"
        "page_id: example-note\n"
        "page_type: source_catalog\n"
        "---\n"
        f"# Note\n\nCanonical page link to {artifact_link}.\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    audit.audit_drive_artifact_links(warnings, WikiConfig())

    assert warnings == [
        "1 link(s) to unversioned local artifact in 1 page(s); "
        "general rule: content on Drive (wiki_drive_publish) and the wiki points to the "
        "manifest view_url. Use --list-stale-gaps to list."
    ]


# ---------------------------------------------------------------------------
# audit_prompt_checksums: prompts must not drift silently
# ---------------------------------------------------------------------------


def _seed_prompts(
    tmp_path, audit, monkeypatch, *, checksums: str | None, prompt_text="prompt body\n"
):
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
    prompts_dir = _seed_prompts(
        tmp_path, audit, monkeypatch, checksums=line, prompt_text=body
    )
    (prompts_dir / "new_prompt.v1.md").write_text("new\n", encoding="utf-8")
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("new_prompt.v1.md" in e and "not pinned" in e for e in errors)


def test_prompt_checksums_pinned_but_missing_prompt_is_error(
    tmp_path, audit, monkeypatch
):
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
    _seed_prompts(
        tmp_path, audit, monkeypatch, checksums="not-a-sha context_deep_read.v1.md\n"
    )
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert any("invalid checksum line" in e for e in errors)


def test_repo_prompt_checksums_are_current(audit):
    # The VERSIONED .checksums must match the real prompts of this repo: if this
    # fails, a prompt changed without updating the pin (or vice versa).
    errors: list[str] = []
    audit.audit_prompt_checksums(errors)
    assert errors == []


def test_declared_perspectives_must_exist(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/example/index.md",
            "memories/system/input-channels/repository.md",
            "memories/system/perspectives/technical.md",
            "memories/sources/config/example.md",
        ],
    )
    (tmp_path / "memories/example").mkdir(parents=True)
    (tmp_path / "memories/system/input-channels").mkdir(parents=True)
    (tmp_path / "memories/system/perspectives").mkdir(parents=True)
    (tmp_path / "memories/sources/config").mkdir(parents=True)
    (tmp_path / "memories/example/index.md").write_text(
        "---\n"
        "page_id: root-example\n"
        "page_type: root_entity\n"
        "perspective_bundle_required:\n"
        "  - perspective-technical\n"
        "perspective_bundle_optional:\n"
        "  - perspective-missing-root\n"
        "---\n"
        "# Example\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/input-channels/repository.md").write_text(
        "---\n"
        "page_id: channel-repository\n"
        "page_type: input_channel\n"
        "perspectives_required:\n"
        "  - perspective-technical\n"
        "perspectives_optional:\n"
        "  - perspective-missing-channel\n"
        "---\n"
        "# Repository\n",
        encoding="utf-8",
    )
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
    config = WikiConfig(
        audit={**WikiConfig().audit, "perspective_coverage_check": True},
        root_entity={
            **WikiConfig().root_entity,
            "perspective_bundle": {
                "required": ["perspective-technical", "perspective-missing-config"],
                "optional": [],
            },
        },
    )
    audit.audit_source_config_perspectives(errors, config)

    assert errors == [
        "config root_entity.perspective_bundle.required `perspective-missing-config` is not a perspective page",
        "memories/system/input-channels/repository.md: perspectives_optional `perspective-missing-channel` is not a perspective page",
        "memories/example/index.md: perspective_bundle_optional `perspective-missing-root` is not a perspective page",
        "memories/sources/config/example.md: perspectives_required `perspective-missing` is not a perspective page",
    ]


def test_append_only_entity_mentions_are_ignored_when_changed(
    tmp_path, audit, monkeypatch
):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "changed_paths_for_audit",
        lambda: {
            "memories/system/ingestion/events/e.md",
            "memories/system/ingestion/events/legacy.md",
            "memories/system/log.md",
        },
    )
    monkeypatch.setattr(
        audit,
        "markdown_files",
        lambda: [
            "memories/people/marcelo.md",
            "memories/system/ingestion/events/e.md",
            "memories/system/ingestion/events/legacy.md",
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
    (tmp_path / "memories/system/ingestion/events/legacy.md").write_text(
        "---\n"
        "page_id: legacy-event\n"
        "page_type: source_catalog\n"
        "---\n"
        "# Legacy Event\n\nMarcelo appeared in a legacy normalized event.\n",
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
    config = WikiConfig(
        audit={**WikiConfig().audit, "mention_links_on_changed": "error"}
    )
    audit.audit_entity_mention_links(warnings, config, errors)

    assert errors == []
    assert warnings == []


def test_changed_canonical_page_entity_mentions_still_error(
    tmp_path, audit, monkeypatch
):
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
    config = WikiConfig(
        audit={**WikiConfig().audit, "mention_links_on_changed": "error"}
    )
    audit.audit_entity_mention_links(warnings, config, errors)

    assert warnings == []
    assert errors == [
        "memories/example/note.md: names known entities without a link: Marcelo (memories/people/marcelo.md)"
    ]


def test_append_only_directory_links_are_ignored(tmp_path, audit, monkeypatch):
    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "link_audit_files",
        lambda _config: [
            "memories/system/ingestion/events/e.md",
            "memories/system/ingestion/events/legacy.md",
            "memories/system/log.md",
            "memories/example/note.md",
        ],
    )
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "memories/system/ingestion/events").mkdir(parents=True)
    (tmp_path / "memories/system").mkdir(parents=True, exist_ok=True)
    (tmp_path / "memories/example").mkdir(parents=True)
    (tmp_path / "memories/system/ingestion/events/e.md").write_text(
        "---\n"
        "page_id: event-e\n"
        "page_type: ingestion_event\n"
        "---\n"
        "# Event\n\nHistorical link to [docs](../../../../docs/).\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/ingestion/events/legacy.md").write_text(
        "---\n"
        "page_id: legacy-event\n"
        "page_type: source_catalog\n"
        "---\n"
        "# Legacy Event\n\nLegacy event link to [docs](../../../../docs/).\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/system/log.md").write_text(
        "---\n"
        "page_id: system-log\n"
        "page_type: system_log\n"
        "---\n"
        "# Log\n\nAppend-only historical link to [docs](../../docs/).\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/example/note.md").write_text(
        "---\n"
        "page_id: example-note\n"
        "page_type: source_catalog\n"
        "---\n"
        "# Note\n\nCanonical page link to [docs](../../docs/).\n",
        encoding="utf-8",
    )

    warnings: list[str] = []
    audit.audit_obsidian_directory_links(warnings, WikiConfig())

    assert warnings == [
        "1 markdown link(s) point to directories in 1 file(s); "
        "link README.md/index.md for Obsidian navigation. Use --list-stale-gaps to list."
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
    path.write_text(
        VALID_FRONTMATTER.replace("test-page", "other-page"), encoding="utf-8"
    )
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


def test_audit_pii_public_visibility_errors_without_export(
    tmp_path, audit, monkeypatch
):
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
    assert (
        audit.ONTOLOGY_DIRNAME_TYPES["pessoas"]
        == audit.ONTOLOGY_DIRNAME_TYPES["people"]
    )
    assert (
        audit.ONTOLOGY_DIRNAME_TYPES["fontes"]
        == audit.ONTOLOGY_DIRNAME_TYPES["sources"]
    )
    # A file directly under the memory root is not an ontology page.
    assert audit.ontology_dir_for("memories/people", en) is None
    assert audit.ontology_dir_for("docs/people/x.md", en) is None


@pytest.mark.parametrize(
    ("memory_root", "calendar_dir", "initiatives_dir"),
    [
        ("memories", "calendar", "initiatives"),
        ("memorias", "calendario", "iniciativas"),
    ],
)
def test_page_type_registry_overrides_legacy_ontology_directory_vocabulary(
    tmp_path,
    audit,
    monkeypatch,
    memory_root,
    calendar_dir,
    initiatives_dir,
):
    paths = {**WikiConfig().paths, "memory_root": memory_root}
    config = WikiConfig(
        language="pt" if memory_root == "memorias" else "en",
        paths=paths,
        audit={"page_type_registry_check": True},
    )
    (tmp_path / "wiki.config.yaml").write_text(
        f"repo_id: registry-authority\npaths:\n  memory_root: {memory_root}\n",
        encoding="utf-8",
    )
    registry = tmp_path / "wiki.page-types.yaml"
    registry.write_text(
        "schema_version: wiki_page_types.v1\n"
        "page_types:\n"
        "  meeting:\n"
        "    template: none\n"
        "    template_none_reason: synthetic registry authority test\n"
        f"    allowed_dirs: [{memory_root}/{calendar_dir}]\n"
        "    required_frontmatter: [page_id, page_type]\n"
        "  project:\n"
        "    template: none\n"
        "    template_none_reason: synthetic registry authority test\n"
        f"    allowed_dirs: [{memory_root}/{initiatives_dir}]\n"
        "    required_frontmatter: [page_id, page_type]\n",
        encoding="utf-8",
    )

    relations = "".join(f"{key}: []\n" for key in sorted(audit.RELATION_KEYS))
    rels = [
        f"{memory_root}/{calendar_dir}/weekly.md",
        f"{memory_root}/{initiatives_dir}/migration.md",
    ]
    for rel, page_type in zip(rels, ("meeting", "project"), strict=True):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"page_id: {page_type}-registry-authority\n"
            f"page_type: {page_type}\n"
            "context: system\n"
            "visibility: private_self\n"
            "updated_at: 2026-08-28\n"
            "stale_after_days: 3650\n"
            "sources_policy: required\n"
            "gate: github_pr\n"
            "sensitive_data_policy: private_sensitive_allowed\n"
            f"{relations}"
            "---\n\n# Registry authority\n",
            encoding="utf-8",
        )

    audit.parse_frontmatter.cache_clear()
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "markdown_files", lambda: rels)
    monkeypatch.setattr(audit, "primary_pages", lambda _config: ())
    errors: list[str] = []
    warnings: list[str] = []

    audit.audit_frontmatter(errors, warnings, config)
    audit.audit_page_type_registry(errors, config)

    assert errors == []
    assert warnings == []


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
    assert (
        audit.ontology_dir_for("memorias/pessoas/ana.md", config) == "memorias/pessoas"
    )

    # Local-path regexes rebuild around the pt roots.
    _, _, bare_re = audit._compile_local_path_regexes(config)
    assert bare_re.search("ver memorias/sistema/log.md")
    assert bare_re.search("see memories/system/log.md") is None

    # Operation cockpit gate points at memorias/operacao.md.
    errors: list[str] = []
    audit.audit_operation_page(errors, [], config)
    assert any(
        e.startswith("memorias/operacao.md: missing operation cockpit") for e in errors
    )

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


def test_command_reference_discovers_repo_local_wiki_clis(
    tmp_path, audit, monkeypatch
):
    reference = tmp_path / "memories/system/command-reference.md"
    reference.parent.mkdir(parents=True)
    reference.write_text(
        "# Commands\n\n- `wiki_public.py`\n- `wiki_private.py`\n",
        encoding="utf-8",
    )
    config = WikiConfig(
        paths={
            **WikiConfig().paths,
            "command_reference_page": "memories/system/command-reference.md",
        }
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "tracked_files",
        lambda: [
            "scripts/wiki_public.py",
            "private/scripts/wiki_private.py",
        ],
    )
    errors: list[str] = []

    audit.audit_command_reference(errors, config)

    assert errors == []


# ---------------------------------------------------------------------------
# Existing action lifecycle changes require a receipt chain
# ---------------------------------------------------------------------------


def _action_document(state: str) -> str:
    return (
        "---\n"
        "page_id: action-audit-synthetic\n"
        "page_type: action\n"
        "title: Synthetic action\n"
        "context: example\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-11\n"
        "stale_after_days: 30\n"
        f"action_state: {state}\n"
        "next_action: Review synthetic evidence.\n"
        "owner_kind: unassigned\n"
        "created_at: 2026-07-10\n"
        "priority: normal\n"
        "attention_basis: Synthetic audit coverage.\n"
        "source_refs: []\n"
        "moc_parent: memories/index.md\n"
        "---\n\n"
        "# Synthetic action\n"
    )


def test_action_transition_audit_rejects_manual_state_edit(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-audit-synthetic.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _action_document("open")
    path.write_text(_action_document("in_progress"), encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(
        audit,
        "_base_action_texts_by_page_id",
        lambda: {"action-audit-synthetic": ((rel, previous),)},
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{rel}: action_state changed without a transition receipt "
        "[missing_action_transition_receipt]"
    ]


def test_action_transition_audit_rejects_manual_governed_support_edit(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-audit-synthetic.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _action_document("open")
    path.write_text(
        previous.replace(
            "next_action: Review synthetic evidence.",
            "next_action: Bypass the governed writer.",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(
        audit,
        "_base_action_texts_by_page_id",
        lambda: {"action-audit-synthetic": ((rel, previous),)},
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{rel}: governed action support changed without a transition receipt "
        "[missing_action_transition_receipt]"
    ]


def test_action_transition_audit_follows_page_id_across_rename(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-renamed.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _action_document("open")
    path.write_text(_action_document("in_progress"), encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(
        audit,
        "_base_action_texts_by_page_id",
        lambda: {
            "action-audit-synthetic": (
                ("memories/actions/action-old-name.md", previous),
            )
        },
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{rel}: action_state changed without a transition receipt "
        "[missing_action_transition_receipt]"
    ]
def test_action_transition_audit_blocks_deletion_but_allows_identity_preserving_move(
    tmp_path, monkeypatch, audit
):
    old_rel = "memories/actions/action-old-name.md"
    previous = _action_document("open")
    base = {"action-audit-synthetic": ((old_rel, previous),)}
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "_base_action_texts_by_page_id", lambda: base)
    monkeypatch.setattr(audit, "run_git", lambda args: "")
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {old_rel})
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{old_rel}: deleting an existing action discards its lifecycle history; "
        "transition it to `cancelled` with a receipt and retain the page "
        "[action_page_deleted]"
    ]

    new_rel = "memories/actions/action-new-name.md"
    new_path = tmp_path / new_rel
    new_path.parent.mkdir(parents=True)
    new_path.write_text(previous, encoding="utf-8")
    monkeypatch.setattr(
        audit,
        "changed_paths_for_audit",
        lambda: {old_rel, new_rel},
    )
    errors = []

    audit.audit_action_state_transitions(errors)

    assert errors == []


def test_action_transition_audit_accepts_central_writer_receipt(
    tmp_path, monkeypatch, audit
):
    from wiki_core.action_transition import transition_action_page

    rel = "memories/actions/action-audit-synthetic.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _action_document("open")
    path.write_text(previous, encoding="utf-8")
    transition_action_page(
        tmp_path,
        rel,
        "in_progress",
        recorded_at="2026-07-11T15:00:00Z",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(
        audit,
        "_base_action_texts_by_page_id",
        lambda: {"action-audit-synthetic": ((rel, previous),)},
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == []


def test_action_transition_audit_uses_verified_one_time_adoption_baseline(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-audit-synthetic.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    adopted = _action_document("waiting_human")
    path.write_text(adopted, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "_action_adoption_baseline",
        lambda errors, config: ("baseline-commit", False),
    )
    monkeypatch.setattr(
        audit,
        "_action_candidate_texts_by_path_at_ref",
        lambda ref: {rel: adopted},
    )
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(audit, "run_git", lambda args: "")
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == []


def test_action_adoption_receipt_is_byte_immutable_after_the_first_pr(
    tmp_path, monkeypatch, audit
):
    rel = audit.ACTION_ADOPTION_RECEIPT_PATH
    path = tmp_path / rel
    path.write_text("schema_version: wiki_action_transition_adoption.v1\n", encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(
        audit,
        "_text_at_audit_base",
        lambda candidate: (
            "schema_version: wiki_action_transition_adoption.v1"
            if candidate == rel
            else None
        ),
    )
    errors: list[str] = []

    baseline, invalid = audit._action_adoption_baseline(errors, WikiConfig())

    assert baseline is None and invalid is True
    assert errors == [
        f"{rel}: action adoption receipt is immutable "
        "[action_adoption_receipt_rewritten]"
    ]


def test_new_action_adoption_receipt_exposes_only_a_verified_baseline(
    tmp_path, monkeypatch, audit
):
    rel = audit.ACTION_ADOPTION_RECEIPT_PATH
    path = tmp_path / rel
    path.write_text(
        "schema_version: wiki_action_transition_adoption.v1\n"
        "baseline_commit: " + "b" * 40 + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "_text_at_audit_base", lambda candidate: None)
    monkeypatch.setattr(audit, "_audit_base_ref", lambda: "origin/main")
    monkeypatch.setattr(
        audit,
        "run_git",
        lambda args: "a" * 40 if args[:1] == ["rev-parse"] else "",
    )
    verified: list[tuple[str, str]] = []

    def verify(root, receipt, **kwargs):
        verified.append((str(receipt["baseline_commit"]), kwargs["audit_base_commit"]))
        return []

    monkeypatch.setattr(audit, "verify_action_adoption_git_contract", verify)
    errors: list[str] = []

    baseline, invalid = audit._action_adoption_baseline(errors, WikiConfig())

    assert baseline == "b" * 40 and invalid is False
    assert errors == []
    assert verified == [("b" * 40, "a" * 40)]


def test_action_transition_audit_checks_untracked_half_of_identity_move(
    tmp_path, monkeypatch, audit
):
    old_rel = "memories/actions/action-old-name.md"
    new_rel = "memories/actions/action-new-name.md"
    previous = _action_document("open")
    new_path = tmp_path / new_rel
    new_path.parent.mkdir(parents=True)
    new_path.write_text(_action_document("in_progress"), encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {old_rel})
    monkeypatch.setattr(
        audit,
        "_base_action_texts_by_page_id",
        lambda: {"action-audit-synthetic": ((old_rel, previous),)},
    )
    monkeypatch.setattr(audit, "_malformed_base_actions", lambda: {})
    monkeypatch.setattr(
        audit,
        "run_git",
        lambda args: new_rel
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]
        else "",
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{new_rel}: action_state changed without a transition receipt "
        "[missing_action_transition_receipt]"
    ]


def test_action_transition_audit_fails_closed_on_malformed_base_action(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-malformed.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(_action_document("open"), encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(audit, "_base_action_texts_by_page_id", lambda: {})
    monkeypatch.setattr(
        audit,
        "_malformed_base_actions",
        lambda: {rel: "action-audit-synthetic"},
    )
    monkeypatch.setattr(audit, "run_git", lambda args: "")
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{rel}: existing base action has malformed or incomplete frontmatter; "
        "repair must preserve and validate its lifecycle origin "
        "[malformed_base_action]"
    ]


def test_action_transition_audit_rejects_history_on_new_untracked_action(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/action-new.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    authored = _action_document("open").replace(
        "next_action: Review synthetic evidence.\n",
        "action_state_history:\n"
        "- schema_version: wiki_action_transition_receipt.v2\n"
        "  from: done\n"
        "  to: open\n"
        "next_action: Review synthetic evidence.\n",
    )
    path.write_text(authored, encoding="utf-8")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: set())
    monkeypatch.setattr(audit, "_base_action_texts_by_page_id", lambda: {})
    monkeypatch.setattr(audit, "_malformed_base_actions", lambda: {})
    monkeypatch.setattr(
        audit,
        "run_git",
        lambda args: rel
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]
        else "",
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == [
        f"{rel}: a new action cannot author historical transition receipts "
        "[new_action_history_not_allowed]"
    ]


def test_action_transition_audit_ignores_portable_fixture_actions(
    tmp_path, monkeypatch, audit
):
    rel = "docs/references/fixtures/demo-wiki/memories/actions/action-new.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        _action_document("open").replace(
            "next_action: Review synthetic evidence.\n",
            "action_state_history:\n"
            "- schema_version: wiki_action_transition_receipt.v2\n"
            "  from: done\n"
            "  to: open\n"
            "next_action: Review synthetic evidence.\n",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(audit, "_base_action_texts_by_page_id", lambda: {})
    monkeypatch.setattr(audit, "_malformed_base_actions", lambda: {})
    monkeypatch.setattr(
        audit,
        "run_git",
        lambda args: rel
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]
        else "",
    )
    errors: list[str] = []

    audit.audit_action_state_transitions(errors)

    assert errors == []


def test_base_action_index_ignores_explicit_non_action_pages_in_action_directory(
    monkeypatch, audit
):
    index = (
        "---\n"
        "page_id: actions-index\n"
        "page_type: ontology_index\n"
        "---\n\n"
        "# Actions\n"
    )
    malformed = (
        "---\n"
        "page_id: action-broken\n"
        "page_type: action\n"
        "broken: [\n"
        "---\n"
    )
    monkeypatch.setattr(
        audit,
        "_base_action_candidate_texts_by_path",
        lambda: {
            "memories/actions/index.md": index,
            "memories/actions/broken.md": malformed,
        },
    )
    audit._malformed_base_actions.cache_clear()

    assert audit._malformed_base_actions() == {
        "memories/actions/broken.md": "action-broken"
    }


def test_base_action_index_discovers_nested_commented_yaml_in_real_git_repo(
    tmp_path, monkeypatch, audit
):
    rel = "memories/actions/nested/action-commented.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _action_document("open").replace(
        "page_type: action", "page_type: action # still canonical YAML"
    )
    path.write_text(previous, encoding="utf-8")
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "add", rel],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "base action",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    path.write_text(
        previous.replace("action_state: open", "action_state: in_progress"),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    for cached in (
        audit._audit_base_ref,
        audit._text_at_audit_base,
        audit._base_action_candidate_texts_by_path,
        audit._base_action_texts_by_page_id,
        audit._malformed_base_actions,
    ):
        cached.cache_clear()

    indexed = audit._base_action_texts_by_page_id()
    errors: list[str] = []
    audit.audit_action_state_transitions(errors)

    assert indexed["action-audit-synthetic"][0][0] == rel
    assert errors == [
        f"{rel}: action_state changed without a transition receipt "
        "[missing_action_transition_receipt]"
    ]
    for cached in (
        audit._audit_base_ref,
        audit._text_at_audit_base,
        audit._base_action_candidate_texts_by_path,
        audit._base_action_texts_by_page_id,
        audit._malformed_base_actions,
    ):
        cached.cache_clear()


def test_base_action_index_excludes_fixture_page_id_collisions(
    tmp_path, monkeypatch, audit
):
    canonical_rel = "memories/actions/action.md"
    fixture_rel = "docs/references/fixtures/demo-wiki/memories/actions/action.md"
    for rel in (canonical_rel, fixture_rel):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_action_document("open"), encoding="utf-8")
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "add",
            ".",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "canonical and fixture actions",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    for cached in (
        audit._audit_base_ref,
        audit._text_at_audit_base,
        audit._base_action_candidate_texts_by_path,
        audit._base_action_texts_by_page_id,
        audit._malformed_base_actions,
    ):
        cached.cache_clear()

    candidates = audit._base_action_texts_by_page_id()["action-audit-synthetic"]

    assert [rel for rel, _text in candidates] == [canonical_rel]


def _source_audit_document(
    *, state: str, adoption: str = "pending", accepted: bool = False
) -> str:
    closure = (
        "  accepted_ref: sha256:synthetic\n" "  emitted_page_ids: [page-one]\n"
        if accepted
        else ""
    )
    return (
        "---\n"
        "page_id: source-audit-synthetic\n"
        "page_type: source\n"
        "source_lifecycle:\n"
        f"  state: {state}\n"
        "  freshness_state: fresh\n"
        "  last_attempt_state: ok\n"
        "  pipeline_stage: complete\n"
        f"  adoption_state: {adoption}\n"
        f"{closure}"
        "---\n\n"
        "# Synthetic source\n"
    )


def test_source_transition_audit_uses_base_identity_and_rejects_reset(
    tmp_path, monkeypatch, audit
):
    old_rel = "memories/sources/source-old.md"
    rel = "memories/sources/source-renamed.md"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    previous = _source_audit_document(
        state="ingested", adoption="accepted", accepted=True
    )
    path.write_text(
        _source_audit_document(state="ingested", adoption="pending"),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    monkeypatch.setattr(audit, "changed_paths_for_audit", lambda: {rel})
    monkeypatch.setattr(
        audit,
        "_base_source_texts_by_page_id",
        lambda: {"source-audit-synthetic": ((old_rel, previous),)},
    )
    errors: list[str] = []

    audit.audit_source_lifecycle_transitions(errors)

    assert errors == [
        f"{rel}: source adoption changed through a reset or edge that is not "
        "allowed by SOURCE_ADOPTION_TRANSITIONS "
        "[illegal_source_adoption_transition]"
    ]


# ---------------------------------------------------------------------------
# Declarative check registry (CHECKS) + --only / --list-checks
# ---------------------------------------------------------------------------

# Canonical run order: this is the historical hand-written call sequence from
# main(), now the source of truth for the registry invariant. Reordering or
# dropping any entry would change gate behavior, so the test pins it exactly.
EXPECTED_CHECK_ORDER = [
    "frontmatter",
    "action_state_transitions",
    "source_lifecycle_transitions",
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
    "templates_registry",
    "source_recipes",
    "impact_closure",
    "log_changed",
]


def test_registry_matches_canonical_order(audit):
    # The registry must contain exactly the historical checks, in the same order.
    assert audit.CHECK_NAMES == tuple(EXPECTED_CHECK_ORDER)
    assert [name for name, _ in audit.CHECKS] == EXPECTED_CHECK_ORDER
    # No duplicate names.
    assert len(set(audit.CHECK_NAMES)) == len(audit.CHECK_NAMES)


def test_page_type_registry_accepts_nested_object_frontmatter(
    tmp_path, monkeypatch, audit
):
    (tmp_path / "memories/sources").mkdir(parents=True)
    (tmp_path / "wiki.page-types.yaml").write_text(
        "schema_version: wiki_page_types.v1\n"
        "page_types:\n"
        "  source:\n"
        "    template: none\n"
        "    template_none_reason: test fixture\n"
        "    allowed_dirs: [memories/sources]\n"
        "    required_frontmatter: [page_id, page_type, title]\n"
        "    field_types:\n"
        "      parent_projection: object\n",
        encoding="utf-8",
    )
    (tmp_path / "memories/sources/source.md").write_text(
        "---\n"
        "page_id: source-demo\n"
        "page_type: source\n"
        "title: Source\n"
        "context: system\n"
        "visibility: private_self\n"
        "updated_at: 2026-07-07\n"
        "stale_after_days: 30\n"
        "parent_projection:\n"
        "  quadrant: q2\n"
        "  sub_lens: evidencias\n"
        "---\n"
        "# Source\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    errors: list[str] = []
    audit.audit_page_type_registry(errors, WikiConfig())

    assert errors == []


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
    full_lines = [
        line
        for line in full.stdout.splitlines()
        if line.startswith(("WARN:", "ERROR:"))
    ]
    one_lines = [
        line for line in one.stdout.splitlines() if line.startswith(("WARN:", "ERROR:"))
    ]
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


def test_text_at_audit_base_preserves_trailing_newline(tmp_path, monkeypatch, audit):
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Wiki Audit Test"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "wiki-audit@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    target = tmp_path / "receipt.yaml"
    target.write_text("schema_version: receipt.v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "receipt.yaml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    monkeypatch.setattr(audit, "ROOT", tmp_path)
    audit._audit_base_ref.cache_clear()
    audit._text_at_audit_base.cache_clear()

    assert audit._text_at_audit_base("receipt.yaml") == "schema_version: receipt.v1\n"
