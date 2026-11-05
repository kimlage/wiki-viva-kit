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


def test_c1_cleans_temporary_file_when_replacement_fails(tmp_path: Path, monkeypatch) -> None:
    kit, consumer, manifest = _fixture(tmp_path)
    sync = _sync_module()
    plan = sync.build_plan(kit, consumer, manifest, [])

    def fail_replace(source, target):
        raise OSError('synthetic replacement failure')

    monkeypatch.setattr(sync.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='synthetic replacement failure'):
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
