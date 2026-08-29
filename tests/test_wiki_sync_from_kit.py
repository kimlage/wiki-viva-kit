from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/wiki_sync_from_kit.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Wiki Tests")
    return path


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    kit = _repo(tmp_path / "kit")
    consumer = _repo(tmp_path / "consumer")
    (kit / "portable").mkdir()
    (kit / "portable/tool.txt").write_text("v1\n", encoding="utf-8")
    (kit / "private").mkdir()
    (kit / "private/secret.txt").write_text("synthetic-blocked\n", encoding="utf-8")
    (kit / "generate.py").write_text(
        "from pathlib import Path\nPath('derived.txt').write_text('derived-v1\\n')\n", encoding="utf-8"
    )
    manifest = kit / "sync.yaml"
    manifest.write_text(
        "schema_version: wiki_viva_sync_manifest.v1\n"
        "portable:\n  allow: ['portable/**', generate.py]\n  block: ['private/**']\n"
        "c2_commands:\n  - [python3, generate.py]\n",
        encoding="utf-8",
    )
    _git(kit, "add", ".")
    _git(kit, "commit", "-qm", "fixture")
    (consumer / "README.md").write_text("consumer\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "consumer")
    return kit, consumer, manifest


def _run(kit: Path, consumer: Path, manifest: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--kit", str(kit), "--consumer", str(consumer), "--manifest", str(manifest), *args],
        text=True,
        capture_output=True,
        env=env,
    )


def _run_default(kit: Path, consumer: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--kit", str(kit), "--consumer", str(consumer), *args],
        text=True,
        capture_output=True,
        env=env,
    )


def _sync_module():
    spec = importlib.util.spec_from_file_location("wiki_sync_from_kit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_is_read_only_and_machine_readable(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    before = _git(consumer, "status", "--porcelain")
    result = _run(kit, consumer, manifest, "--dry-run", "--json")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan["mode"] == "B0_dry_run"
    assert plan["c1"]["add"] == ["generate.py", "portable/tool.txt"]
    assert before == _git(consumer, "status", "--porcelain") == ""
    assert not (consumer / "kit.lock").exists()


def test_apply_runs_c1_c2_explicit_c3_and_is_idempotent(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    c3 = "python3 -c \"from pathlib import Path; Path('consumer-owned.txt').write_text('c3\\n')\""
    first = _run(kit, consumer, manifest, "--c3-command", c3)
    assert first.returncode == 0, first.stderr
    assert (consumer / "portable/tool.txt").read_bytes() == (kit / "portable/tool.txt").read_bytes()
    assert (consumer / "derived.txt").read_text() == "derived-v1\n"
    assert (consumer / "consumer-owned.txt").read_text() == "c3\n"
    lock_before = (consumer / "kit.lock").read_bytes()
    assert yaml.safe_load(lock_before)["schema_version"] == "wiki_viva_kit_lock.v1"

    second = _run(kit, consumer, manifest, "--allow-dirty", "--c3-command", c3, "--json")
    assert second.returncode == 0, second.stderr
    assert (consumer / "kit.lock").read_bytes() == lock_before
    assert json.loads(second.stdout.split("\nAPPLIED", 1)[0])["c1"]["unchanged"] == 2


def test_apply_refuses_dirty_consumer_without_explicit_override(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (consumer / "README.md").write_text("dirty\n", encoding="utf-8")
    result = _run(kit, consumer, manifest)
    assert result.returncode == 2
    assert "apply requires a clean consumer" in result.stderr
    assert not (consumer / "portable/tool.txt").exists()


def test_only_previously_managed_stale_paths_are_removed(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "first sync")
    (consumer / "local.txt").write_text("keep\n", encoding="utf-8")
    _git(consumer, "add", "local.txt")
    _git(consumer, "commit", "-qm", "consumer file")

    (kit / "portable/tool.txt").unlink()
    _git(kit, "add", "-u")
    _git(kit, "commit", "-qm", "remove managed file")
    result = _run(kit, consumer, manifest)
    assert result.returncode == 0, result.stderr
    assert not (consumer / "portable/tool.txt").exists()
    assert (consumer / "local.txt").read_text() == "keep\n"


def test_blocklist_wins_and_executable_mode_is_preserved(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    tool = kit / "portable/tool.txt"
    tool.chmod(0o755)
    _git(kit, "add", "portable/tool.txt")
    _git(kit, "commit", "-qm", "executable")
    result = _run(kit, consumer, manifest)
    assert result.returncode == 0, result.stderr
    assert os.access(consumer / "portable/tool.txt", os.X_OK)
    assert not (consumer / "private/secret.txt").exists()


def test_recursive_glob_prefix_syncs_kit_skills_without_local_skills(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (kit / ".skills/wiki-viva").mkdir(parents=True)
    (kit / ".skills/wiki-viva/SKILL.md").write_text("portable skill\n", encoding="utf-8")
    (kit / ".skills/local-private").mkdir(parents=True)
    (kit / ".skills/local-private/SKILL.md").write_text("consumer-owned\n", encoding="utf-8")
    manifest.write_text(
        "schema_version: wiki_viva_sync_manifest.v1\n"
        "portable:\n  allow: ['.skills/wiki-*/**']\n  block: []\n"
        "c2_commands: []\n",
        encoding="utf-8",
    )
    _git(kit, "add", ".")
    _git(kit, "commit", "-qm", "portable skill fixture")

    result = _run(kit, consumer, manifest)

    assert result.returncode == 0, result.stderr
    assert (consumer / ".skills/wiki-viva/SKILL.md").read_bytes() == (
        kit / ".skills/wiki-viva/SKILL.md"
    ).read_bytes()
    assert not (consumer / ".skills/local-private").exists()


def test_default_manifest_is_the_canonical_upgrade_contract(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    canonical = kit / "docs/references/upgrades/sync-manifest.yaml"
    legacy = kit / "docs/references/upgrades/wiki-viva-v8/sync-manifest.yaml"
    canonical.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    canonical.write_bytes(manifest.read_bytes())
    legacy.write_text(
        "schema_version: wiki_viva_sync_manifest.v1\n"
        "portable:\n  allow: ['private/**']\n  block: []\n"
        "c2_commands: []\n",
        encoding="utf-8",
    )
    _git(kit, "add", ".")
    _git(kit, "commit", "-qm", "canonical and stale legacy manifests")

    default = _run_default(kit, consumer, "--dry-run", "--json")
    explicit = _run(kit, consumer, canonical, "--dry-run", "--json")

    assert default.returncode == explicit.returncode == 0
    default_plan = json.loads(default.stdout)
    explicit_plan = json.loads(explicit.stdout)
    assert default_plan["manifest_sha256"] == explicit_plan["manifest_sha256"]
    assert default_plan["portable_tree_sha256"] == explicit_plan["portable_tree_sha256"]
    assert default_plan["c1"] == explicit_plan["c1"]


def test_legacy_manifest_compatibility_copy_matches_canonical() -> None:
    canonical = ROOT / "docs/references/upgrades/sync-manifest.yaml"
    legacy = ROOT / "docs/references/upgrades/wiki-viva-v8/sync-manifest.yaml"

    assert legacy.read_bytes() == canonical.read_bytes()


def test_root_named_block_pattern_does_not_block_nested_fixture_contract() -> None:
    sync = _sync_module()

    assert sync._matches("wiki.config.yaml", "wiki.config.yaml")
    assert not sync._matches(
        "docs/references/fixtures/demo-wiki/wiki.config.yaml",
        "wiki.config.yaml",
    )


def test_published_contract_applies_c2_and_second_b0_is_unchanged(tmp_path: Path) -> None:
    consumer = _repo(tmp_path / "downstream")
    (consumer / "README.md").write_text("synthetic downstream\n", encoding="utf-8")
    _git(consumer, "add", "README.md")
    _git(consumer, "commit", "-qm", "synthetic downstream")

    first = _run_default(ROOT, consumer)
    assert first.returncode == 0, first.stderr
    for relative in (
        "docs/references/fixtures/demo-wiki/wiki.config.yaml",
        "docs/references/fixtures/demo-wiki/wiki.page-types.yaml",
        "docs/references/fixtures/demo-wiki/wiki.templates.yaml",
        "tests/test_build_demo.py",
        "tests/test_web_snapshot.py",
    ):
        assert (consumer / relative).is_file(), relative
    assert (consumer / "apps/wiki-cockpit/public/sample-snapshot/manifest.json").is_file()

    second = _run_default(ROOT, consumer, "--dry-run", "--json")
    assert second.returncode == 0, second.stderr
    plan = json.loads(second.stdout)
    assert plan["c1"]["add"] == []
    assert plan["c1"]["change"] == []
    assert plan["c1"]["remove_previously_managed"] == []
    assert plan["c1"]["unchanged"] == plan["c1"]["managed_total"]
