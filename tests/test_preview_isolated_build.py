"""The real build boundary, without network or reading consumer inputs."""
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from wiki_core.web import vercel_preview as preview


def archive(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as tar:
        parent = tarfile.TarInfo('apps'); parent.type = tarfile.DIRTYPE; tar.addfile(parent)
        for path, raw in files.items():
            item = tarfile.TarInfo('apps/wiki-cockpit/' + path)
            item.size = len(raw); item.mode = 0o644
            tar.addfile(item, io.BytesIO(raw))
    return output.getvalue()


def test_build_materializes_only_head_and_cleans_home(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv('VITE_PRIVATE_SENTINEL', 'do-not-copy')
    monkeypatch.setenv('NODE_OPTIONS', '--synthetic-option')
    monkeypatch.setattr(preview.shutil, 'which', lambda name: '/usr/bin/' + name)
    def git(root, *args):
        assert args == ('archive', '--format=tar', 'a'*40, 'apps/wiki-cockpit')
        return archive({'package.json': b'{}', 'package-lock.json': b'{}', 'src/public.ts': b'public'})
    monkeypatch.setattr(preview, '_git', git)
    def run(command, *, cwd, env, check, capture_output, timeout):
        calls.append((command, cwd, env))
        assert cwd != tmp_path and (cwd / 'src/public.ts').read_bytes() == b'public'
        assert not (cwd / 'private.ts').exists()
        assert 'VITE_PRIVATE_SENTINEL' not in env and 'NODE_OPTIONS' not in env
        assert env['HOME'] != os.environ.get('HOME')
        assert Path(env['NPM_CONFIG_USERCONFIG']).read_bytes() == b''
        assert Path(env['NPM_CONFIG_GLOBALCONFIG']).read_bytes() == b''
        assert timeout == 300 and check and capture_output
        if command[1:] == ['run', 'build']:
            dist = cwd / 'dist'; (dist / 'assets').mkdir(parents=True)
            (dist / 'index.html').write_text('synthetic')
            (dist / 'favicon.svg').write_text('<svg/>')
            (dist / 'assets/app.js').write_text('public')
    monkeypatch.setattr(preview.subprocess, 'run', run)
    (tmp_path / 'private.ts').write_text('do-not-copy')
    result = preview._build_frontend(tmp_path, 'a'*40)
    assert result['/assets/app.js'] == b'public'
    assert calls[0][0][1:] == ['ci', '--ignore-scripts', '--no-audit', '--no-fund']
    assert len(calls) == 2 and not calls[0][1].exists()


@pytest.mark.parametrize('path', ['.env.local', '.npmrc', 'node_modules/tool.js', '../escape'])
def test_build_refuses_ambient_or_unsafe_committed_inputs(tmp_path, monkeypatch, path):
    monkeypatch.setattr(preview.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(preview, '_git', lambda *args: archive({path: b'synthetic'}))
    with pytest.raises(ValueError):
        preview._build_frontend(tmp_path, 'a'*40)
