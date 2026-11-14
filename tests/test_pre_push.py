import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_pre_push.py'


@pytest.fixture(autouse=True)
def python_on_path(monkeypatch):
    monkeypatch.setenv('PATH', str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', ''))


def git(root, *args):
    return subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=test@example.invalid',
                           '-c', 'commit.gpgsign=false', *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'page.md').write_text('initial\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'initial')
    (root / '.git' / 'info' / 'exclude').write_text('/scripts\n')
    (root / 'scripts').symlink_to(SCRIPT.parent, target_is_directory=True)
    return root


def commit(root, text):
    (root / 'page.md').write_text(text)
    git(root, 'add', 'page.md')
    git(root, 'commit', '-qm', 'change')
    return git(root, 'rev-parse', 'HEAD')


def hook(root, old, new):
    update = f'refs/heads/topic {new} refs/heads/topic {old}\n'
    return subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), 'origin', 'example'],
                          input=update, capture_output=True, text=True, timeout=12)


def test_pushed_range_rejects_whitespace_and_secret_in_intermediate_commit(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    bad = commit(root, 'trailing  \n')
    assert hook(root, base, bad).returncode != 0
    token = 'sk-proj-' + 'a' * 48
    commit(root, 'token=' + token + '\n')
    final = commit(root, 'clean\n')
    result = hook(root, base, final)
    assert result.returncode != 0
    assert 'secret detected' in result.stderr
    assert token not in result.stderr


def test_consumer_commands_and_ten_second_target(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    marker = root / 'marker'
    config = {'pre_push': {'quick_commands': [[sys.executable, '-c',
              'from pathlib import Path; Path("marker").write_text("ran")']]}}
    (root / 'wiki.config.yaml').write_text(json.dumps(config))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'configure')
    new = git(root, 'rev-parse', 'HEAD')
    started = time.monotonic()
    result = hook(root, base, new)
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 10
    assert marker.read_text() == 'ran'
    (root / 'page.md').write_text('uncommitted\n')
    assert hook(root, base, new).returncode != 0


def test_install_and_real_push_blocks_bad_change(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    installed = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'],
                               capture_output=True, text=True)
    assert installed.returncode == 0, installed.stderr
    git(root, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
    commit(root, 'bad whitespace  \n')
    push = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=root,
                          capture_output=True, text=True, timeout=12)
    assert push.returncode != 0 and 'pre-push blocked' in push.stderr
    repeated = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'],
                              capture_output=True, text=True)
    assert repeated.returncode != 0


def test_deletion_only_does_not_execute_consumer_commands(tmp_path):
    root = repo(tmp_path)
    result = hook(root, git(root, 'rev-parse', 'HEAD'), '0' * 40)
    assert result.returncode == 0


def test_failed_consumer_check_and_invalid_configuration_block(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    config = root / 'wiki.config.yaml'
    config.write_text(json.dumps({'pre_push': {'quick_commands': [[sys.executable, '-c', 'raise SystemExit(3)']]}}))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'configure')
    assert hook(root, base, git(root, 'rev-parse', 'HEAD')).returncode != 0
    config.write_text('pre_push:\n  quick_commands: shell command\n')
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'invalid')
    assert hook(root, base, git(root, 'rev-parse', 'HEAD')).returncode != 0


def test_installed_hook_checks_the_invoking_worktree(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    other = tmp_path / 'other'
    git(root, 'worktree', 'add', '-qb', 'other', str(other))
    (other / 'scripts').symlink_to(SCRIPT.parent, target_is_directory=True)
    config = {'pre_push': {'quick_commands': [[sys.executable, '-c', 'raise SystemExit(4)']]}}
    (other / 'wiki.config.yaml').write_text(json.dumps(config))
    git(other, 'add', 'wiki.config.yaml')
    git(other, 'commit', '-qm', 'consumer failing check')
    push = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/other'], cwd=other,
                          capture_output=True, text=True, timeout=12)
    assert push.returncode != 0 and 'pre-push blocked' in push.stderr


