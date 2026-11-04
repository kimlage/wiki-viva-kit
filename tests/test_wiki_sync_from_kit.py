from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
import pytest


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


@pytest.mark.parametrize('kind', ['modified', 'staged_addition', 'untracked', 'dirty_manifest'])
def test_dirty_kit_is_not_a_sha_backed_preview_or_apply(tmp_path: Path, kind: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    if kind == 'modified':
        (kit / 'portable/tool.txt').write_text('uncommitted\n')
    elif kind == 'staged_addition':
        (kit / 'portable/new.txt').write_text('staged\n')
        _git(kit, 'add', 'portable/new.txt')
    elif kind == 'dirty_manifest':
        manifest.write_text(manifest.read_text() + "\nc2_commands: [[python3, malicious.py]]\n")
    else:
        (kit / 'untracked.txt').write_text('work in progress\n')
    before = _git(consumer, 'status', '--porcelain')
    for args in (('--dry-run', '--json'), ('--allow-dirty',)):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert 'kit source changed or is dirty' in result.stderr
        assert _git(consumer, 'status', '--porcelain') == before
        assert not (consumer / 'kit.lock').exists()
        assert not (consumer / 'portable/tool.txt').exists()


def test_manifest_outside_commit_is_rejected_without_consumer_changes(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    external = tmp_path / 'external.yaml'
    external.write_bytes(manifest.read_bytes())
    for args in (('--dry-run',), ()):
        result = _run(kit, consumer, external, *args)
        assert result.returncode != 0
        assert 'sync manifest must belong to the kit' in result.stderr
        assert not (consumer / 'kit.lock').exists()
        assert not (consumer / 'portable').exists()


def test_b0_and_apply_reject_symlink_ancestor_before_any_read_or_delete(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'tool.txt').write_text('outside sentinel')
    (consumer / 'old.txt').write_text('preserve')
    import hashlib
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'managed_files': {
        'old.txt': {'sha256': hashlib.sha256(b'preserve').hexdigest(), 'mode': '100644'}}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    (consumer / 'portable').symlink_to(outside, target_is_directory=True)
    for args in (('--dry-run',), ('--allow-dirty',)):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert (outside / 'tool.txt').read_text() == 'outside sentinel'
        assert (consumer / 'old.txt').read_text() == 'preserve'


@pytest.mark.parametrize('unsafe', ['../outside', '/tmp/outside', 'a/../../outside', 'a\\outside', '.git/config'])
def test_untrusted_lock_paths_cannot_escape_or_delete(tmp_path: Path, unsafe: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    outside = tmp_path / 'outside'
    outside.write_text('sentinel')
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'managed_files': {
        unsafe: {'sha256': 'a' * 64, 'mode': '100644'}}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    for args in (('--dry-run',), ('--allow-dirty',)):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert outside.read_text() == 'sentinel'
        assert not (consumer / 'portable').exists()


def test_symlinked_lock_and_unavailable_nofollow_fail_before_writes(tmp_path: Path, monkeypatch, capsys) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    outside = tmp_path / 'external-lock'
    outside.write_text('sentinel')
    (consumer / 'kit.lock').symlink_to(outside)
    result = _run(kit, consumer, manifest, '--allow-dirty')
    assert result.returncode != 0 and outside.read_text() == 'sentinel'
    (consumer / 'kit.lock').unlink()
    sync = _sync_module()
    monkeypatch.setattr(sync.os, 'supports_dir_fd', set())
    assert sync.main(['--kit', str(kit), '--consumer', str(consumer), '--manifest', str(manifest)]) != 0
    assert 'safe no-follow sync is unavailable' in capsys.readouterr().err
    assert not (consumer / 'portable').exists()
    assert not (consumer / 'kit.lock').exists()


def test_dry_run_ignores_fake_git_and_git_trace_environment(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    fake_dir = tmp_path / 'fake-bin'
    fake_dir.mkdir()
    marker = tmp_path / 'fake-git-ran'
    fake = fake_dir / 'git'
    fake.write_text('#!/bin/sh\nprintf attempted > "' + str(marker) + '"\nexit 1\n')
    fake.chmod(0o700)
    trace = tmp_path / 'git-trace'
    monkeypatch.setenv('PATH', str(fake_dir))
    monkeypatch.setenv('GIT_TRACE', str(trace))
    result = _run(kit, consumer, manifest, '--dry-run', '--json')
    assert result.returncode == 0
    assert not marker.exists() and not trace.exists()
    assert not (consumer / 'kit.lock').exists()


@pytest.mark.parametrize('moment', ['before_copy', 'after_copy', 'target_changed'])
def test_source_or_target_race_never_runs_c2_c3_or_writes_lock(tmp_path: Path, monkeypatch, capsys, moment: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    original = sync._copy_c1
    def raced(kit_arg, consumer_arg, plan):
        if moment == 'before_copy':
            (kit / 'portable/tool.txt').write_text('raced source')
        original(kit_arg, consumer_arg, plan)
        if moment == 'after_copy':
            (kit / 'portable/tool.txt').write_text('raced source')
        if moment == 'target_changed':
            (consumer / 'portable/tool.txt').write_text('raced consumer')
    monkeypatch.setattr(sync, '_copy_c1', raced)
    c3_marker = consumer / 'c3-ran'
    c3 = f'{sys.executable} -c "from pathlib import Path; Path(\'c3-ran\').write_text(\'x\')"'
    rc = sync.main(['--kit', str(kit), '--consumer', str(consumer), '--manifest', str(manifest), '--c3-command', c3])
    assert rc != 0
    assert 'consumer may be partially changed' in capsys.readouterr().err
    assert not (consumer / 'derived.txt').exists()
    assert not c3_marker.exists()
    assert not (consumer / 'kit.lock').exists()
    if moment == 'before_copy':
        assert not (consumer / 'portable/tool.txt').exists()
    elif moment == 'after_copy':
        assert (consumer / 'portable/tool.txt').read_text() == 'v1\n'


def test_modified_previously_managed_file_is_not_pruned(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, 'add', '.')
    _git(consumer, 'commit', '-qm', 'prior adoption')
    (consumer / 'portable/tool.txt').write_text('local work in progress')
    (kit / 'portable/tool.txt').unlink()
    _git(kit, 'add', '-u')
    _git(kit, 'commit', '-qm', 'remove portable file')
    result = _run(kit, consumer, manifest, '--allow-dirty')
    assert result.returncode != 0
    assert (consumer / 'portable/tool.txt').read_text() == 'local work in progress'


def test_forged_lock_cannot_prune_path_not_in_historical_kit(tmp_path: Path) -> None:
    import hashlib
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': _git(kit, 'rev-parse', 'HEAD'),
            'manifest_sha256': sync._canonical_sha256(yaml.safe_load(manifest.read_text())),
            'managed_files': {'README.md': {'sha256': hashlib.sha256(b'consumer\n').hexdigest(), 'mode': '100644'}}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    result = _run(kit, consumer, manifest, '--allow-dirty')
    assert result.returncode != 0
    assert 'managed path was not selected by historical kit' in result.stderr
    assert (consumer / 'README.md').read_text() == 'consumer\n'


def test_unmanaged_ignored_collision_is_preserved_or_identical_noop(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (consumer / '.gitignore').write_text('portable/\n')
    _git(consumer, 'add', '.gitignore')
    _git(consumer, 'commit', '-qm', 'ignore local files')
    (consumer / 'portable').mkdir()
    target = consumer / 'portable/tool.txt'
    target.write_text('ignored local work')
    assert _git(consumer, 'status', '--porcelain') == ''
    for args in (('--dry-run',), ()):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert 'unmanaged consumer file conflicts' in result.stderr
        assert target.read_text() == 'ignored local work'
        assert not (consumer / 'kit.lock').exists()
    target.write_text('v1\n')
    before_inode = target.stat().st_ino
    result = _run(kit, consumer, manifest)
    assert result.returncode == 0, result.stderr
    assert target.read_text() == 'v1\n' and target.stat().st_ino == before_inode


def test_forged_lock_cannot_overwrite_ignored_work_with_matching_fake_hash(tmp_path: Path) -> None:
    import hashlib
    kit, consumer, manifest = _fixture(tmp_path)
    (consumer / '.gitignore').write_text('portable/\nkit.lock\n')
    _git(consumer, 'add', '.gitignore')
    _git(consumer, 'commit', '-qm', 'ignore local files')
    (consumer / 'portable').mkdir()
    target = consumer / 'portable/tool.txt'
    target.write_text('ignored personal work')
    sync = _sync_module()
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': _git(kit, 'rev-parse', 'HEAD'),
            'manifest_sha256': sync._canonical_sha256(yaml.safe_load(manifest.read_text())),
            'managed_files': {'portable/tool.txt': {
                'sha256': hashlib.sha256(b'ignored personal work').hexdigest(), 'mode': '100644'}}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    assert _git(consumer, 'status', '--porcelain') == ''
    for args in (('--dry-run',), ()):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert 'managed path differs from historical kit' in result.stderr
        assert target.read_text() == 'ignored personal work'


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


def test_root_named_block_pattern_does_not_block_nested_fixture_contract() -> None:
    sync = _sync_module()

    assert sync._matches("wiki.config.yaml", "wiki.config.yaml")
    assert not sync._matches(
        "docs/references/fixtures/demo-wiki/wiki.config.yaml",
        "wiki.config.yaml",
    )


def test_runtime_only_contract_preserves_consumer_and_second_b0_is_unchanged(tmp_path: Path) -> None:
    consumer = _repo(tmp_path / "downstream")
    (consumer / "README.md").write_text("synthetic downstream\n", encoding="utf-8")
    _git(consumer, "add", "README.md")
    _git(consumer, "commit", "-qm", "synthetic downstream")
    original_tree = _git(consumer, "rev-parse", "HEAD^{tree}")

    first = _run_default(ROOT, consumer)
    assert first.returncode == 0, first.stderr
    for relative in ("wiki_core/config.py", "scripts/wiki_audit.py", "docs/references/freshness-impact.md", "apps/wiki-cockpit/src/App.tsx", "apps/wiki-cockpit/e2e/downstream/operator-origin.spec.ts", "apps/wiki-cockpit/e2e/fixtures.ts"):
        assert (consumer / relative).is_file(), relative
    for relative in ("docs/references/fixtures/demo-wiki", "tests", "apps/wiki-cockpit/public/sample-snapshot", "scripts/wiki_build_demo.py"):
        assert not (consumer / relative).exists(), relative
    assert (consumer / "README.md").read_text() == "synthetic downstream\n"
    assert not list((consumer / "apps/wiki-cockpit/src").rglob("*.test.*"))
    assert not list((consumer / "apps/wiki-cockpit/src").rglob("*.fixture.json"))
    assert not (consumer / "apps/wiki-cockpit/src/data/fixtures").exists()
    assert not list((consumer / "apps/wiki-cockpit/scripts").glob("*.test.mjs"))
    # Exercise the installed contract, not only the manifest's path list.
    # Generic tests stay upstream; execute the consumer's actual local checks.
    cockpit = consumer / "apps/wiki-cockpit"
    for script in ("check-assets.mjs",):
        gate = subprocess.run(["node", str(cockpit / "scripts" / script)], cwd=cockpit, text=True, capture_output=True)
        assert gate.returncode == 0, gate.stdout + gate.stderr

    second = _run_default(ROOT, consumer, "--dry-run", "--json")
    assert second.returncode == 0, second.stderr
    plan = json.loads(second.stdout)
    assert plan["c1"]["add"] == []
    assert plan["c1"]["change"] == []
    assert plan["c1"]["remove_previously_managed"] == []
    assert plan["c1"]["unchanged"] == plan["c1"]["managed_total"]
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "adopt kit")
    _git(consumer, "revert", "--no-edit", "HEAD")
    assert _git(consumer, "rev-parse", "HEAD^{tree}") == original_tree


def test_retired_host_is_pruned_only_when_previously_managed(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    canonical = yaml.safe_load((ROOT / "docs/references/upgrades/sync-manifest.yaml").read_text())
    retired = "integrations/hermes/wiki-viva-board/**"
    assert retired not in canonical["portable"]["allow"]
    body = yaml.safe_load(manifest.read_text())
    body["portable"]["allow"].extend(["apps/wiki-cockpit/**", retired])
    manifest.write_text(yaml.safe_dump(body, sort_keys=False))
    paths = ["integrations/hermes/wiki-viva-board/plugin.js", "apps/wiki-cockpit/src/App.tsx"]
    for relative in paths:
        target = kit / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic portable source\n")
    _git(kit, "add", ".")
    _git(kit, "commit", "-qm", "previous host contract")
    assert _run(kit, consumer, manifest).returncode == 0
    unmanaged = consumer / "integrations/consumer-owned.txt"
    unmanaged.write_text("preserve consumer integration\n")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "consumer adoption")
    body["portable"]["allow"].remove(retired)
    manifest.write_text(yaml.safe_dump(body, sort_keys=False))
    _git(kit, "add", ".")
    _git(kit, "commit", "-qm", "retire host integration")
    planned = _run(kit, consumer, manifest, "--dry-run", "--json")
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["c1"]["remove_previously_managed"] == [paths[0]]
    assert (consumer / paths[0]).is_file()
    result = _run(kit, consumer, manifest)
    assert result.returncode == 0, result.stderr
    assert not (consumer / paths[0]).exists()
    assert (consumer / paths[1]).read_bytes() == (kit / paths[1]).read_bytes()
    assert unmanaged.read_text() == "preserve consumer integration\n"
    assert not (consumer / ".hermes").exists()
