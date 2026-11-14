from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/wiki_sync_from_kit.py"
requires_safe_drift = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK")
    or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd
    or os.stat not in os.supports_dir_fd or os.stat not in os.supports_follow_symlinks
    or os.access not in os.supports_dir_fd or os.access not in os.supports_follow_symlinks,
    reason="drift inspection requires POSIX no-follow and directory-relative reads",
)


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
    assert not any(key.startswith('_') for key in plan)
    assert plan["c1"]["add"] == ["generate.py", "portable/tool.txt"]
    assert before == _git(consumer, "status", "--porcelain") == ""
    assert not (consumer / "kit.lock").exists()


@pytest.mark.parametrize('content', [b'bad: [SYNTHETIC_PRIVATE_MARKER', b'\xffSYNTHETIC_PRIVATE_MARKER',
                                    b'date: 2024-13-01\nnote: SYNTHETIC_PRIVATE_MARKER\n',
                                    b'date: !!timestamp nonsense\nnote: SYNTHETIC_PRIVATE_MARKER\n',
                                    b'count: !!int SYNTHETIC_PRIVATE_MARKER\n'])
def test_lock_read_failure_does_not_echo_yaml_content(tmp_path: Path, content: bytes) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (consumer / 'kit.lock').write_bytes(content)
    result = _run(kit, consumer, manifest, '--dry-run')
    assert result.returncode == 2
    assert 'kit.lock' in result.stderr
    assert 'SYNTHETIC_PRIVATE_MARKER' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr


def test_lock_io_failure_does_not_echo_exception_text(tmp_path: Path, monkeypatch) -> None:
    import traceback
    sync = _sync_module()
    lock = tmp_path / 'kit.lock'
    def fail(_path, *args, **kwargs):
        raise OSError('SYNTHETIC_PRIVATE_MARKER')
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'read_text', fail)
        with pytest.raises(sync.SyncError) as error:
            sync._load_yaml(lock)
    assert 'kit.lock' in str(error.value)
    assert 'SYNTHETIC_PRIVATE_MARKER' not in ''.join(traceback.format_exception(error.value))


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


@pytest.mark.parametrize('kit_subdirectory', [False, True])
def test_sync_rejects_same_git_root_without_effects(tmp_path: Path, kit_subdirectory: bool) -> None:
    kit, _, manifest = _fixture(tmp_path)
    source = kit / 'portable' if kit_subdirectory else kit
    original = (kit / 'portable/tool.txt').read_bytes()
    before = _git(kit, 'status', '--porcelain')
    for args in (('--dry-run',), ('--allow-dirty',)):
        result = _run(source, kit, manifest, *args)
        assert result.returncode != 0
        assert 'kit and consumer must be different Git worktree roots' in result.stderr
        assert not (kit / 'derived.txt').exists()
        assert not (kit / 'kit.lock').exists()
        assert (kit / 'portable/tool.txt').read_bytes() == original
        assert _git(kit, 'status', '--porcelain') == before


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


