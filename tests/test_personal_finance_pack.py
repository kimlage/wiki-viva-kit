from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import jsonschema
import yaml

from wiki_core.detectors import scan_text
from wiki_core.experience_packs import (
    PackError,
    compose_active_packs,
    disable_pack,
    install_pack,
    load_lock,
    preview_pack,
    remove_pack,
    resolve_pack,
    upgrade_pack,
    validate_installation,
)


KIT_ROOT = Path(__file__).resolve().parents[1]
FINANCE_PACK = KIT_ROOT / "packs/personal-finance"
STUDY_PACK = KIT_ROOT / "packs/study-research"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _tree_sha(pack: Path) -> str:
    rows = [
        {
            "path": item.relative_to(pack).as_posix(),
            "sha256": _sha(item),
            "size": item.stat().st_size,
        }
        for item in sorted(pack.rglob("*"), key=lambda item: item.as_posix())
        if item.is_file()
    ]
    return hashlib.sha256(
        json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    root.mkdir(parents=True)
    _write_yaml(
        root / "wiki.templates.yaml",
        {
            "schema_version": "wiki_templates.v2",
            "packages": {"quadrant_lenses": {"blocks": []}, "gamification": {"blocks": []}},
        },
    )
    shutil.copytree(FINANCE_PACK, root / "packs/personal-finance")
    shutil.copytree(STUDY_PACK, root / "packs/study-research")
    shutil.copy2(KIT_ROOT / "packs/registry.yaml", root / "packs/registry.yaml")
    return root


def _add_finance_upgrade(root: Path) -> None:
    source = root / "packs/personal-finance"
    target = root / "packs/personal-finance-0.1.1"
    shutil.copytree(source, target)
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.1.1"
    _write_yaml(manifest_path, manifest)
    install_path = target / "migrations/0001-install.yaml"
    install = yaml.safe_load(install_path.read_text(encoding="utf-8"))
    install["to_version"] = "0.1.1"
    _write_yaml(install_path, install)
    _write_yaml(
        target / "migrations/upgrades/0.1.0-to-0.1.1.yaml",
        {
            "schema_version": "wiki_experience_pack_migration.v1",
            "pack": "personal-finance",
            "from_version": "0.1.0",
            "to_version": "0.1.1",
            "data_policy": "preserve_user_content",
            "steps": [
                {"action": "activate_pack_bundle"},
                {"action": "register_capabilities"},
                {"action": "deactivate_pack_bundle"},
            ],
        },
    )
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    finance = registry["packs"]["personal-finance"]
    finance["default_version"] = "0.1.1"
    finance["versions"]["0.1.1"] = {
        "path": "personal-finance-0.1.1",
        "manifest_sha256": _sha(manifest_path),
        "tree_sha256": _tree_sha(target),
    }
    _write_yaml(registry_path, registry)


def test_finance_manifest_is_pinned_and_schema_valid() -> None:
    manifest_path = FINANCE_PACK / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (KIT_ROOT / "docs/references/schemas/wiki-experience-pack-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(schema).validate(manifest)
    registry = yaml.safe_load((KIT_ROOT / "packs/registry.yaml").read_text(encoding="utf-8"))
    record = registry["packs"]["personal-finance"]
    assert record["default_version"] == "0.1.0"
    assert record["versions"]["0.1.0"]["manifest_sha256"] == _sha(manifest_path)
    assert record["versions"]["0.1.0"]["tree_sha256"] == _tree_sha(FINANCE_PACK)
    source = resolve_pack(KIT_ROOT, "personal-finance")
    assert source.version == "0.1.0"
    assert source.manifest_sha256 == _sha(manifest_path)


def test_finance_vertical_declares_required_types_views_operations_and_time() -> None:
    manifest = resolve_pack(KIT_ROOT, "personal-finance").manifest
    assert set(manifest["capabilities"]["page_types"]) == {
        "personal_finance_account",
        "personal_finance_transaction",
        "personal_finance_obligation",
        "personal_finance_category",
        "personal_finance_reconciliation",
        "personal_finance_monthly_closing",
    }
    assert set(manifest["capabilities"]["operations"]) == {
        "personal-finance.import-transactions",
        "personal-finance.classify-transaction",
        "personal-finance.reconcile-account",
        "personal-finance.monthly-close",
        "personal-finance.forecast-cashflow",
    }
    assert set(manifest["capabilities"]["views"]) == {
        "personal-finance.cashflow",
        "personal-finance.category-variance",
        "personal-finance.reconciliation",
        "personal-finance.monthly-closing-tape",
    }
    assert set(manifest["capabilities"]["temporal_profiles"]) == {
        "personal-finance.financial-calendar",
        "personal-finance.due-horizon",
        "personal-finance.month-comparison",
    }
    assert set(manifest["i18n"]["locales"]) == {"en", "es", "pt-BR"}
    assert manifest["capabilities"]["block_packages"] == ["quadrant_lenses", "gamification"]


def test_finance_operations_are_declarative_dry_run_human_gated_and_permissioned() -> None:
    descriptor = yaml.safe_load(
        (FINANCE_PACK / "operations/operations.yaml").read_text(encoding="utf-8")
    )
    assert descriptor["write_policy"] == "proposal_branch_only"
    assert {entry["id"] for entry in descriptor["skills"]["human"]} == {
        "personal-finance.approve-monthly-close"
    }
    assert {entry["id"] for entry in descriptor["skills"]["agent"]} == {
        "personal-finance.classify-synthetic-transactions"
    }
    for operation in descriptor["operations"].values():
        assert operation["dry_run"] is True
        assert operation["human_gate"] == "required"
        assert operation["command"].startswith("personal-finance.")
        assert operation["outputs"]
        assert operation["policies"]
    assert set(descriptor["permissions"]) == {
        "personal-finance.read-financial-sources",
        "personal-finance.propose-financial-changes",
        "personal-finance.review-public-boundary",
    }


def test_finance_temporal_profiles_preserve_time_semantics() -> None:
    temporal = yaml.safe_load((FINANCE_PACK / "temporal/profiles.yaml").read_text(encoding="utf-8"))
    profiles = temporal["profiles"]
    assert profiles["personal-finance.financial-calendar"]["event_times"] == [
        "occurred_at",
        "due_at",
        "closed_at",
    ]
    assert profiles["personal-finance.due-horizon"]["lanes"] == [
        "overdue",
        "due_soon",
        "scheduled",
        "completed",
    ]
    assert profiles["personal-finance.month-comparison"]["comparison"] == "adjacent-periods"
    assert all(profile["precision_policy"] == "preserve_unknown" for profile in profiles.values())


def test_finance_monthly_closing_migration_is_additive_and_reversible() -> None:
    migration = yaml.safe_load(
        (FINANCE_PACK / "migrations/monthly-closing-convention.yaml").read_text(encoding="utf-8")
    )
    assert migration["from"]["page_type"] == "monthly_closing"
    assert migration["to"]["page_type"] == "personal_finance_monthly_closing"
    assert migration["strategy"] == "additive_copy"
    assert migration["data_policy"] == "preserve_user_content"
    assert migration["write_policy"] == "proposal_branch_only"
    assert migration["field_map"]["month"] == "period"
    assert migration["preserve_unknown_fields"] is True
    assert migration["delete_source_pages"] is False
    assert migration["overwrite_existing_fields"] is False
    assert migration["human_review_required"] is True
    assert migration["rollback"] == "remove_generated_proposal_only"


def test_finance_fixture_portfolio_is_complete_and_explicit() -> None:
    preview = preview_pack(KIT_ROOT, "personal-finance")
    by_id = {row["id"]: row for row in preview["fixtures"]}
    assert set(by_id) == {
        "finance-mini-genesis",
        "finance-minimal",
        "finance-normal-month",
        "finance-dense-year",
        "finance-missing-source",
        "finance-duplicate-transaction",
        "finance-late-close",
        "finance-public-export-blocked",
    }
    assert by_id["finance-mini-genesis"]["expected_state"] == "genesis_ready"
    assert by_id["finance-normal-month"]["expected_state"] == "close_ready"
    assert by_id["finance-dense-year"]["expected_state"] == "dense_ready"
    failures = {
        "finance-missing-source": "missing_source",
        "finance-duplicate-transaction": "duplicate_transaction",
        "finance-late-close": "late_monthly_close",
        "finance-public-export-blocked": "private_financial_fields_require_redaction",
    }
    for fixture_id, code in failures.items():
        path = next(
            FINANCE_PACK / row["path"] / "scenario.yaml"
            for row in preview["fixtures"]
            if row["id"] == fixture_id
        )
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert scenario["failure_code"] == code
        assert scenario["assertions"]


def test_finance_dense_fixture_and_public_export_failure_are_honest() -> None:
    dense = yaml.safe_load(
        (FINANCE_PACK / "fixtures/dense/scenario.yaml").read_text(encoding="utf-8")
    )
    assert dense["generated_counts"] == {
        "accounts": 6,
        "transactions": 720,
        "obligations": 36,
        "categories": 24,
        "reconciliations": 72,
        "monthly_closings": 12,
    }
    blocked = yaml.safe_load(
        (FINANCE_PACK / "fixtures/failure-public-export/scenario.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert blocked["expected_state"] == "public_export_blocked"
    assert "private_fields_are_not_emitted" in blocked["assertions"]
    assert blocked["public_synthetic"] is True


def test_finance_pack_contains_no_secret_pii_entity_or_unapproved_asset() -> None:
    findings = []
    for path in sorted(FINANCE_PACK.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".yaml", ".yml", ".md", ".json", ".txt"}:
            findings.extend(scan_text(path.read_text(encoding="utf-8")))
    assert findings == []
    assets = yaml.safe_load((FINANCE_PACK / "assets/manifest.yaml").read_text(encoding="utf-8"))
    assert assets == {"schema_version": "wiki_experience_pack_assets.v1", "assets": []}
    assert not list((FINANCE_PACK / "assets").glob("*.svg"))


def test_finance_public_fixture_gate_blocks_injected_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    scenario = root / "packs/personal-finance/fixtures/minimal/scenario.yaml"
    scenario.write_text(
        scenario.read_text(encoding="utf-8") + "owner_contact: private.fixture@example.test\n",
        encoding="utf-8",
    )
    try:
        resolve_pack(root, "personal-finance")
    except PackError as exc:
        assert exc.code in {
            "pack_publication_privacy_blocked",
            "public_fixture_privacy_blocked",
        }
        assert "private.fixture@example.test" not in str(exc)
    else:  # pragma: no cover - fail loudly if the boundary ever regresses
        raise AssertionError("public fixture identity was not blocked")


def test_finance_composes_with_study_research(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    install_pack(root, "personal-finance")
    report = validate_installation(root)
    assert report["status"] == "valid"
    composition = compose_active_packs(root)
    assert [row["id"] for row in composition["packs"]] == [
        "personal-finance",
        "study-research",
    ]
    assert composition["block_packages"] == ["gamification", "quadrant_lenses"]
    assert {
        row["contribution"] for row in composition["slots"]["views"]
    }.issuperset({"personal-finance.cashflow", "study-research.concept-graph"})


def test_finance_full_lifecycle_receipts_and_user_data_preservation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    user_page = root / "memories/finance/durable-ledger.md"
    user_page.parent.mkdir(parents=True)
    original = b"# Durable private ledger\n"
    user_page.write_bytes(original)

    dry_install = install_pack(root, "personal-finance", version="0.1.0", dry_run=True)
    installed = install_pack(root, "personal-finance", version="0.1.0")
    assert dry_install["receipt"]["receipt_id"] == installed["receipt"]["receipt_id"]

    _add_finance_upgrade(root)
    dry_upgrade = upgrade_pack(root, "personal-finance", dry_run=True)
    upgraded = upgrade_pack(root, "personal-finance")
    assert dry_upgrade["receipt"]["receipt_id"] == upgraded["receipt"]["receipt_id"]
    assert load_lock(root)["packs"]["personal-finance"]["version"] == "0.1.1"

    disabled = disable_pack(root, "personal-finance")
    assert disabled["receipt"]["action"] == "disable"
    assert load_lock(root)["packs"]["personal-finance"]["status"] == "disabled"
    removed = remove_pack(root, "personal-finance")
    assert removed["receipt"]["action"] == "remove"
    assert "personal-finance" not in load_lock(root)["packs"]
    assert user_page.read_bytes() == original

    receipt_dir = root / ".wiki-viva/pack-receipts/personal-finance"
    for action in ("install", "upgrade", "disable", "remove"):
        receipts = list(receipt_dir.glob(f"{action}-*.json"))
        assert len(receipts) == 1
        payload = json.loads(receipts[0].read_text(encoding="utf-8"))
        assert payload["data_preservation"] == "user_content_untouched"
        assert payload["privacy_gate"] == "core_secret_and_public_pii_rules_preserved"


def test_finance_upgrade_preserves_disabled_state(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "personal-finance", version="0.1.0")
    disable_pack(root, "personal-finance")
    _add_finance_upgrade(root)
    upgrade_pack(root, "personal-finance")
    assert load_lock(root)["packs"]["personal-finance"]["status"] == "disabled"
    assert compose_active_packs(root)["packs"] == []
