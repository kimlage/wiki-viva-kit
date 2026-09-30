"""Synthetic legacy-locale adoption through the published pack lifecycle."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from scripts.wiki_pack_adopt import adopt_pack
from wiki_core import _experience_pack_lifecycle as lifecycle
from wiki_core.experience_packs import (
    PackError, PackFile, load_lock, resolve_pack, upgrade_pack,
    validate_installation, validate_manifest,
)

KIT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _state(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def _legacy_repo(tmp_path: Path) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / "synthetic-wiki"
    root.mkdir()
    (root / "wiki.templates.yaml").write_text(yaml.safe_dump({
        "schema_version": "wiki_templates.v2", "packages": {
            "quadrant_lenses": {"blocks": []}, "gamification": {"blocks": []},
        },
    }))
    for name in ["personal-finance", "personal-finance-0.1.1"]:
        shutil.copytree(KIT / "packs" / name, root / "packs" / name)
    registry = yaml.safe_load((KIT / "packs/registry.yaml").read_text())
    registry["packs"] = {"personal-finance": registry["packs"]["personal-finance"]}
    (root / "packs/registry.yaml").write_text(yaml.safe_dump(registry))
    current = resolve_pack(root, "personal-finance", version="0.1.0")

    # Fixture-only construction of the earlier EN/PT bundle and its authentic
    # hash-bound lifecycle receipt. All bytes originate in this public kit;
    # no private consumer tree is read and no production validator is patched.
    legacy = root / "legacy-source"
    shutil.copytree(current.path, legacy)
    manifest = yaml.safe_load((legacy / "pack.yaml").read_text())
    manifest["i18n"]["locales"] = ["en", "pt-BR"]
    (legacy / "pack.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    (legacy / "i18n/es.yaml").unlink()
    files = tuple(PackFile(p.relative_to(legacy).as_posix(), _sha(p), p.stat().st_size)
                  for p in sorted(legacy.rglob("*")) if p.is_file())
    inventory = [{"path": p.path, "sha256": p.sha256, "size": p.size} for p in files]
    tree_sha = hashlib.sha256(json.dumps(inventory, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    source = replace(current, path=legacy, manifest=manifest, files=files,
                     manifest_sha256=_sha(legacy / "pack.yaml"), tree_sha256=tree_sha)
    with lifecycle._operation_guard(root, enabled=True):
        prior, lock, receipt = lifecycle._install_plan(
            root, source, action="install", branch="wiki/synthetic-locale-upgrade")
        lifecycle._copy_bundle(root, source)
        lifecycle._write_receipt(root, receipt)
        lifecycle._atomic_write_lock(root, lock, expected_lock=prior)

    personal = {
        "memories/finance/custom-monthly-close.md": b"# Tailored close\nKeep the user's own category convention.\n",
        "memories/finance/custom-category.md": b"# Custom category\nA synthetic local classification.\n",
        "wiki.config.yaml": b"repo_id: synthetic-pack-consumer\nlanguage: pt\nowner_label: Demo owner\n",
        "custom/templates/local-close.md": b"# Local template\nDo not replace this user-authored template.\n",
        ".wiki-viva/local-notes.md": b"Synthetic operator notes outside the owned pack bundle.\n",
    }
    for relative, raw in personal.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return root, personal


def test_published_finance_version_and_migration_are_coherent() -> None:
    source = resolve_pack(KIT, "personal-finance", version="0.1.1")
    prior = resolve_pack(KIT, "personal-finance", version="0.1.0")
    assert source.manifest["i18n"]["locales"] == ["en", "es", "pt-BR"]
    assert source.manifest["capabilities"] == prior.manifest["capabilities"]
    assert source.manifest["privacy"] == prior.manifest["privacy"]
    install = yaml.safe_load((source.path / "migrations/0001-install.yaml").read_text())
    upgrade = yaml.safe_load((source.path / "migrations/upgrades/0.1.0-to-0.1.1.yaml").read_text())
    assert install["to_version"] == source.version == "0.1.1"
    assert upgrade["from_version"] == "0.1.0" and upgrade["to_version"] == "0.1.1"
    assert upgrade["data_policy"] == "preserve_user_content"
    assert upgrade["steps"] == [{"action": "activate_pack_bundle"},
                                {"action": "register_capabilities"},
                                {"action": "deactivate_pack_bundle"}]


def test_legacy_upgrade_preserves_custom_content_and_is_repeat_safe(tmp_path: Path) -> None:
    root, personal = _legacy_repo(tmp_path)
    old = root / load_lock(root)["packs"]["personal-finance"]["installed_path"]
    with pytest.raises(PackError, match="required_pack_locales_missing"):
        validate_manifest(root, old, yaml.safe_load((old / "pack.yaml").read_text()))
    assert validate_installation(root)["errors"] == [
        {"code": "installed_manifest_contract_invalid", "pack": "personal-finance"}]
    before = _state(root)
    plan = adopt_pack(root, "personal-finance", "0.1.1", dry_run=True)
    assert plan["status"] == "dry_run"
    assert plan == adopt_pack(root, "personal-finance", "0.1.1", dry_run=True)
    assert _state(root) == before
    assert plan["receipt"]["mutation_scope"] == [
        ".wiki-viva/packs", ".wiki-viva/pack-receipts", "wiki.packs.lock.yaml"]
    assert plan["receipt"]["data_preservation"] == "user_content_untouched"
    result = adopt_pack(root, "personal-finance", "0.1.1")
    assert result["status"] == "applied"
    assert result["receipt"]["receipt_id"] == plan["receipt"]["receipt_id"]
    assert not old.exists()
    assert validate_installation(root)["errors"] == []
    entry = load_lock(root)["packs"]["personal-finance"]
    assert entry["version"] == "0.1.1" and entry["status"] == "active"
    assert len(entry["receipts"]) == 2
    for relative, raw in personal.items():
        assert (root / relative).read_bytes() == raw
    after = _state(root)
    assert adopt_pack(root, "personal-finance", "0.1.1")["status"] == "unchanged"
    assert adopt_pack(root, "personal-finance", "0.1.1", dry_run=True)["conceptual_diff"] == []
    assert _state(root) == after
    # The underlying upgrade retains its strict version rule; the explicit
    # C3 guard supplies replay safety without relaxing that rule.
    with pytest.raises(PackError, match="upgrade_requires_newer_version"):
        upgrade_pack(root, "personal-finance", version="0.1.1")
    assert _state(root) == after


def test_customized_immutable_bundle_is_refused_without_overwrite(tmp_path: Path) -> None:
    root, personal = _legacy_repo(tmp_path)
    entry = load_lock(root)["packs"]["personal-finance"]
    path = root / entry["installed_path"] / "templates/monthly-closing.md"
    path.write_text("# Local edit to an immutable bundle\nPreserve this for human resolution.\n")
    before = _state(root)
    with pytest.raises(PackError, match="installed_bundle_drift"):
        adopt_pack(root, "personal-finance", "0.1.1")
    assert _state(root) == before
    for relative, raw in personal.items():
        assert (root / relative).read_bytes() == raw


def test_repeat_adoption_refuses_drift_instead_of_reporting_unchanged(tmp_path: Path) -> None:
    root, _ = _legacy_repo(tmp_path)
    adopt_pack(root, "personal-finance", "0.1.1")
    entry = load_lock(root)["packs"]["personal-finance"]
    path = root / entry["installed_path"] / "i18n/es.yaml"
    path.write_text(path.read_text() + "\n# changed after install\n")
    before = _state(root)
    with pytest.raises(PackError, match="installed_pack_validation_failed"):
        adopt_pack(root, "personal-finance", "0.1.1")
    assert _state(root) == before