@pytest.mark.parametrize('kind', ['modified', 'staged_addition', 'untracked', 'dirty_manifest'])
def test_dirty_kit_syncs_the_committed_revision(tmp_path: Path, kind: str) -> None:
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
    result = _run(kit, consumer, manifest, '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['source_sha'] == _git(kit, 'rev-parse', 'HEAD')
    assert not (consumer / 'kit.lock').exists()
    result = _run(kit, consumer, manifest)
    assert result.returncode == 0, result.stderr
    assert (consumer / 'portable/tool.txt').read_text() == 'v1\n'
    assert not (consumer / 'portable/new.txt').exists()


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


@pytest.mark.parametrize('marker', ['file', 'directory'])
@pytest.mark.parametrize('operation', ['add', 'change', 'remove'])
def test_sync_rejects_nested_repository_before_add_change_or_remove(tmp_path: Path, marker: str, operation: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    if operation != 'add':
        applied = _run(kit, consumer, manifest)
        assert applied.returncode == 0, applied.stderr
        if operation == 'change':
            (kit / 'portable/tool.txt').write_text('v2\n')
        else:
            (kit / 'portable/tool.txt').unlink()
        _git(kit, 'add', '-A')
        _git(kit, 'commit', '-qm', 'change selected portable files')
    else:
        (consumer / 'portable').mkdir()
    marker_path = consumer / 'portable/.git'
    if marker == 'file':
        marker_path.write_text('gitdir: elsewhere\n')
    else:
        marker_path.mkdir()
    sentinel = consumer / 'portable/sentinel.txt'
    sentinel.write_text('nested work preserved\n')
    target = consumer / 'portable/tool.txt'
    before = target.read_bytes() if target.exists() else None
    lock = consumer / 'kit.lock'
    prior_lock = lock.read_bytes() if lock.exists() else None
    for args in (('--dry-run', '--json'), ('--allow-dirty',)):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert 'consumer path crosses a nested repository' in result.stderr
        assert (target.read_bytes() if target.exists() else None) == before
        assert (lock.read_bytes() if lock.exists() else None) == prior_lock
        assert sentinel.read_text() == 'nested work preserved\n'


def test_sync_rechecks_nested_boundary_between_b0_and_write(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    (consumer / 'portable').mkdir()
    plan = sync.build_plan(kit, consumer, manifest, [])
    (consumer / 'portable/.git').mkdir()
    with pytest.raises(sync.SyncError, match='nested repository'):
        sync._copy_c1(kit, consumer, plan)
    assert not (consumer / 'portable/tool.txt').exists()
    assert not (consumer / 'kit.lock').exists()


def test_c1_refuses_consumer_root_changed_after_plan(tmp_path: Path) -> None:
    # All repositories in this test are synthetic and confined to tmp_path.
    _git(tmp_path, 'init', '-q')
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    # Simulate the selected root disappearing: Git now discovers the outer
    # synthetic repository instead of the originally selected consumer.
    (consumer / '.git').rename(consumer / '.git-disabled-for-test')
    assert Path(_git(consumer, 'rev-parse', '--show-toplevel')).resolve() == tmp_path.resolve()
    with pytest.raises(sync.SyncError, match='consumer path must be its Git root'):
        sync._copy_c1(kit, consumer, plan)
    assert (consumer / 'README.md').read_text() == 'consumer\n'
    assert not (consumer / 'generate.py').exists()
    assert not (consumer / 'portable').exists()
    assert not (consumer / 'kit.lock').exists()


def test_c1_refuses_new_repository_at_same_consumer_path(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    consumer.rename(tmp_path / 'earlier-consumer')
    _repo(consumer)
    before = _git(consumer, 'status', '--porcelain')
    with pytest.raises(sync.SyncError, match='consumer root changed after B0'):
        sync._copy_c1(kit, consumer, plan)
    assert not (consumer / 'portable').exists()
    assert not (consumer / 'generate.py').exists()
    assert not (consumer / 'kit.lock').exists()
    assert _git(consumer, 'status', '--porcelain') == before


def test_b0_refuses_consumer_root_replacement_during_inspection(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    original = sync._consumer_state
    def replace_after_observation(root, files):
        state = original(root, files)
        consumer.rename(tmp_path / 'earlier-consumer')
        _repo(consumer)
        return state
    monkeypatch.setattr(sync, '_consumer_state', replace_after_observation)
    with pytest.raises(sync.SyncError, match='consumer root changed during B0'):
        sync.build_plan(kit, consumer, manifest, [])
    assert not (consumer / 'kit.lock').exists()


def test_b0_refuses_consumer_root_replacement_during_dirty_check(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    original = sync._git_dirty
    def replace_before_dirty(root):
        consumer.rename(tmp_path / 'earlier-consumer')
        _repo(consumer)
        return original(root)
    monkeypatch.setattr(sync, '_git_dirty', replace_before_dirty)
    with pytest.raises(sync.SyncError, match='consumer root changed during B0'):
        sync.build_plan(kit, consumer, manifest, [])
    assert not (consumer / 'kit.lock').exists()


def test_consumer_root_identity_unavailable_fails_closed(tmp_path: Path, monkeypatch) -> None:
    sync = _sync_module()
    consumer = tmp_path / 'consumer'
    def unavailable(_self):
        raise OSError('synthetic unavailable identity')
    monkeypatch.setattr(Path, 'stat', unavailable)
    with pytest.raises(sync.SyncError, match='consumer root identity unavailable'):
        sync._consumer_root_identity(consumer)


@pytest.mark.parametrize('mode,inode,device', [(0o040755, 0, 1), (0o100644, 1, 1), (0o040755, 1, -1)])
def test_consumer_root_identity_rejects_unusable_stat(tmp_path: Path, monkeypatch, mode, inode, device) -> None:
    from types import SimpleNamespace
    sync = _sync_module()
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'stat', lambda _self: SimpleNamespace(st_mode=mode, st_ino=inode, st_dev=device))
        with pytest.raises(sync.SyncError, match='consumer root identity unavailable'):
            sync._consumer_root_identity(tmp_path)


@pytest.mark.parametrize('nested_repo', [False, True])
def test_consumer_subdirectory_is_not_a_git_root(tmp_path: Path, nested_repo: bool) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    enclosing = _repo(consumer / 'nested') if nested_repo else consumer
    target = enclosing / 'subdirectory'
    target.mkdir()
    sentinel = target / 'sentinel.txt'
    sentinel.write_text('preserve existing work\n')
    before = _git(enclosing, 'status', '--porcelain')
    for args in (('--dry-run', '--json'), ('--allow-dirty',)):
        result = _run(kit, target, manifest, *args)
        assert result.returncode != 0
        assert 'consumer path must be its Git root' in result.stderr
        assert sentinel.read_text() == 'preserve existing work\n'
        assert _git(enclosing, 'status', '--porcelain') == before
        assert not (target / 'portable').exists()
        assert not (target / 'kit.lock').exists()


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


@requires_safe_drift
def test_read_only_drift_inventory_reports_all_managed_changes_without_touching_wip(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    clean = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert clean.returncode == 0 and json.loads(clean.stdout)["drift"] == []
    (consumer / "generate.py").write_text("# committed synthetic drift\n")
    _git(consumer, "add", "generate.py")
    _git(consumer, "commit", "-qm", "committed drift")
    (consumer / "generate.py").write_text("# staged synthetic drift\n")
    _git(consumer, "add", "generate.py")
    (consumer / "generate.py").write_text("# unstaged synthetic drift\n")
    (consumer / "portable/tool.txt").unlink()
    (consumer / "untracked.txt").write_text("synthetic work in progress\n")
    before_status = _git(consumer, "status", "--porcelain=v1")
    before_lock = (consumer / "kit.lock").read_bytes()
    before_index = _git(consumer, "write-tree")
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "drift"
    assert [(row["path"], row["worktree"]["kind"]) for row in report["drift"]] == [
        ("generate.py", "file"), ("portable/tool.txt", "missing")
    ]
    assert all(row["expected"]["sha256"] for row in report["drift"])
    assert _git(consumer, "status", "--porcelain=v1") == before_status
    assert _git(consumer, "write-tree") == before_index
    assert (consumer / "kit.lock").read_bytes() == before_lock
    assert (consumer / "generate.py").read_text() == "# unstaged synthetic drift\n"
    assert (consumer / "untracked.txt").read_text() == "synthetic work in progress\n"
    assert not (consumer / "portable/tool.txt").exists()


@requires_safe_drift
def test_drift_inventory_detects_staged_change_when_worktree_matches_lock(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    target = consumer / "portable/tool.txt"
    original = target.read_bytes()
    target.write_text("staged synthetic change\n")
    _git(consumer, "add", "portable/tool.txt")
    target.write_bytes(original)
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 1, result.stderr
    row = next(row for row in json.loads(result.stdout)["drift"] if row["path"] == "portable/tool.txt")
    assert row["worktree"]["sha256"] == row["expected"]["sha256"]
    assert row["index"]["sha256"] != row["expected"]["sha256"]
    assert target.read_bytes() == original


@requires_safe_drift
def test_drift_inspection_ignores_hostile_git_environment_and_fsmonitor(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    alternate_index = tmp_path / "old-index"
    shutil.copyfile(consumer / ".git/index", alternate_index)
    target = consumer / "portable/tool.txt"
    original = target.read_bytes()
    target.write_text("staged synthetic change\n")
    _git(consumer, "add", "portable/tool.txt")
    target.write_bytes(original)
    marker = tmp_path / "fsmonitor-ran"
    hook = tmp_path / "synthetic-fsmonitor"
    hook.write_text(f'#!/bin/sh\nprintf invoked > {shlex.quote(str(marker))}\n')
    hook.chmod(0o755)
    _git(consumer, "config", "core.fsmonitor", str(hook))
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate_index))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 1, result.stderr
    row = next(row for row in json.loads(result.stdout)["drift"] if row["path"] == "portable/tool.txt")
    assert row["index"]["sha256"] != row["expected"]["sha256"]
    assert row["worktree"]["sha256"] == row["expected"]["sha256"]
    assert not marker.exists()
    assert target.read_bytes() == original


@requires_safe_drift
def test_drift_inspection_refuses_large_worktree_file_without_changing_it(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    target = consumer / "portable/tool.txt"
    with target.open("wb") as handle:
        handle.truncate(128 * 1024 * 1024 + 1)
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2 and "size limit" in result.stderr
    assert target.stat().st_size == 128 * 1024 * 1024 + 1


@requires_safe_drift
def test_drift_inspection_refuses_parent_symlink_swap(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tool.txt").write_text("outside synthetic sentinel\n")
    sync = _sync_module()
    original = sync._check_consumer_path

    def swap(root, rel):
        original(root, rel)
        if rel == "portable/tool.txt":
            (consumer / "portable").rename(consumer / "preserved")
            (consumer / "portable").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(sync, "_check_consumer_path", swap)
    with pytest.raises(sync.SyncError, match="unsafe or unreadable"):
        sync.inspect_drift(consumer)
    assert (outside / "tool.txt").read_text() == "outside synthetic sentinel\n"
    assert (consumer / "preserved/tool.txt").read_text() == "v1\n"


@pytest.mark.parametrize("relative", ["portable/tool.txt", "kit.lock"])
@requires_safe_drift
def test_drift_inspection_refuses_external_hardlink(tmp_path: Path, relative: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside synthetic sentinel\n")
    target = consumer / relative
    target.unlink()
    os.link(outside, target)
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2 and "hard-linked" in result.stderr
    assert result.stdout == ""
    assert outside.read_text() == "outside synthetic sentinel\n"


@requires_safe_drift
def test_drift_inventory_refuses_missing_lock_and_symlink_without_mutation(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    missing = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert missing.returncode == 2 and "kit.lock" in missing.stderr
    assert _run(kit, consumer, manifest).returncode == 0
    target = consumer / "portable/tool.txt"
    target.unlink()
    target.symlink_to(consumer / "generate.py")
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2 and "symlink" in result.stderr
    assert target.is_symlink()


@requires_safe_drift
def test_drift_inventory_refuses_c3_and_invalid_lock_metadata(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    command = _run(kit, consumer, manifest, "--inspect-drift", "--c3-command", "python3 generate.py")
    assert command.returncode == 2 and "cannot run C3" in command.stderr
    lock_path = consumer / "kit.lock"
    lock = yaml.safe_load(lock_path.read_text())
    lock["managed_files"]["portable/tool.txt"]["sha256"] = "invalid"
    lock_path.write_text(yaml.safe_dump(lock))
    before = lock_path.read_bytes()
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2 and "invalid managed file metadata" in result.stderr
    assert lock_path.read_bytes() == before
    lock_path.write_text("schema_version: wiki_viva_kit_lock.v1\nmanaged_files: {}\n")
    incomplete = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert incomplete.returncode == 2 and "incomplete provenance" in incomplete.stderr


@requires_safe_drift
def test_drift_inventory_refuses_lock_with_inconsistent_tree_digest(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    lock_path = consumer / "kit.lock"
    lock = yaml.safe_load(lock_path.read_text())
    lock["managed_files"]["portable/tool.txt"]["sha256"] = "0" * 64
    lock_path.write_text(yaml.safe_dump(lock))
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2 and "digest mismatch" in result.stderr


@requires_safe_drift
def test_drift_inventory_refuses_unmerged_index(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    oid = _git(consumer, "rev-parse", "HEAD:portable/tool.txt")
    entry = f"0 {'0' * 40}\tportable/tool.txt\n100644 {oid} 1\tportable/tool.txt\n100644 {oid} 2\tportable/tool.txt\n"
    result = subprocess.run(["git", "update-index", "--index-info"], cwd=consumer,
                            input=entry, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    inspected = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert inspected.returncode == 2 and "unmerged" in inspected.stderr
    assert (consumer / "portable/tool.txt").read_text() == "v1\n"


@requires_safe_drift
@pytest.mark.parametrize("mode", [0o641, 0o650, 0o644, 0o755])
def test_drift_inspection_uses_same_execute_mode_as_b0(tmp_path: Path, mode: int) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    target = consumer / "portable/tool.txt"
    target.chmod(mode)
    b0 = _run(kit, consumer, manifest, "--dry-run", "--json")
    inspected = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    expected_drift = os.access(target, os.X_OK)
    assert (b0.returncode != 0) == expected_drift
    assert (inspected.returncode == 1) == expected_drift


def test_drift_inspection_fails_closed_without_safe_directory_reads(tmp_path: Path, monkeypatch) -> None:
    sync = _sync_module()
    monkeypatch.setattr(sync.os, "supports_dir_fd", set())
    with pytest.raises(sync.SyncError, match="requires no-follow directory-relative reads"):
        sync._drift_worktree_file(tmp_path, "kit.lock")


@requires_safe_drift
def test_drift_inspection_never_lazy_fetches_missing_index_blob(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    remote = tmp_path / "promisor.git"
    subprocess.run(["git", "clone", "--bare", "--no-hardlinks", str(consumer), str(remote)],
                   check=True, capture_output=True)
    _git(consumer, "config", "remote.origin.url", str(remote))
    _git(consumer, "config", "remote.origin.promisor", "true")
    _git(consumer, "config", "remote.origin.partialclonefilter", "blob:none")
    oid = _git(consumer, "rev-parse", "HEAD:portable/tool.txt")
    missing_blob = consumer / ".git/objects" / oid[:2] / oid[2:]
    assert missing_blob.is_file()
    missing_blob.unlink()
    objects = consumer / ".git/objects"
    before = {p.relative_to(objects).as_posix() for p in objects.rglob("*") if p.is_file()}
    trace = tmp_path / "synthetic-git-trace"
    monkeypatch.setenv("GIT_TRACE", str(trace))
    result = _run(kit, consumer, manifest, "--inspect-drift", "--json")
    assert result.returncode == 2
    assert {p.relative_to(objects).as_posix() for p in objects.rglob("*") if p.is_file()} == before
    assert not missing_blob.exists()
    assert not trace.exists()  # inherited Git tracing is removed, not written


@requires_safe_drift
def test_drift_inspection_refuses_git_without_no_lazy_fetch(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic adoption")
    real_git = shutil.which("git")
    assert real_git
    bindir = tmp_path / "bin"
    bindir.mkdir()
    wrapper = bindir / "git"
    wrapper.write_text('#!/bin/sh\nfor arg in "$@"; do if [ "$arg" = "--no-lazy-fetch" ]; then exit 129; fi; done\n'
                       f'exec {shlex.quote(real_git)} "$@"\n')
    wrapper.chmod(0o755)
    lock_before = (consumer / "kit.lock").read_bytes()
    sync = _sync_module()
    monkeypatch.setattr(sync, "local_git_executable", lambda: str(wrapper))
    with pytest.raises(sync.SyncError, match="Git must support --no-lazy-fetch"):
        sync.inspect_drift(consumer)
    assert (consumer / "kit.lock").read_bytes() == lock_before


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


def test_committed_cockpit_config_collision_and_followup_b0(tmp_path: Path) -> None:
    consumer = _repo(tmp_path / "consumer")
    relative = "apps/wiki-cockpit/public/wiki-cockpit.config.json"
    kit_config = ROOT / relative
    target = consumer / relative
    target.parent.mkdir(parents=True)
    local_config = '{"mode":"local_operator","api_base":"/api"}\n'
    target.write_text(local_config)
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "consumer configuration")
    assert not _git(consumer, "status", "--porcelain")
    for args in (("--dry-run",), ()):
        result = _run_default(ROOT, consumer, *args)
        assert result.returncode != 0
        assert f"unmanaged consumer file conflicts: {relative}" in result.stderr
        assert target.read_text() == local_config
        assert not (consumer / "kit.lock").exists()

    # After the owner resolves the collision explicitly, adoption is stable.
    target.write_bytes(kit_config.read_bytes())
    _git(consumer, "add", relative)
    _git(consumer, "commit", "-qm", "resolve synthetic collision")
    applied = _run_default(ROOT, consumer)
    assert applied.returncode == 0, applied.stderr
    followup = _run_default(ROOT, consumer, "--dry-run", "--json")
    assert followup.returncode == 0, followup.stderr
    plan = json.loads(followup.stdout)
    assert plan["c1"]["add"] == plan["c1"]["change"] == []
    assert plan["c1"]["remove_previously_managed"] == []
    assert target.read_bytes() == kit_config.read_bytes()


def test_c1_replacement_preserves_ignored_hardlink(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (consumer / '.gitignore').write_text('local-copy.txt\n')
    _git(consumer, 'add', '.gitignore')
    _git(consumer, 'commit', '-qm', 'ignore local copy')
    assert _run(kit, consumer, manifest).returncode == 0
    _git(consumer, 'add', '.')
    _git(consumer, 'commit', '-qm', 'adopt first revision')
    target = consumer / 'portable/tool.txt'
    local_copy = consumer / 'local-copy.txt'
    os.link(target, local_copy)
    assert _git(consumer, 'status', '--porcelain') == ''
    (kit / 'portable/tool.txt').write_text('v2\n')
    _git(kit, 'add', 'portable/tool.txt')
    _git(kit, 'commit', '-qm', 'update portable file')

    result = _run(kit, consumer, manifest)

    assert result.returncode == 0, result.stderr
    assert target.read_text() == 'v2\n'
    assert local_copy.read_text() == 'v1\n'
    assert target.stat().st_ino != local_copy.stat().st_ino
    assert not list(target.parent.glob('.wiki-sync-*'))


def test_c1_cleans_temporary_file_when_addition_fails(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])

    def fail_link(source, target):
        raise OSError('synthetic addition failure')

    monkeypatch.setattr(sync.os, 'link', fail_link)
    with pytest.raises(OSError, match='synthetic addition failure'):
        sync._copy_c1(kit, consumer, plan)
    assert not list(consumer.rglob('.wiki-sync-*'))


@pytest.mark.parametrize('relative', ['portable/tool.txt', 'sync.yaml'])
def test_sync_uses_committed_bytes_when_skip_worktree_hides_edits(tmp_path: Path, relative: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    _git(kit, 'update-index', '--skip-worktree', relative)
    (kit / relative).write_text('hidden change\n')
    assert _git(kit, 'status', '--porcelain') == ''

    result = _run(kit, consumer, manifest)

    assert result.returncode == 0, result.stderr
    assert (consumer / 'portable/tool.txt').read_text() == 'v1\n'
    lock = yaml.safe_load((consumer / 'kit.lock').read_text())
    assert lock['source_sha'] == _git(kit, 'rev-parse', 'HEAD')
    import hashlib
    assert lock['managed_files']['portable/tool.txt']['sha256'] == hashlib.sha256(b'v1\n').hexdigest()


@pytest.mark.parametrize('stage', ['c2', 'c3'])
def test_sync_refuses_lock_when_generator_changes_c1(tmp_path: Path, stage: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    c3 = ()
    if stage == 'c2':
        (kit / 'generate.py').write_text(
            "from pathlib import Path\nPath('portable/tool.txt').write_text('changed')\n")
        _git(kit, 'add', 'generate.py')
        _git(kit, 'commit', '-qm', 'generator alters managed file')
    else:
        c3 = ('--c3-command',
              "python3 -c \"from pathlib import Path; Path('portable/tool.txt').write_text('changed')\"")

    result = _run(kit, consumer, manifest, *c3)

    assert result.returncode != 0
    assert 'managed C1 file changed during C2/C3' in result.stderr
    assert (consumer / 'portable/tool.txt').read_text() == 'changed'
    assert not (consumer / 'kit.lock').exists()


def test_actual_nested_git_repo_is_untouched_by_b0_and_allow_dirty_apply(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    nested = _repo(consumer / 'portable')
    sentinel = nested / 'independent.txt'
    sentinel.write_text('original synthetic work\n')
    _git(nested, 'add', 'independent.txt')
    _git(nested, 'commit', '-qm', 'nested baseline')
    sentinel.write_text('synthetic work in progress\n')
    before = sentinel.read_bytes()
    nested_status = _git(nested, 'status', '--porcelain')
    for args in (('--dry-run', '--json'), ('--allow-dirty',)):
        result = _run(kit, consumer, manifest, *args)
        assert result.returncode != 0
        assert 'consumer path crosses a nested repository' in result.stderr
        assert sentinel.read_bytes() == before
        assert _git(nested, 'status', '--porcelain') == nested_status
        assert not (nested / 'tool.txt').exists()
        assert not (consumer / 'kit.lock').exists()


def _manual_drift_lock(consumer: Path, entries: dict[str, bytes]):
    """Build a synthetic lock/index directly, without invoking sync."""
    import hashlib
    sync = _sync_module()
    managed = {}
    for rel, data in entries.items():
        path = consumer / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        managed[rel] = {'sha256': hashlib.sha256(data).hexdigest(), 'mode': '100644'}
    tree = [{'path': rel, **managed[rel]} for rel in sorted(managed)]
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': 'a' * 40,
            'manifest_sha256': 'b' * 64, 'portable_tree_sha256': sync._canonical_sha256(tree),
            'managed_files': managed}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    _git(consumer, 'add', '-A')
    _git(consumer, 'commit', '-qm', 'synthetic lock and files')
    return sync


@requires_safe_drift
def test_drift_rejects_protected_selection_before_managed_metadata_or_body(tmp_path, monkeypatch):
    consumer = _repo(tmp_path / 'consumer')
    protected = 'data/.WIKI-VIVA-PROTECTED/secret.txt'
    sync = _manual_drift_lock(consumer, {'a-normal.txt': b'normal', protected: b'synthetic'})
    monkeypatch.setattr(sync, '_check_consumer_path', lambda *_: pytest.fail('managed path resolved'))
    monkeypatch.setattr(sync, '_drift_index_states', lambda *_: pytest.fail('index selection opened'))
    original = sync._drift_worktree_file
    def only_lock(root, rel, **kwargs):
        if rel != 'kit.lock':
            pytest.fail('managed body opened')
        return original(root, rel, **kwargs)
    monkeypatch.setattr(sync, '_drift_worktree_file', only_lock)
    with pytest.raises(sync.SyncError, match='protected drift selection'):
        sync.inspect_drift(consumer)


@requires_safe_drift
def test_drift_human_output_escapes_terminal_control(tmp_path, monkeypatch, capsys):
    consumer = _repo(tmp_path / 'consumer')
    rel = 'synthetic-\x1b[31m-\x7f.txt'
    sync = _manual_drift_lock(consumer, {rel: b'original'})
    (consumer / rel).write_bytes(b'changed')
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--kit', str(consumer), '--consumer', str(consumer), '--inspect-drift'])
    assert sync.main() == 1
    output = capsys.readouterr().out
    assert '\x1b' not in output and '\x7f' not in output
    assert '\\u001b' in output and '\\u007f' in output
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--kit', str(consumer), '--consumer', str(consumer), '--inspect-drift', '--json'])
    assert sync.main() == 1
    output = capsys.readouterr().out
    assert '\x1b' not in output and '\x7f' not in output
    assert json.loads(output)['drift'][0]['path'] == rel


@requires_safe_drift
def test_drift_git_output_and_duration_are_bounded(tmp_path, monkeypatch):
    sync = _sync_module()
    with pytest.raises(sync.SyncError, match='exceeded limits'):
        sync._drift_git_run([sys.executable, '-c', 'print("x" * 10000)'], tmp_path, output_limit=64)
    monkeypatch.setattr(sync, 'DRIFT_GIT_TIMEOUT_SECONDS', 0.2)
    with pytest.raises(sync.SyncError, match='exceeded limits'):
        sync._drift_git_run([sys.executable, '-c', 'import time; time.sleep(3)'], tmp_path, output_limit=64)


def test_drift_fails_closed_without_nonblocking_open(tmp_path, monkeypatch):
    sync = _sync_module()
    monkeypatch.delattr(sync.os, 'O_NONBLOCK', raising=False)
    with pytest.raises(sync.SyncError, match='requires no-follow directory-relative reads'):
        sync._drift_worktree_file(tmp_path, 'kit.lock')


@requires_safe_drift
@pytest.mark.parametrize('missing_worktree', [False, True])
def test_drift_index_never_emits_descendants_of_selected_directory(tmp_path, monkeypatch, missing_worktree):
    import hashlib
    consumer = _repo(tmp_path / 'consumer')
    sync = _sync_module()
    nested = consumer / 'selected/.WIKI-VIVA-PROTECTED/synthetic.txt'
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b'synthetic protected body')
    expected = {'sha256': hashlib.sha256(b'expected file').hexdigest(), 'mode': '100644'}
    tree = [{'path': 'selected', **expected}]
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': 'a' * 40,
            'manifest_sha256': 'b' * 64, 'portable_tree_sha256': sync._canonical_sha256(tree),
            'managed_files': {'selected': expected}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    _git(consumer, 'add', '-A')
    _git(consumer, 'commit', '-qm', 'synthetic index')
    if missing_worktree:
        (consumer / 'selected').rename(consumer / 'elsewhere')
    original = sync._drift_git_run
    def inspect_output(*args, **kwargs):
        result = original(*args, **kwargs)
        assert b'.WIKI-VIVA-PROTECTED' not in result.output
        return result
    monkeypatch.setattr(sync, '_drift_git_run', inspect_output)
    report = sync.inspect_drift(consumer)
    assert report['status'] == 'drift'
    assert report['drift'][0]['index']['kind'] == 'missing'


@requires_safe_drift
@pytest.mark.parametrize('name', ['consumer ', 'consumer\n'])
def test_drift_accepts_git_root_with_trailing_whitespace(tmp_path, name):
    consumer = _repo(tmp_path / name)
    sync = _manual_drift_lock(consumer, {'synthetic.txt': b'original'})
    assert sync.inspect_drift(consumer)['status'] == 'clean'


def test_drift_rejects_overlapping_or_nul_selections_before_git():
    sync = _sync_module()
    for paths in (['parent', 'parent/child'], ['normal', 'bad\0path']):
        with pytest.raises(sync.SyncError):
            sync._validate_drift_selection(paths)


@requires_safe_drift
def test_drift_exact_pathspec_accepts_literal_special_names(tmp_path):
    consumer = _repo(tmp_path / 'consumer')
    entries = {'synthetic-[:]*?.txt': b'one', 'nested/other.txt': b'two'}
    sync = _manual_drift_lock(consumer, entries)
    report = sync.inspect_drift(consumer)
    assert report['status'] == 'clean' and report['managed_total'] == 2


@requires_safe_drift
def test_drift_rejects_case_variant_git_metadata_before_selection(tmp_path, monkeypatch):
    consumer = _repo(tmp_path / 'consumer')
    sync = _sync_module()
    expected = {'sha256': 'c' * 64, 'mode': '100644'}
    tree = [{'path': '.GIT/config', **expected}]
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': 'a' * 40,
            'manifest_sha256': 'b' * 64, 'portable_tree_sha256': sync._canonical_sha256(tree),
            'managed_files': {'.GIT/config': expected}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    monkeypatch.setattr(sync, '_check_consumer_path', lambda *_: pytest.fail('managed metadata inspected'))
    monkeypatch.setattr(sync, '_drift_index_states', lambda *_: pytest.fail('index selection opened'))
    with pytest.raises(sync.SyncError, match='unsafe or protected drift selection'):
        sync.inspect_drift(consumer)


@requires_safe_drift
def test_drift_rejects_physical_alias_of_reserved_component(tmp_path):
    consumer = _repo(tmp_path / 'consumer')
    sync = _sync_module()
    reserved = consumer / '.wiki-viva-protected'
    reserved.write_bytes(b'synthetic reserved')
    alias = consumer / 'synthetic-alias'
    os.link(reserved, alias)
    with pytest.raises(sync.SyncError, match='aliases a reserved component'):
        sync._drift_check_consumer_path(consumer, 'synthetic-alias')
    with pytest.raises(sync.SyncError, match='aliases a reserved component'):
        sync._drift_worktree_file(consumer, 'synthetic-alias')


@requires_safe_drift
def test_drift_rejects_intent_to_add_even_when_bytes_match(tmp_path):
    import hashlib
    consumer = _repo(tmp_path / 'consumer')
    sync = _sync_module()
    (consumer / 'empty.txt').write_bytes(b'')
    _git(consumer, 'add', '-N', 'empty.txt')
    expected = {'sha256': hashlib.sha256(b'').hexdigest(), 'mode': '100644'}
    tree = [{'path': 'empty.txt', **expected}]
    lock = {'schema_version': 'wiki_viva_kit_lock.v1', 'source_sha': 'a' * 40,
            'manifest_sha256': 'b' * 64, 'portable_tree_sha256': sync._canonical_sha256(tree),
            'managed_files': {'empty.txt': expected}}
    (consumer / 'kit.lock').write_text(yaml.safe_dump(lock))
    with pytest.raises(sync.SyncError, match='intent-to-add'):
        sync.inspect_drift(consumer)


@pytest.mark.parametrize('kind', ['file', 'symlink'])
def test_c1_add_does_not_replace_destination_created_at_install(tmp_path: Path, monkeypatch, kind: str) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    target = consumer / 'portable/tool.txt'
    outside = consumer / 'independent.txt'
    outside.write_text('independent synthetic data\n')
    real_link = os.link
    def race_link(source, destination):
        if Path(destination) == target:
            if kind == 'file':
                target.write_text('concurrent synthetic data\n')
            else:
                target.symlink_to(outside)
        return real_link(source, destination)
    monkeypatch.setattr(sync.os, 'link', race_link)
    with pytest.raises(sync.SyncError, match='consumer target changed before write'):
        sync._copy_c1(kit, consumer, plan)
    if kind == 'file':
        assert target.read_text() == 'concurrent synthetic data\n'
    else:
        assert target.is_symlink() and outside.read_text() == 'independent synthetic data\n'
    assert not list(consumer.rglob('.wiki-sync-*'))
    assert not (consumer / 'kit.lock').exists()


def test_c1_add_fails_closed_when_hardlinks_unavailable(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    def fail_link(*_args):
        raise OSError('synthetic hardlink unsupported')
    def forbidden_replace(*_args):
        pytest.fail('add must not fall back to replacement')
    monkeypatch.setattr(sync.os, 'link', fail_link)
    monkeypatch.setattr(sync.os, 'replace', forbidden_replace)
    with pytest.raises(OSError, match='synthetic hardlink unsupported'):
        sync._copy_c1(kit, consumer, plan)
    assert not (consumer / 'portable/tool.txt').exists()
    assert not list(consumer.rglob('.wiki-sync-*'))
    assert not (consumer / 'kit.lock').exists()


def test_c1_add_preserves_executable_mode_and_cleans_link(tmp_path: Path) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    (kit / 'portable/tool.txt').chmod(0o755)
    _git(kit, 'add', 'portable/tool.txt')
    _git(kit, 'commit', '-qm', 'synthetic executable')
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    sync._copy_c1(kit, consumer, plan)
    target = consumer / 'portable/tool.txt'
    assert target.read_text() == 'v1\n'
    assert target.stat().st_mode & 0o777 == 0o755
    assert target.stat().st_nlink == 1
    assert not list(consumer.rglob('.wiki-sync-*'))


def test_c1_change_still_cleans_temporary_when_replacement_fails(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    assert _run(kit, consumer, manifest).returncode == 0
    (kit / 'portable/tool.txt').write_text('v2\n')
    _git(kit, 'add', 'portable/tool.txt')
    _git(kit, 'commit', '-qm', 'synthetic change')
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])
    assert 'portable/tool.txt' in plan['c1']['change']
    def fail_replace(*_args):
        raise OSError('synthetic replacement failure')
    monkeypatch.setattr(sync.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='synthetic replacement failure'):
        sync._copy_c1(kit, consumer, plan)
    assert (consumer / 'portable/tool.txt').read_text() == 'v1\n'
    assert not list(consumer.rglob('.wiki-sync-*'))
