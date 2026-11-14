import json
import subprocess
import sys
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_pre_push.py'


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