def test_install_does_not_disable_an_existing_hook(tmp_path):
    root = repo(tmp_path)
    precommit = root / '.git' / 'hooks' / 'pre-commit'
    precommit.write_text('#!/bin/sh\nexit 0\n')
    precommit.chmod(0o755)
    installed = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'],
                               capture_output=True, text=True)
    assert installed.returncode != 0
    assert precommit.exists()
    assert subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=root).returncode != 0


@pytest.mark.skipif(sys.platform == 'win32', reason='the liveness check uses ps')
def test_timeout_terminates_consumer_command_and_descendant(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    pidfile = tmp_path / 'pid'
    code = ('import pathlib,subprocess,sys,time; '
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
            f'pathlib.Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(60)')
    (root / 'wiki.config.yaml').write_text(json.dumps({'pre_push': {'quick_commands': [[sys.executable, '-c', code]]}}))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'configure slow command')
    head = git(root, 'rev-parse', 'HEAD')
    update = f'refs/heads/topic {head} refs/heads/topic {base}\n'
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--timeout', '1.5', 'origin', 'example'],
                            input=update, capture_output=True, text=True, timeout=4)
    assert result.returncode != 0 and time.monotonic() - started < 3
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
    assert status.returncode != 0 or status.stdout.strip().startswith('Z')


def test_timeout_bounds_secret_scan_itself(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    head = commit(root, 'synthetic long text\n' * 500_000)
    update = f'refs/heads/topic {head} refs/heads/topic {base}\n'
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--timeout', '0.6', 'origin', 'example'],
                            input=update, capture_output=True, text=True, timeout=4)
    assert result.returncode != 0 and time.monotonic() - started < 2


def test_new_branch_does_not_trust_stale_remote_tracking_refs(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    secret = 'sk-proj-' + 'b' * 48
    commit(root, 'token=' + secret + '\n')
    git(root, 'update-ref', 'refs/remotes/origin/main', git(root, 'rev-parse', 'HEAD'))
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/topic'], cwd=root,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_worktree_cannot_remove_a_committed_failing_gate(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    config = root / 'wiki.config.yaml'
    config.write_text(json.dumps({'pre_push': {'quick_commands': [[sys.executable, '-c', 'raise SystemExit(5)']]}}))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'configure')
    head = git(root, 'rev-parse', 'HEAD')
    config.unlink()
    assert hook(root, base, head).returncode != 0
    config.write_text('pre_push:\n  quick_commands: []\n')
    assert hook(root, base, head).returncode != 0


