from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

import wiki_core._experience_pack_lifecycle as experience_pack_lifecycle
import wiki_core._experience_pack_i18n as experience_pack_i18n
from wiki_core.web import snapshot as snapshot_module
from wiki_core.config import WikiConfig
from wiki_core.experience_packs import (
    CORE_VERSION,
    PackError,
    compose_active_packs,
    disable_pack,
    inspect_pack,
    install_pack,
    list_packs,
    load_lock,
    preview_pack,
    remove_pack,
    resolve_pack,
    upgrade_pack,
    validate_installation,
    version_satisfies,
)
from wiki_core.web.schemas import SNAPSHOT_FILES
from wiki_core.web.snapshot import build_snapshot, snapshot_contract_errors


KIT_ROOT = Path(__file__).resolve().parents[1]
STUDY_PACK = KIT_ROOT / "packs/study-research"


def _hold_pack_operation_guard(
    root: str,
    entered: object,
    release: object,
) -> None:
    with experience_pack_lifecycle._operation_guard(Path(root)):
        entered.set()  # type: ignore[attr-defined]
        release.wait(10)  # type: ignore[attr-defined]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


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


def _registry_record(path: str, manifest: Path) -> dict[str, str]:
    return {
        "path": path,
        "manifest_sha256": _sha(manifest),
        "tree_sha256": _tree_sha(manifest.parent),
    }


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    root.mkdir(parents=True)
    _write_yaml(
        root / "wiki.templates.yaml",
        {
            "schema_version": "wiki_templates.v2",
            "packages": {
                "quadrant_lenses": {"blocks": []},
                "gamification": {"blocks": []},
            },
        },
    )
    shutil.copytree(STUDY_PACK, root / "packs/study-research")
    _write_yaml(
        root / "packs/registry.yaml",
        {
            "schema_version": "wiki_experience_pack_registry.v1",
            "packs": {
                "study-research": {
                    "default_version": "0.1.0",
                    "versions": {
                        "0.1.0": _registry_record(
                            "study-research", root / "packs/study-research/pack.yaml"
                        )
                    },
                }
            },
        },
    )
    return root


def _rename_pack(root: Path, pack_id: str, *, exclusive_view: bool = False) -> Path:
    target = root / "packs" / pack_id
    shutil.copytree(STUDY_PACK, target)
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    old_id = manifest["id"]
    manifest["id"] = pack_id
    manifest["name"] = pack_id.replace("-", " ").title()
    manifest["description"] = (
        "A second synthetic pack used to prove deterministic composition."
    )
    page_prefix = f"{pack_id.replace('-', '_')}_"
    manifest["capabilities"]["page_types"] = [f"{page_prefix}reference"]
    for key in ("blocks", "views", "commands", "operations", "temporal_profiles"):
        manifest["capabilities"][key] = [
            value.replace(f"{old_id}.", f"{pack_id}.")
            for value in manifest["capabilities"][key][:1]
        ]
    for kind, capability in (
        ("views", "views"),
        ("commands", "commands"),
        ("operations", "operations"),
        ("timelines", "temporal_profiles"),
    ):
        contribution = manifest["capabilities"][capability][0]
        manifest["slots"][kind] = [
            {
                "slot": {
                    "views": "view.knowledge",
                    "commands": "command.capture",
                    "operations": "operation.intake",
                    "timelines": "timeline.history",
                }[kind],
                "contribution": contribution,
                "mode": "exclusive" if exclusive_view and kind == "views" else "append",
            }
        ]
    _write_yaml(manifest_path, manifest)

    # Keep the copied declarative adapters semantically bound to the minimized
    # manifest. These synthetic packs exercise composition, not the full study
    # vertical, so one contribution per slot is intentional.
    replacement_prefix = pack_id.replace("-", "_")
    page_types_path = target / "page-types.yaml"
    page_types = yaml.safe_load(page_types_path.read_text(encoding="utf-8"))
    page_types["pack"] = pack_id
    page_types["page_types"] = {
        f"{replacement_prefix}_reference": {
            "title": "Synthetic reference",
            "visibility": "private",
            "template": "templates/source.md",
            "fields": ["source_kind", "status", "captured_at"],
        }
    }
    _write_yaml(page_types_path, page_types)

    views_path = target / "views/views.yaml"
    views = yaml.safe_load(views_path.read_text(encoding="utf-8"))
    views["pack"] = pack_id
    views["views"] = {
        manifest["capabilities"]["views"][0]: next(iter(views["views"].values()))
    }
    _write_yaml(views_path, views)

    permission_id = f"{pack_id}.propose-study-changes"
    command_id = manifest["capabilities"]["commands"][0]
    commands_path = target / "commands/commands.yaml"
    commands = yaml.safe_load(commands_path.read_text(encoding="utf-8"))
    command = next(iter(commands["commands"].values()))
    command["outputs"] = [f"{replacement_prefix}_reference"]
    command["permissions"] = [permission_id]
    commands["pack"] = pack_id
    commands["commands"] = {command_id: command}
    _write_yaml(commands_path, commands)

    operation_id = manifest["capabilities"]["operations"][0]
    operations_path = target / "operations/operations.yaml"
    operations = yaml.safe_load(operations_path.read_text(encoding="utf-8"))
    operation = next(iter(operations["operations"].values()))
    operation["command"] = command_id
    operation["outputs"] = [f"{replacement_prefix}_reference"]
    operation["permissions"] = [permission_id]
    operations["pack"] = pack_id
    operations["permissions"] = {
        permission_id: {
            "scope": "pack-owned-page-types",
            "mode": "proposal_only",
        }
    }
    operations["skills"] = {
        "human": [],
        "agent": [
            {
                "id": f"{pack_id}.prepare-study-proposal",
                "permissions": [permission_id],
                "responsibility": "Prepare a synthetic proposal for human review.",
            }
        ],
    }
    operations["operations"] = {operation_id: operation}
    _write_yaml(operations_path, operations)

    temporal_id = manifest["capabilities"]["temporal_profiles"][0]
    temporal_path = target / "temporal/profiles.yaml"
    temporal = yaml.safe_load(temporal_path.read_text(encoding="utf-8"))
    temporal["pack"] = pack_id
    temporal["profiles"] = {
        temporal_id: next(iter(temporal["profiles"].values()))
    }
    adapter = dict(next(iter(temporal["adapters"].values())))
    adapter_id = f"{pack_id}.learning-captured"
    adapter["page_type"] = f"{replacement_prefix}_reference"
    adapter["event_kind"] = adapter_id
    temporal["adapters"] = {adapter_id: adapter}
    _write_yaml(temporal_path, temporal)

    presentation_ids = {
        pack_id,
        f"{replacement_prefix}_reference",
        manifest["capabilities"]["views"][0],
        manifest["capabilities"]["commands"][0],
        manifest["capabilities"]["operations"][0],
        manifest["capabilities"]["temporal_profiles"][0],
        adapter_id,
    }

    def presentation_key(identifier: str) -> str:
        if identifier == pack_id:
            return "title"
        dotted = f"{pack_id}."
        underscored = f"{replacement_prefix}_"
        suffix = (
            identifier[len(dotted) :]
            if identifier.startswith(dotted)
            else identifier[len(underscored) :]
        )
        return suffix.replace("-", "_").replace(".", "_")

    copy_keys = sorted({presentation_key(identifier) for identifier in presentation_ids})
    for locale in ("en", "pt-BR"):
        catalog_path = target / f"i18n/{locale}.yaml"
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
        catalog["pack"] = pack_id
        catalog["copy"] = {
            key: key.replace("_", " ").title() for key in copy_keys
        }
        _write_yaml(catalog_path, catalog)

    migration_path = target / "migrations/0001-install.yaml"
    migration = yaml.safe_load(migration_path.read_text(encoding="utf-8"))
    migration["pack"] = pack_id
    _write_yaml(migration_path, migration)
    registry = yaml.safe_load(
        (root / "packs/registry.yaml").read_text(encoding="utf-8")
    )
    registry["packs"][pack_id] = {
        "default_version": "0.1.0",
        "versions": {"0.1.0": _registry_record(pack_id, manifest_path)},
    }
    _write_yaml(root / "packs/registry.yaml", registry)
    return target


