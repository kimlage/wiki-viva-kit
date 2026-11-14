"""Cross-platform coverage for the opt-in hook's selected interpreter."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'wiki_pre_push.py'


@pytest.fixture
def prepush(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('wiki_pre_push_selection_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('alias', ['python', 'python3', 'python.exe', 'python3.exe', 'PYTHON.EXE'])
def test_windows_aliases_bind_to_selected_interpreter(prepush, alias):
    selected = r'C:\work\example\.venv\Scripts\python.exe'
    command = [alias, '-c', 'import yaml']
    assert prepush.bind_python_command(command, executable=selected, windows=True) == [selected, '-c', 'import yaml']
    assert command[0] == alias


@pytest.mark.parametrize('alias', ['python', 'python3'])
def test_posix_aliases_bind_to_selected_interpreter(prepush, alias):
    assert prepush.bind_python_command([alias, '-c', 'import yaml'], executable='/tmp/venv/bin/python3', windows=False) == [
        '/tmp/venv/bin/python3', '-c', 'import yaml']


def test_explicit_or_versioned_executables_are_not_rewritten(prepush):
    for command in (['python3.12', '-V'], ['/opt/custom/python3', '-V'], ['py', '-3', '-V']):
        assert prepush.bind_python_command(command, executable='selected', windows=True) == command
    with pytest.raises(prepush.Blocked):
        prepush.bind_python_command(['python3', '-V'], executable='', windows=False)


@pytest.mark.skipif(os.name != 'nt', reason='real Windows wrapper and venv integration')
def test_windows_real_push_uses_selected_venv_for_python3(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    def git(cwd, *args):
        return subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=test@example.invalid',
                               '-c', 'commit.gpgsign=false', *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()
    git(root, 'init', '-q')
    git(root, 'config', 'core.autocrlf', 'false')
    (root / 'page.md').write_bytes(b'initial\n')
    git(root, 'add', 'page.md')
    git(root, 'commit', '-qm', 'initial')
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(remote)], check=True)
    git(root, 'remote', 'add', 'origin', str(remote))
    git(root, 'push', '-q', 'origin', 'HEAD:refs/heads/main')

    (root / '.git' / 'info' / 'exclude').write_text('/scripts\n/wiki_core\n/.venv\n', encoding='utf-8')
    scripts = root / 'scripts'
    scripts.mkdir()
    for name in ('_common.py', 'wiki_session_hook.py', 'wiki_pre_push.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    shutil.copytree(ROOT / 'wiki_core', root / 'wiki_core', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    venv = root / '.venv'
    subprocess.run([sys.executable, '-m', 'venv', '--system-site-packages', str(venv)], check=True)
    selected = venv / 'Scripts' / 'python.exe'
    assert subprocess.run([str(selected), '-c', 'import yaml'], capture_output=True).returncode == 0
    code = f'import pathlib,sys; assert pathlib.Path(sys.prefix).resolve() == pathlib.Path({str(venv)!r}).resolve()'
    try:
        external = subprocess.run(['python3', '-c', code], capture_output=True, text=True)
        assert external.returncode != 0
    except FileNotFoundError:
        pass
    (root / 'wiki.config.yaml').write_text(json.dumps({'pre_push': {'quick_commands': [['python3', '-c', code]]}}), encoding='utf-8')
    git(root, 'add', 'wiki.config.yaml')
    git(root, 'commit', '-qm', 'consumer gate')
    for name in ('page.md', 'wiki.config.yaml'):
        committed = subprocess.check_output(['git', 'show', f'HEAD:{name}'], cwd=root)
        assert committed == (root / name).read_bytes()
    subprocess.run([sys.executable, str(scripts / 'wiki_pre_push.py'), '--root', str(root), '--install'], check=True)
    result = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=root,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