def test_secret_in_commit_message_is_blocked(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'page.md').write_text('change\n')
    git(root, 'add', 'page.md')
    secret = 'sk-proj-' + 'c' * 48
    git(root, 'commit', '-qm', 'token=' + secret)
    result = hook(root, base, git(root, 'rev-parse', 'HEAD'))
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_secret_in_annotated_tag_is_blocked(tmp_path):
    root = repo(tmp_path)
    secret = 'sk-proj-' + 'd' * 48
    git(root, 'tag', '-a', 'synthetic', '-m', 'token=' + secret)
    tag = git(root, 'rev-parse', 'refs/tags/synthetic')
    update = f'refs/tags/synthetic {tag} refs/tags/synthetic {"0" * 40}\n'
    result = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root)],
                            input=update, capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_new_ref_can_use_live_remote_main_as_baseline(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    secret = 'sk-proj-' + 'e' * 48
    commit(root, 'token=' + secret + '\n')
    git(root, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
    commit(root, 'clean\n')
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/topic'], cwd=root,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr


def test_distinct_push_url_is_used_for_remote_baseline(tmp_path):
    root = repo(tmp_path)
    fetch = tmp_path / 'fetch.git'
    target = tmp_path / 'target.git'
    for remote in (fetch, target):
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(fetch))
    secret = 'sk-proj-' + 'f' * 48
    commit(root, 'token=' + secret + '\n')
    git(root, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
    git(root, 'remote', 'set-url', '--push', 'origin', str(target))
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/topic'], cwd=root,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_replace_refs_cannot_hide_a_secret_in_the_pushed_commit(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    clean = git(root, 'rev-parse', 'HEAD')
    secret = 'sk-proj-' + 'g' * 48
    original = commit(root, 'token=' + secret + '\n')
    git(root, 'replace', original, clean)
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/topic'], cwd=root,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_grafts_cannot_hide_a_secret_in_pushed_history(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    secret = 'sk-proj-' + 'h' * 48
    commit(root, 'token=' + secret + '\n')
    head = commit(root, 'clean\n')
    info = root / '.git' / 'info'
    info.mkdir(exist_ok=True)
    (info / 'grafts').write_text(head + '\n')
    result = hook(root, base, head)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_index_flags_cannot_hide_different_gate_inputs(tmp_path, flag):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    config = {'pre_push': {'quick_commands': [[sys.executable, '-c',
              'from pathlib import Path; assert Path("page.md").read_text() == "GOOD\\n"']]}}
    (root / 'wiki.config.yaml').write_text(json.dumps(config))
    (root / 'page.md').write_text('BAD\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'configure bad committed input')
    head = git(root, 'rev-parse', 'HEAD')
    (root / 'page.md').write_text('GOOD\n')
    git(root, 'update-index', flag, 'page.md')
    result = hook(root, base, head)
    assert result.returncode != 0 and 'index flags' in result.stderr


def test_secret_in_filename_is_blocked_without_disclosure(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    secret = 'sk-proj-' + 'i' * 48
    (root / secret).write_text('harmless\n')
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'add file')
    result = hook(root, base, git(root, 'rev-parse', 'HEAD'))
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_consumer_gate_rejects_mismatched_or_uninitialized_submodule(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    git(source, 'init', '-q')
    (source / 'page.md').write_text('BAD\n')
    git(source, 'add', '.')
    git(source, 'commit', '-qm', 'bad')
    root = tmp_path / 'parent'
    root.mkdir()
    git(root, 'init', '-q')
    git(root, '-c', 'protocol.file.allow=always', 'submodule', 'add', str(source), 'library')
    config = {'pre_push': {'quick_commands': [[sys.executable, '-c',
              'from pathlib import Path; assert Path("library/page.md").read_text() == "GOOD\\n"']]}}
    (root / 'wiki.config.yaml').write_text(json.dumps(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'parent')
    head = git(root, 'rev-parse', 'HEAD')
    git(root, 'config', 'submodule.library.ignore', 'all')
    good = commit(source, 'GOOD\n')
    git(root / 'library', '-c', 'protocol.file.allow=always', 'fetch', 'origin')
    git(root / 'library', 'checkout', '-q', good)
    result = hook(root, '0' * 40, head)
    assert result.returncode != 0
    # Even with ignore=all, a staged gitlink must not hide a different tree.
    git(root, 'add', 'library')
    result = hook(root, '0' * 40, head)
    assert result.returncode != 0 and 'check failed' in result.stderr
    git(root, 'reset', '-q', 'HEAD', '--', 'library')
    git(root, 'submodule', 'deinit', '-f', '--', 'library')
    result = hook(root, '0' * 40, head)
    assert result.returncode != 0


def test_clean_filter_cannot_hide_bytes_from_a_consumer_gate(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'config', 'filter.demo.clean', 'sed s/GOOD/BAD/g')
    (root / '.gitattributes').write_text('page.md filter=demo\n')
    (root / 'page.md').write_text('BAD\n')
    config = {'pre_push': {'quick_commands': [[sys.executable, '-c',
              'from pathlib import Path; assert Path("page.md").read_text() == "GOOD\\n"']]}}
    (root / 'wiki.config.yaml').write_text(json.dumps(config))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'configured filter')
    head = git(root, 'rev-parse', 'HEAD')
    (root / 'page.md').write_text('GOOD\n')
    result = hook(root, base, head)
    assert result.returncode != 0 and 'content differs' in result.stderr


def test_installed_hook_survives_removal_of_installing_worktree(tmp_path):
    root = repo(tmp_path)
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    other = tmp_path / 'temporary'
    git(root, 'worktree', 'add', '-qb', 'temporary', str(other))
    (other / 'scripts').symlink_to(SCRIPT.parent, target_is_directory=True)
    python = other / '.venv' / 'bin' / 'python3'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    subprocess.run([str(python), str(SCRIPT), '--root', str(other), '--install'], check=True)
    shutil.rmtree(other / '.venv')
    (other / 'scripts').unlink()
    git(root, 'worktree', 'remove', str(other))
    push = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=root,
                          capture_output=True, text=True, timeout=12)
    assert push.returncode == 0, push.stderr


@pytest.mark.skipif(sys.platform == 'win32', reason='symlink setup requires Unix permissions')
def test_consumer_check_rejects_tracked_directory_replaced_by_symlink(tmp_path):
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    directory = root / 'docs'
    directory.mkdir()
    (directory / 'page').write_text('synthetic\n')
    (root / 'wiki.config.yaml').write_text(json.dumps({'pre_push': {'quick_commands': [[sys.executable, '-c', 'pass']]}}))
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'configure')
    head = git(root, 'rev-parse', 'HEAD')
    outside = tmp_path / 'outside'
    directory.rename(outside)
    directory.symlink_to(outside, target_is_directory=True)
    result = hook(root, base, head)
    assert result.returncode != 0 and 'symlink' in result.stderr


def test_chained_url_rewrites_cannot_hide_secret_from_push_target(tmp_path):
    root = repo(tmp_path)
    target = tmp_path / 'target.git'
    other = tmp_path / 'other.git'
    for remote in (target, other):
        subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    secret = 'sk-proj-' + 'j' * 48
    commit(root, 'token=' + secret + '\n')
    git(root, 'push', '-q', str(other), 'HEAD:refs/heads/main')
    git(root, 'remote', 'add', 'origin', 'alias:')
    git(root, 'config', f'url.{target}.insteadOf', 'alias:')
    git(root, 'config', f'url.{other}.insteadOf', str(target))
    subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/topic'], cwd=root,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode != 0 and 'secret detected' in result.stderr
    assert secret not in result.stderr


def test_secret_object_read_never_uses_temporary_files(tmp_path, monkeypatch, capsys):
    import importlib.util
    import tempfile
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    secret = 'sk-proj-' + 'k' * 48
    head = commit(root, 'token=' + secret + '\n')
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('prepush_in_memory_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(tempfile, 'TemporaryFile', lambda *a, **k: pytest.fail('secret data must stay in memory'))
    with pytest.raises(module.Blocked, match='secret detected'):
        module.scan_objects(root, time.monotonic() + 10, head, base)
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err


@pytest.mark.skipif(sys.platform == 'win32', reason='SIGTERM and ps differ on Windows')
def test_sigterm_cleans_up_consumer_command_group(tmp_path):
    import signal
    root = repo(tmp_path)
    base = git(root, 'rev-parse', 'HEAD')
    pidfile = tmp_path / 'pid'
    code = ('import pathlib,subprocess,sys,time; '
            'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
            f'pathlib.Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(60)')
    (root / 'wiki.config.yaml').write_text(json.dumps({'pre_push': {'quick_commands': [[sys.executable, '-c', code]]}}))
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'slow consumer check')
    head = git(root, 'rev-parse', 'HEAD')
    update = f'refs/heads/topic {head} refs/heads/topic {base}\n'
    proc = subprocess.Popen([sys.executable, str(SCRIPT), '--root', str(root), 'origin', 'example'],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        proc.stdin.write(update)
        proc.stdin.close()
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pidfile.exists()
        pid = int(pidfile.read_text())
        os.kill(proc.pid, signal.SIGTERM)
        assert proc.wait(timeout=3) == 128 + signal.SIGTERM
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
        assert status.returncode != 0 or status.stdout.strip().startswith('Z')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        proc.stdout.close()
        proc.stderr.close()