def _add_upgrade(root: Path) -> None:
    source = root / "packs/study-research"
    target = root / "packs/study-research-0.2.0"
    shutil.copytree(source, target)
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "0.2.0"
    _write_yaml(manifest_path, manifest)
    install = yaml.safe_load(
        (target / "migrations/0001-install.yaml").read_text(encoding="utf-8")
    )
    install["to_version"] = "0.2.0"
    _write_yaml(target / "migrations/0001-install.yaml", install)
    _write_yaml(
        target / "migrations/upgrades/0.1.0-to-0.2.0.yaml",
        {
            "schema_version": "wiki_experience_pack_migration.v1",
            "pack": "study-research",
            "from_version": "0.1.0",
            "to_version": "0.2.0",
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
    record = registry["packs"]["study-research"]
    record["default_version"] = "0.2.0"
    record["versions"]["0.2.0"] = _registry_record(
        "study-research-0.2.0", manifest_path
    )
    _write_yaml(registry_path, registry)


def _state_digest(root: Path) -> str:
    rows: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append((path.relative_to(root).as_posix(), _sha(path)))
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _assert_receipt_projects_current_lock(
    root: Path, response: dict[str, object]
) -> None:
    receipt = response["receipt"]
    assert isinstance(receipt, dict)
    projection = experience_pack_lifecycle._receipt_lock_projection(load_lock(root))
    assert receipt["schema_version"] == "wiki_experience_pack_receipt.v2"
    assert receipt["next_lock_projection"] == projection
    assert all("receipts" not in entry for entry in projection["packs"].values())
    assert receipt["next_lock_sha256"] == hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert experience_pack_lifecycle._receipt_matches(
        root,
        str(receipt["pack"]),
        str(receipt["receipt_id"]),
    )


def _snapshot_config(root: Path) -> WikiConfig:
    page = root / "memories/index.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """---
page_id: root-pack-snapshot
page_type: root_index
title: "Pack snapshot root"
context: system
visibility: public
updated_at: 2026-07-11
stale_after_days: 30
---

# Pack snapshot root

Synthetic runtime-boundary fixture.
""",
        encoding="utf-8",
    )
    return WikiConfig(repo_id="pack-snapshot")


def test_shipped_manifest_registry_and_lock_match_published_schemas() -> None:
    cases = [
        (
            KIT_ROOT / "packs/study-research/pack.yaml",
            KIT_ROOT / "docs/references/schemas/wiki-experience-pack-v1.schema.json",
        ),
        (
            KIT_ROOT / "packs/personal-finance/pack.yaml",
            KIT_ROOT / "docs/references/schemas/wiki-experience-pack-v1.schema.json",
        ),
        (
            KIT_ROOT / "packs/registry.yaml",
            KIT_ROOT
            / "docs/references/schemas/wiki-experience-pack-registry-v1.schema.json",
        ),
        (
            KIT_ROOT / "wiki.packs.lock.yaml",
            KIT_ROOT
            / "docs/references/schemas/wiki-experience-pack-lock-v1.schema.json",
        ),
    ]
    for document_path, schema_path in cases:
        document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(document)


@pytest.mark.parametrize("pack_id", ["study-research", "personal-finance"])
@pytest.mark.parametrize(
    ("artifact", "schema_name"),
    [
        ("views/views.yaml", "wiki-experience-pack-views-v1.schema.json"),
        ("commands/commands.yaml", "wiki-experience-pack-commands-v1.schema.json"),
        ("operations/operations.yaml", "wiki-experience-pack-operations-v1.schema.json"),
        (
            "temporal/profiles.yaml",
            "wiki-experience-pack-temporal-profiles-v2.schema.json",
        ),
    ],
)
def test_shipped_declarative_pack_artifacts_match_closed_schemas(
    pack_id: str,
    artifact: str,
    schema_name: str,
) -> None:
    document = yaml.safe_load(
        (KIT_ROOT / "packs" / pack_id / artifact).read_text(encoding="utf-8")
    )
    schema = json.loads(
        (KIT_ROOT / "docs/references/schemas" / schema_name).read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(schema).validate(document)


def test_declarative_artifact_invalid_yaml_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "packs/study-research/operations/operations.yaml").write_text(
        "operations: [unterminated\n",
        encoding="utf-8",
    )

    with pytest.raises(PackError, match="invalid_yaml"):
        resolve_pack(root, "study-research")


def test_declarative_artifact_ghost_contribution_fails_closed(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    path = root / "packs/study-research/views/views.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["views"]["study-research.ghost-view"] = {
        "slot": "view.ghost",
        "fallback": "linked-list",
        "empty_state": "create-concept",
    }
    _write_yaml(path, document)

    with pytest.raises(PackError, match="views_artifact_capability_mismatch"):
        resolve_pack(root, "study-research")


def test_pack_license_metadata_requires_applicable_license_text(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    manifest_path = root / "packs/study-research/pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["license"] = "Apache-2.0"
    _write_yaml(manifest_path, manifest)
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["study-research"]["versions"]["0.1.0"][
        "manifest_sha256"
    ] = _sha(manifest_path)
    _write_yaml(registry_path, registry)

    with pytest.raises(PackError, match="pack_license_not_proven"):
        resolve_pack(root, "study-research")


def test_install_refuses_malformed_presentation_catalog_before_any_write(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    catalog_path = root / "packs/study-research/i18n/pt-BR.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["copy"].pop("learning_captured")
    _write_yaml(catalog_path, catalog)
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["study-research"]["versions"]["0.1.0"] = _registry_record(
        "study-research", root / "packs/study-research/pack.yaml"
    )
    _write_yaml(registry_path, registry)

    before = _state_digest(root)
    with pytest.raises(PackError, match="pack_presentation_catalog_key_mismatch"):
        install_pack(root, "study-research")
    assert _state_digest(root) == before
    assert not (root / "wiki.packs.lock.yaml").exists()
    assert not (root / ".wiki-viva").exists()


def test_empty_lock_publishes_exact_mandatory_pack_composition(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    snapshot = build_snapshot(
        root,
        _snapshot_config(root),
        generated_at="2026-07-11T12:00:00Z",
    )

    assert tuple(snapshot) == SNAPSHOT_FILES
    assert snapshot["experience_packs.json"] == {
        "schema_version": "wiki_experience_pack_composition.v1",
        "core_version": "8.0.0",
        "packs": [],
        "block_packages": [],
        "slots": {
            "views": [],
            "commands": [],
            "operations": [],
            "timelines": [],
        },
        "presentation": {
            "default_locale": "en",
            "locales": {"en": {}, "pt-BR": {}},
        },
        "composition_sha256": (
            "91278d9654bc92e5a7af1075c67297eb751beb6feef3bd06cee92210e5d667c4"
        ),
    }
    manifest = snapshot["manifest.json"]
    assert "experience_packs.json" in manifest["files"]
    assert "experience_packs.json" in manifest["integrity"]
    assert manifest["capabilities"].count("experience_packs") == 1
    assert (
        manifest["versions"]["experience_pack_composition"]
        == "wiki_experience_pack_composition.v1"
    )
    assert manifest["contract_errors"] == []

    snapshot["experience_packs.json"]["composition_sha256"] = "0" * 64
    assert "experience pack composition hash mismatch" in snapshot_contract_errors(
        snapshot
    )

    presentation = snapshot["experience_packs.json"]["presentation"]
    snapshot["experience_packs.json"]["composition_sha256"] = (
        "91278d9654bc92e5a7af1075c67297eb751beb6feef3bd06cee92210e5d667c4"
    )
    presentation["locales"].pop("pt-BR")
    assert "experience pack presentation locales are not canonical" in (
        snapshot_contract_errors(snapshot)
    )


def _legacy_v2_snapshot_without_pack_contract(
    snapshot: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    legacy = json.loads(json.dumps(snapshot))
    legacy.pop("experience_packs.json")
    manifest = legacy["manifest.json"]
    manifest["files"].remove("experience_packs.json")  # type: ignore[union-attr]
    manifest["integrity"].pop("experience_packs.json")  # type: ignore[union-attr]
    manifest["capabilities"].remove("experience_packs")  # type: ignore[union-attr]
    manifest["versions"].pop("experience_pack_composition")  # type: ignore[union-attr]
    bundle_hash = snapshot_module._bundle_hash_for_artifacts(legacy)
    manifest["bundle_hash"] = bundle_hash
    repo_id = str(manifest["repo"]["repo_id"])  # type: ignore[index]
    manifest["snapshot_id"] = f"{repo_id}-{bundle_hash[:16]}"
    manifest["contract_errors"] = []
    return legacy


def test_old_v2_snapshot_without_pack_advertisement_remains_valid(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    current = build_snapshot(
        root,
        _snapshot_config(root),
        generated_at="2026-07-11T12:00:00Z",
    )
    legacy = _legacy_v2_snapshot_without_pack_contract(current)

    assert snapshot_contract_errors(legacy) == []


@pytest.mark.parametrize("advertisement", ["capability", "version"])
def test_partial_pack_contract_advertisement_fails_closed(
    tmp_path: Path,
    advertisement: str,
) -> None:
    root = _repo(tmp_path)
    current = build_snapshot(
        root,
        _snapshot_config(root),
        generated_at="2026-07-11T12:00:00Z",
    )
    partial = _legacy_v2_snapshot_without_pack_contract(current)
    manifest = partial["manifest.json"]
    if advertisement == "capability":
        manifest["capabilities"].append("experience_packs")  # type: ignore[union-attr]
    else:
        manifest["versions"]["experience_pack_composition"] = (  # type: ignore[index]
            "wiki_experience_pack_composition.v1"
        )

    errors = snapshot_contract_errors(partial)
    assert "experience pack composition file declaration missing" in errors
    assert "experience pack composition payload missing" in errors


def test_active_pack_snapshot_proves_all_slots_and_block_packages(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    snapshot = build_snapshot(
        root,
        _snapshot_config(root),
        generated_at="2026-07-11T12:00:00Z",
    )
    composition = snapshot["experience_packs.json"]

    assert composition["packs"] == [{"id": "study-research", "version": "0.1.0"}]
    assert composition["block_packages"] == ["gamification", "quadrant_lenses"]
    assert set(composition["slots"]) == {
        "views",
        "commands",
        "operations",
        "timelines",
    }
    assert {row["contribution"] for row in composition["slots"]["views"]} == {
        "study-research.concept-graph",
        "study-research.evidence-matrix",
        "study-research.reading-queue",
    }
    assert {row["contribution"] for row in composition["slots"]["commands"]} >= {
        "study-research.capture",
        "study-research.synthesize",
    }
    assert {row["contribution"] for row in composition["slots"]["operations"]} == {
        "study-research.capture-source",
        "study-research.review-evidence",
        "study-research.synthesize-topic",
    }
    assert {row["contribution"] for row in composition["slots"]["timelines"]} == {
        "study-research.claim-evolution",
        "study-research.learning-history",
        "study-research.spaced-review",
    }
    schema = json.loads(
        (
            KIT_ROOT
            / "docs/references/schemas/wiki-experience-pack-composition-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(composition)
    assert snapshot_contract_errors(snapshot) == []


def test_invalid_lock_and_active_composition_fail_snapshot_closed(
    tmp_path: Path,
) -> None:
    malformed_root = _repo(tmp_path / "malformed")
    malformed_config = _snapshot_config(malformed_root)
    _write_yaml(
        malformed_root / "wiki.packs.lock.yaml",
        {
            "schema_version": "wiki_experience_pack_lock.invalid",
            "core_version": "8.0.0",
            "packs": {},
        },
    )
    with pytest.raises(PackError, match="lock_schema_version_mismatch"):
        build_snapshot(malformed_root, malformed_config)

    conflict_root = _repo(tmp_path / "conflict")
    _rename_pack(conflict_root, "citation-tools")
    install_pack(conflict_root, "study-research", enforce_git_gate=False)
    install_pack(conflict_root, "citation-tools", enforce_git_gate=False)
    conflict_config = _snapshot_config(conflict_root)
    lock_path = conflict_root / "wiki.packs.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    shared_slot = lock["packs"]["study-research"]["slots"]["views"][0]["slot"]
    lock["packs"]["citation-tools"]["slots"]["views"][0]["slot"] = shared_slot
    lock["packs"]["citation-tools"]["slots"]["views"][0]["mode"] = "exclusive"
    _write_yaml(lock_path, lock)

    with pytest.raises(PackError, match="active_pack_composition_invalid"):
        build_snapshot(conflict_root, conflict_config)


def test_study_pack_is_registered_pinned_and_complete() -> None:
    source = resolve_pack(KIT_ROOT, "study-research")
    assert source.version == "0.1.0"
    assert source.manifest_sha256 == _sha(STUDY_PACK / "pack.yaml")
    assert source.manifest["capabilities"]["block_packages"] == [
        "quadrant_lenses",
        "gamification",
    ]
    assert len(source.manifest["fixtures"]) == 4
    assert len(source.manifest["capabilities"]["temporal_profiles"]) == 3
    assert {"en", "pt-BR"} == set(source.manifest["i18n"]["locales"])


def test_inspect_and_preview_are_deterministic_and_synthetic() -> None:
    inspected = inspect_pack(KIT_ROOT, "study-research")
    preview = preview_pack(KIT_ROOT, "study-research")
    assert inspected == inspect_pack(KIT_ROOT, "study-research")
    assert preview == preview_pack(KIT_ROOT, "study-research")
    assert inspected["asset_policy"]["remote"] == "blocked"
    assert preview["synthetic_only"] is True
    assert preview["privacy_gate"] == "passed"
    assert {row["expected_state"] for row in preview["fixtures"]} == {
        "ready",
        "dense_ready",
        "review_blocked",
    }


def test_list_reports_not_installed_then_active(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert list_packs(root)["packs"][0]["status"] == "not_installed"
    install_pack(root, "study-research")
    row = list_packs(root)["packs"][0]
    assert row["installed_version"] == "0.1.0"
    assert row["status"] == "active"


def test_dry_run_is_read_only_and_receipt_matches_install(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    before = _state_digest(root)
    planned = install_pack(root, "study-research", dry_run=True)
    assert _state_digest(root) == before
    applied = install_pack(root, "study-research")
    assert planned["receipt"]["receipt_id"] == applied["receipt"]["receipt_id"]
    assert planned["conceptual_diff"] == applied["conceptual_diff"]
    lock = load_lock(root)
    entry = lock["packs"]["study-research"]
    assert applied["receipt"]["receipt_id"] in entry["receipts"]
    assert (root / entry["installed_path"] / "pack.yaml").is_file()


def test_receipt_identity_binds_non_recursive_next_lock_across_lifecycle(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)

    installed = install_pack(root, "study-research", version="0.1.0")
    _assert_receipt_projects_current_lock(root, installed)

    _add_upgrade(root)
    upgraded = upgrade_pack(root, "study-research")
    _assert_receipt_projects_current_lock(root, upgraded)

    disabled = disable_pack(root, "study-research")
    _assert_receipt_projects_current_lock(root, disabled)

    removed = remove_pack(root, "study-research")
    _assert_receipt_projects_current_lock(root, removed)
    assert validate_installation(root)["status"] == "valid"


@pytest.mark.parametrize("action", ["install", "upgrade", "disable", "remove"])
def test_receipt_next_lock_digest_tamper_fails_closed(
    tmp_path: Path,
    action: str,
) -> None:
    root = _repo(tmp_path)
    response = install_pack(root, "study-research", version="0.1.0")
    if action in {"upgrade", "disable", "remove"}:
        if action == "upgrade":
            _add_upgrade(root)
            response = upgrade_pack(root, "study-research")
        elif action == "disable":
            response = disable_pack(root, "study-research")
        else:
            response = remove_pack(root, "study-research")

    receipt = response["receipt"]
    receipt_path = root / experience_pack_lifecycle._receipt_relative(receipt)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["next_lock_sha256"] = "0" * 64
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assert not experience_pack_lifecycle._receipt_matches(
        root,
        "study-research",
        str(receipt["receipt_id"]),
    )
    report = validate_installation(root)
    assert report["status"] == "invalid"
    assert {tuple(sorted(row.items())) for row in report["errors"]} >= {
        tuple(
            sorted(
                {
                    "code": "installed_receipt_invalid",
                    "pack": "study-research",
                }.items()
            )
        )
    }


def test_installation_validation_detects_bundle_drift(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    assert validate_installation(root)["status"] == "valid"
    installed = root / load_lock(root)["packs"]["study-research"]["installed_path"]
    (installed / "README.md").write_text(
        "changed by an unreviewed writer\n", encoding="utf-8"
    )
    report = validate_installation(root)
    assert report["status"] == "invalid"
    assert report["errors"] == [
        {"code": "installed_bundle_drift", "pack": "study-research"}
    ]


@pytest.mark.parametrize("relative", ["temporal/profiles.yaml", "i18n/en.yaml"])
def test_composition_reopens_presentation_artifacts_against_the_pinned_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    installed = root / load_lock(root)["packs"]["study-research"]["installed_path"]
    original = experience_pack_i18n._event_kind_identifiers
    changed = False

    def race_after_tree_scan(*args: object, **kwargs: object) -> set[str]:
        nonlocal changed
        if not changed:
            target = installed / relative
            target.write_bytes(target.read_bytes() + b"\n# concurrent drift\n")
            changed = True
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        experience_pack_i18n,
        "_event_kind_identifiers",
        race_after_tree_scan,
    )
    with pytest.raises(PackError, match="installed_bundle_drift"):
        compose_active_packs(root)


def test_installation_validation_binds_manifest_lock_and_receipt(
    tmp_path: Path,
) -> None:
    missing_receipt_root = _repo(tmp_path / "missing-receipt")
    install_pack(missing_receipt_root, "study-research")
    for receipt in (
        missing_receipt_root / ".wiki-viva/pack-receipts/study-research"
    ).glob("*.json"):
        receipt.unlink()
    report = validate_installation(missing_receipt_root)
    assert report["status"] == "invalid"
    assert {row["code"] for row in report["errors"]} == {"installed_receipt_invalid"}

    forged_lock_root = _repo(tmp_path / "forged-lock")
    install_pack(forged_lock_root, "study-research")
    lock_path = forged_lock_root / "wiki.packs.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    entry = lock["packs"]["study-research"]
    entry["capabilities"]["views"] = ["study-research.forged-view"]
    entry["slots"]["views"] = [
        {
            "slot": "view.forged",
            "contribution": "study-research.forged-view",
            "mode": "append",
        }
    ]
    _write_yaml(lock_path, lock)
    report = validate_installation(forged_lock_root)
    assert report["status"] == "invalid"
    assert "installed_manifest_lock_mismatch" in {
        row["code"] for row in report["errors"]
    }


def test_installation_validation_detects_unlocked_bundle_orphan(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    entry = load_lock(root)["packs"]["study-research"]
    installed = root / entry["installed_path"]
    shutil.copytree(installed, root / ".wiki-viva/packs/orphan-tools/0.1.0")

    report = validate_installation(root)

    assert report["status"] == "invalid"
    assert {tuple(sorted(row.items())) for row in report["errors"]} >= {
        tuple(
            sorted({"code": "orphan_installed_bundle", "pack": "orphan-tools"}.items())
        )
    }


def test_disable_removes_contributions_without_deleting_bundle(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    installed_path = root / load_lock(root)["packs"]["study-research"]["installed_path"]
    disable_pack(root, "study-research")
    assert installed_path.is_dir()
    assert load_lock(root)["packs"]["study-research"]["status"] == "disabled"
    assert compose_active_packs(root)["packs"] == []


def test_remove_preserves_user_data_and_only_deletes_owned_bundle(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    user_page = root / "memories/studies/my-notes.md"
    user_page.parent.mkdir(parents=True)
    original = b"# My durable study notes\n"
    user_page.write_bytes(original)
    install_pack(root, "study-research")
    installed_path = root / load_lock(root)["packs"]["study-research"]["installed_path"]
    planned = remove_pack(root, "study-research", dry_run=True)
    assert user_page.read_bytes() == original and installed_path.is_dir()
    applied = remove_pack(root, "study-research")
    assert planned["receipt"]["receipt_id"] == applied["receipt"]["receipt_id"]
    assert user_page.read_bytes() == original
    assert not installed_path.exists()
    assert "study-research" not in load_lock(root)["packs"]
    assert list(
        (root / ".wiki-viva/pack-receipts/study-research").glob("remove-*.json")
    )


def test_remove_refuses_modified_bundle_before_mutation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    entry = load_lock(root)["packs"]["study-research"]
    (root / entry["installed_path"] / "README.md").write_text(
        "drift\n", encoding="utf-8"
    )
    before = _state_digest(root)
    with pytest.raises(PackError, match="installed_bundle_drift"):
        remove_pack(root, "study-research")
    assert _state_digest(root) == before
    assert "study-research" in load_lock(root)["packs"]


def test_remove_rolls_back_lock_and_receipt_when_bundle_delete_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    entry = load_lock(root)["packs"]["study-research"]
    installed = root / entry["installed_path"]

    def fail_owned_bundle(
        _path: Path, _entry: dict[str, object]
    ) -> None:
        raise OSError("simulated owned-bundle deletion failure")

    monkeypatch.setattr(
        experience_pack_lifecycle,
        "_secure_delete_quarantined_bundle",
        fail_owned_bundle,
    )
    with pytest.raises(OSError, match="simulated owned-bundle deletion failure"):
        remove_pack(root, "study-research")

    assert "study-research" in load_lock(root)["packs"]
    assert installed.is_dir()
    assert not list(
        (root / ".wiki-viva/pack-receipts/study-research").glob("remove-*.json")
    )
    assert validate_installation(root)["status"] == "valid"


def test_install_rolls_back_bound_receipt_when_lock_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)

    def fail_lock_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated lock write failure")

    monkeypatch.setattr(
        experience_pack_lifecycle,
        "_atomic_write_lock",
        fail_lock_write,
    )
    with pytest.raises(OSError, match="simulated lock write failure"):
        install_pack(root, "study-research")

    assert load_lock(root)["packs"] == {}
    assert not (root / ".wiki-viva/packs/study-research/0.1.0").exists()
    assert not list(
        (root / ".wiki-viva/pack-receipts/study-research").glob("install-*.json")
    )
    assert validate_installation(root)["status"] == "valid"


def test_upgrade_rolls_back_bound_receipt_and_next_lock_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", version="0.1.0")
    previous = load_lock(root)
    _add_upgrade(root)
    original_delete = experience_pack_lifecycle._secure_delete_quarantined_bundle
    failure_injected = False

    def fail_old_bundle_once(
        quarantine: Path, entry: dict[str, object]
    ) -> None:
        nonlocal failure_injected
        if entry.get("version") == "0.1.0" and not failure_injected:
            failure_injected = True
            raise OSError("simulated old-bundle cleanup failure")
        original_delete(quarantine, entry)  # type: ignore[arg-type]

    monkeypatch.setattr(
        experience_pack_lifecycle,
        "_secure_delete_quarantined_bundle",
        fail_old_bundle_once,
    )
    with pytest.raises(OSError, match="simulated old-bundle cleanup failure"):
        upgrade_pack(root, "study-research")

    assert failure_injected is True
    assert load_lock(root) == previous
    assert (root / previous["packs"]["study-research"]["installed_path"]).is_dir()
    assert not (root / ".wiki-viva/packs/study-research/0.2.0").exists()
    assert not list(
        (root / ".wiki-viva/pack-receipts/study-research").glob("upgrade-*.json")
    )
    assert validate_installation(root)["status"] == "valid"


def test_remove_never_deletes_a_noncooperative_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research")
    entry = load_lock(root)["packs"]["study-research"]
    installed = root / entry["installed_path"]
    original_delete = experience_pack_lifecycle._secure_delete_quarantined_bundle
    replacement = b"external replacement must survive\n"

    def replace_after_quarantine(
        quarantine: Path, current: dict[str, object]
    ) -> None:
        installed.mkdir(parents=True)
        (installed / "DO-NOT-DELETE.txt").write_bytes(replacement)
        original_delete(quarantine, current)  # type: ignore[arg-type]

    monkeypatch.setattr(
        experience_pack_lifecycle,
        "_secure_delete_quarantined_bundle",
        replace_after_quarantine,
    )
    with pytest.raises(PackError, match="owned_bundle_cleanup_recovery_required"):
        remove_pack(root, "study-research")

    assert (installed / "DO-NOT-DELETE.txt").read_bytes() == replacement
    assert "study-research" not in load_lock(root)["packs"]
    assert list(
        (root / ".wiki-viva/pack-receipts/study-research").glob("remove-*.json")
    )


def test_lock_cannot_redirect_removal_into_user_content(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    user_page = root / "memories/studies/durable.md"
    user_page.parent.mkdir(parents=True)
    user_page.write_text("# Durable\n", encoding="utf-8")
    install_pack(root, "study-research")
    lock_path = root / "wiki.packs.lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    lock["packs"]["study-research"]["installed_path"] = "memories/studies"
    _write_yaml(lock_path, lock)
    with pytest.raises(PackError, match="lock_installed_path_outside_pack_namespace"):
        remove_pack(root, "study-research")
    assert user_page.read_text(encoding="utf-8") == "# Durable\n"


def test_active_dependents_block_disable_and_remove_before_mutation(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    target = _rename_pack(root, "dependent-tools")
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["dependencies"] = [{"id": "study-research", "version": ">=0.1 <1"}]
    _write_yaml(manifest_path, manifest)
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["dependent-tools"]["versions"]["0.1.0"]["manifest_sha256"] = _sha(
        manifest_path
    )
    registry["packs"]["dependent-tools"]["versions"]["0.1.0"]["tree_sha256"] = _tree_sha(
        target
    )
    _write_yaml(registry_path, registry)
    install_pack(root, "study-research")
    install_pack(root, "dependent-tools")
    before = _state_digest(root)
    with pytest.raises(PackError, match="dependent_pack_active"):
        disable_pack(root, "study-research")
    with pytest.raises(PackError, match="dependent_pack_active"):
        remove_pack(root, "study-research")
    assert _state_digest(root) == before


def test_two_compatible_packs_compose_independent_of_install_order(
    tmp_path: Path,
) -> None:
    roots = [_repo(tmp_path / "a"), _repo(tmp_path / "b")]
    for root in roots:
        _rename_pack(root, "citation-tools")
    install_pack(roots[0], "study-research")
    install_pack(roots[0], "citation-tools")
    install_pack(roots[1], "citation-tools")
    install_pack(roots[1], "study-research")
    left = compose_active_packs(roots[0])
    right = compose_active_packs(roots[1])
    assert left == right
    assert [row["id"] for row in left["packs"]] == ["citation-tools", "study-research"]
    knowledge = [
        row for row in left["slots"]["views"] if row["slot"] == "view.knowledge"
    ]
    assert [row["pack"] for row in knowledge] == ["citation-tools", "study-research"]


def test_pack_operation_guard_serializes_processes_and_lock_write_uses_cas(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path).resolve()
    context = mp.get_context("fork")
    first_entered = context.Event()
    release_first = context.Event()
    second_entered = context.Event()
    release_second = context.Event()
    first = context.Process(
        target=_hold_pack_operation_guard,
        args=(str(root), first_entered, release_first),
    )
    second = context.Process(
        target=_hold_pack_operation_guard,
        args=(str(root), second_entered, release_second),
    )
    first.start()
    assert first_entered.wait(5)
    second.start()
    assert not second_entered.wait(0.2)
    release_first.set()
    assert second_entered.wait(5)
    release_second.set()
    first.join(5)
    second.join(5)
    assert first.exitcode == 0
    assert second.exitcode == 0

    expected_empty = {
        "schema_version": "wiki_experience_pack_lock.v1",
        "core_version": CORE_VERSION,
        "packs": {},
    }
    install_pack(root, "study-research", enforce_git_gate=False)
    with pytest.raises(PackError, match="pack_lock_changed_during_operation"):
        experience_pack_lifecycle._atomic_write_lock(
            root,
            expected_empty,
            expected_lock=expected_empty,
        )
    assert list(load_lock(root)["packs"]) == ["study-research"]


def test_conflict_fails_before_any_mutation(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _rename_pack(root, "exclusive-graph", exclusive_view=True)
    install_pack(root, "study-research")
    before = _state_digest(root)
    with pytest.raises(PackError, match="exclusive_slot_conflict"):
        install_pack(root, "exclusive-graph")
    assert _state_digest(root) == before
    assert "exclusive-graph" not in load_lock(root)["packs"]


def test_explicit_conflict_is_symmetric(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = _rename_pack(root, "counter-pack")
    manifest_path = target / "pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["conflicts"] = ["study-research"]
    _write_yaml(manifest_path, manifest)
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["counter-pack"]["versions"]["0.1.0"]["manifest_sha256"] = _sha(
        manifest_path
    )
    registry["packs"]["counter-pack"]["versions"]["0.1.0"]["tree_sha256"] = _tree_sha(
        target
    )
    _write_yaml(registry_path, registry)
    install_pack(root, "study-research")
    with pytest.raises(PackError, match="pack_conflict"):
        install_pack(root, "counter-pack")


def test_upgrade_requires_declarative_migration_and_replaces_owned_version(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", version="0.1.0")
    old = root / load_lock(root)["packs"]["study-research"]["installed_path"]
    _add_upgrade(root)
    planned = upgrade_pack(root, "study-research", dry_run=True)
    assert planned["status"] == "dry_run"
    assert {tuple(sorted(change.items())) for change in planned["conceptual_diff"]} >= {
        tuple(
            sorted(
                {
                    "action": "delete_owned_bundle",
                    "path": ".wiki-viva/packs/study-research/0.1.0",
                }.items()
            )
        ),
        tuple(
            sorted(
                {
                    "action": "validate_declarative_migration",
                    "path": "migrations/upgrades/0.1.0-to-0.2.0.yaml",
                }.items()
            )
        ),
    }
    applied = upgrade_pack(root, "study-research")
    assert applied["status"] == "applied"
    entry = load_lock(root)["packs"]["study-research"]
    assert entry["version"] == "0.2.0"
    assert not old.exists()
    assert (root / entry["installed_path"]).is_dir()


def test_privacy_weakening_and_remote_assets_are_blocked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    manifest_path = root / "packs/study-research/pack.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["privacy"]["access_secrets"] = "allow"
    manifest["assets"]["allow_remote"] = True
    _write_yaml(manifest_path, manifest)
    registry = yaml.safe_load(
        (root / "packs/registry.yaml").read_text(encoding="utf-8")
    )
    registry["packs"]["study-research"]["versions"]["0.1.0"]["manifest_sha256"] = _sha(
        manifest_path
    )
    _write_yaml(root / "packs/registry.yaml", registry)
    with pytest.raises(PackError, match="core_secret_gate_cannot_be_weakened"):
        resolve_pack(root, "study-research")


def test_secret_and_public_pii_fail_without_echoing_raw_value(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh123456"
    fixture = root / "packs/study-research/fixtures/minimal/scenario.yaml"
    fixture.write_text(
        f"schema_version: fixture\nsecret_value: {secret}\n", encoding="utf-8"
    )
    with pytest.raises(PackError) as captured:
        # Refresh the registry pin because only the manifest is pinned; tree
        # scanning is what must reject the newly introduced credential.
        resolve_pack(root, "study-research")
    assert captured.value.code in {
        "pack_publication_privacy_blocked",
        "public_fixture_privacy_blocked",
    }
    assert secret not in str(captured.value)


def test_public_pack_tree_blocks_email_outside_fixture(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    email = "private.person@example.test"
    readme = root / "packs/study-research/README.md"
    readme.write_text(f"Contact {email}\n", encoding="utf-8")
    with pytest.raises(PackError) as captured:
        resolve_pack(root, "study-research")
    assert captured.value.code == "pack_publication_privacy_blocked"
    assert email not in str(captured.value)


def test_fixture_must_explicitly_be_public_and_synthetic(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    scenario_path = root / "packs/study-research/fixtures/minimal/scenario.yaml"
    scenario = yaml.safe_load(scenario_path.read_text(encoding="utf-8"))
    scenario["public_synthetic"] = False
    _write_yaml(scenario_path, scenario)

    with pytest.raises(PackError, match="public_fixture_contract_invalid"):
        resolve_pack(root, "study-research")


def test_asset_hash_mismatch_is_blocked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    asset = root / "packs/study-research/assets/test-image.png"
    asset.write_bytes(b"not-a-rendered-image")
    _write_yaml(
        root / "packs/study-research/assets/manifest.yaml",
        {
            "schema_version": "wiki_experience_pack_assets.v1",
            "assets": [
                {
                    "id": "test-image",
                    "path": "assets/test-image.png",
                    "sha256": "0" * 64,
                    "license": "CC0-1.0",
                    "optional": True,
                    "max_bytes": 4096,
                }
            ],
        },
    )
    with pytest.raises(PackError, match="asset_hash_mismatch"):
        resolve_pack(root, "study-research")


def test_unmanifested_asset_and_active_svg_are_blocked(tmp_path: Path) -> None:
    unmanifested_root = _repo(tmp_path / "unmanifested")
    (unmanifested_root / "packs/study-research/assets/rogue.png").write_bytes(
        b"not-an-approved-image"
    )
    with pytest.raises(PackError, match="unmanifested_asset"):
        resolve_pack(unmanifested_root, "study-research")

    svg_root = _repo(tmp_path / "active-svg")
    svg = svg_root / "packs/study-research/assets/active.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        "<script>alert(2)</script></svg>",
        encoding="utf-8",
    )
    _write_yaml(
        svg_root / "packs/study-research/assets/manifest.yaml",
        {
            "schema_version": "wiki_experience_pack_assets.v1",
            "assets": [
                {
                    "id": "active-svg",
                    "path": "assets/active.svg",
                    "sha256": _sha(svg),
                    "license": "CC0-1.0",
                    "optional": False,
                    "max_bytes": 4096,
                }
            ],
        },
    )
    with pytest.raises(PackError, match="active_svg_blocked"):
        resolve_pack(svg_root, "study-research")


def test_executable_pack_file_and_symlink_are_blocked(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    executable = root / "packs/study-research/operations/run.py"
    executable.write_text("raise SystemExit\n", encoding="utf-8")
    with pytest.raises(PackError, match="executable_pack_content_blocked"):
        resolve_pack(root, "study-research")
    executable.unlink()
    link = root / "packs/study-research/templates/escape.md"
    link.symlink_to(root / "wiki.templates.yaml")
    with pytest.raises(PackError, match="symlink_blocked"):
        resolve_pack(root, "study-research")


def test_semver_range_contract() -> None:
    assert version_satisfies(CORE_VERSION, ">=8.0 <9")
    assert version_satisfies("0.2.0", ">=0.1 <1")
    assert not version_satisfies("9.0.0", ">=8.0 <9")
    with pytest.raises(PackError, match="invalid_version_constraint"):
        version_satisfies("8.0.0", "^8")


def test_cli_inspect_preview_validate_and_dry_run(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    script = KIT_ROOT / "scripts/wiki_pack.py"
    for arguments, expected in (
        (["inspect", "study-research"], "wiki_experience_pack.v1"),
        (["preview", "study-research"], "wiki_experience_pack_preview.v1"),
        (["validate", "study-research"], "wiki_experience_pack_validation.v1"),
        (["install", "study-research", "--dry-run"], "wiki_experience_pack_plan.v1"),
    ):
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)["schema_version"] == expected
    assert not (root / ".wiki-viva").exists()
    assert not (root / "wiki.packs.lock.yaml").exists()


def test_cli_validate_all_checks_registry_sources_and_empty_composition(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(KIT_ROOT / "scripts/wiki_pack.py"),
            "--root",
            str(root),
            "validate",
            "--all",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "wiki_experience_pack_validation.v1"
    assert payload["status"] == "valid"
    assert [(row["id"], row["version"]) for row in payload["sources"]] == [
        ("study-research", "0.1.0")
    ]
    assert payload["installation"]["packs"] == []
    assert payload["installation"]["composition"]["packs"] == []


def test_cli_validate_requires_exactly_one_selector(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    script = KIT_ROOT / "scripts/wiki_pack.py"
    for arguments, code in (
        (["validate"], "validate_requires_pack_or_all"),
        (
            ["validate", "study-research", "--all"],
            "validate_all_rejects_pack_or_version",
        ),
        (
            ["validate", "--all", "--version", "0.1.0"],
            "validate_all_rejects_pack_or_version",
        ),
    ):
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert json.loads(result.stdout)["error"]["code"] == code


def test_cli_failure_uses_safe_structured_error(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(KIT_ROOT / "scripts/wiki_pack.py"),
            "--root",
            str(root),
            "inspect",
            "missing-pack",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["error"] == {"code": "pack_not_registered", "detail": "missing-pack"}


def test_dry_run_is_allowed_on_main_but_mutation_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo(tmp_path)
    (root / ".git").mkdir()
    monkeypatch.setattr(experience_pack_lifecycle, "_git_branch", lambda _root: "main")
    planned = install_pack(root, "study-research", dry_run=True)
    assert planned["status"] == "dry_run"
    assert not (root / ".wiki-viva").exists()
    with pytest.raises(PackError, match="protected_or_nonreview_branch"):
        install_pack(root, "study-research")


@pytest.mark.parametrize(
    ("mapping", "expected_code"),
    [
        ("time", "temporal_adapter_source_field_unknown"),
        ("state", "temporal_adapter_source_field_unknown"),
        ("provenance", "temporal_adapter_provenance_field_unknown"),
    ],
)
def test_temporal_adapter_rejects_undeclared_page_type_fields(
    tmp_path: Path,
    mapping: str,
    expected_code: str,
) -> None:
    root = _repo(tmp_path)
    path = root / "packs/study-research/temporal/profiles.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    adapter = document["adapters"]["study-research.learning-captured"]
    if mapping == "time":
        adapter["time"]["occurred_at"] = "captured_at_typo"
    elif mapping == "state":
        adapter["state"]["after"]["status"] = "status_typo"
    else:
        adapter["provenance"]["source_refs"]["fields"] = ["source_refs_typo"]
    _write_yaml(path, document)

    with pytest.raises(PackError, match=expected_code):
        resolve_pack(root, "study-research")


def test_temporal_adapter_rejects_unknown_lane(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    path = root / "packs/study-research/temporal/profiles.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["adapters"]["study-research.learning-captured"]["lane"] = "private"
    _write_yaml(path, document)

    with pytest.raises(PackError, match="temporal_adapter_lane_invalid"):
        resolve_pack(root, "study-research")


def test_registry_tree_pin_blocks_non_manifest_mutation_before_install(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    readme = root / "packs/study-research/README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nUnpinned mutation.\n",
        encoding="utf-8",
    )

    with pytest.raises(PackError, match="registry_tree_hash_mismatch"):
        resolve_pack(root, "study-research")
    with pytest.raises(PackError, match="registry_tree_hash_mismatch"):
        install_pack(root, "study-research", enforce_git_gate=False)
    assert load_lock(root)["packs"] == {}
    assert not (root / ".wiki-viva/packs/study-research").exists()
