"""Synthetic access-secret boundary for the low-level read CLI."""
import json
from pathlib import Path
import subprocess
import sys
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_read.py'
TOKEN = 'AKIA' + 'IOSFODNN7EXAMPLE'  # Public synthetic detector fixture.
GENERIC = 'aB3dE9fG2hJ7kL4mN8pQ5rS6tU1vW0xY'  # Synthetic high-entropy value.


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def fixture_repo(tmp_path):
    git(tmp_path, 'init', '-q'); git(tmp_path, 'config', 'user.email', 'synthetic@example.invalid'); git(tmp_path, 'config', 'user.name', 'Synthetic')
    (tmp_path/'page.md').write_text('---\npage_id: sample\npage_type: claim\ntitle: "Synthetic '+TOKEN+'"\nsafe: ordinary private detail\ncredential: '+TOKEN+'\napi_key: '+GENERIC+'\n---\n# Content\n<!-- wiki:section id=safe version=1 -->\n## Safe\nOrdinary private detail.\n<!-- wiki:section id=unsafe version=1 -->\n## Unsafe\n'+TOKEN+'\n')
    git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','synthetic'); old=git(tmp_path,'rev-parse','HEAD')
    (tmp_path/'page.md').write_text('---\npage_id: sample\ntitle: Current safe page\n---\n# Current\nNormal text.\n')
    git(tmp_path,'add','.'); git(tmp_path,'commit','-qm','safe current')
    return tmp_path,old


def invoke(repo,revision,*args):
    return subprocess.run([sys.executable,str(SCRIPT),'--root',str(repo),'--revision',revision,*args],capture_output=True,text=True)


@pytest.mark.parametrize('mode_args',[
    ('--mode','read','--allow-path','page.md','--ref','page.md','--whole-body'),
    ('--mode','read','--allow-path','page.md','--ref','page.md','--field','credential'),
    ('--mode','read','--allow-path','page.md','--ref','page.md','--section','unsafe'),
    ('--mode','catalog','--allow-path','page.md'),
])
def test_secret_output_is_refused_opaquely_at_historical_revision(fixture_repo,mode_args):
    root,old=fixture_repo; out=invoke(root,old,*mode_args)
    assert out.returncode != 0
    assert TOKEN not in out.stdout and TOKEN not in out.stderr
    assert out.stdout == ''


def test_safe_selections_and_current_content_remain_available(fixture_repo):
    root,old=fixture_repo
    for selector in [('--field','safe'),('--section','safe')]:
        out=invoke(root,old,'--mode','read','--allow-path','page.md','--ref','page.md',*selector)
        assert out.returncode == 0 and 'ordinary private detail' in out.stdout.lower()
    out=invoke(root,'HEAD','--mode','catalog','--allow-path','page.md')
    assert out.returncode == 0 and json.loads(out.stdout)['pages'][0]['title']=='Current safe page'


def test_error_and_argument_paths_never_echo_detected_values(fixture_repo):
    root,old=fixture_repo
    for args in [('--mode','read','--allow-path','page.md','--ref','page.md','--field',TOKEN),
                 ('--mode',TOKEN,'--allow-path','page.md')]:
        out=invoke(root,old,*args)
        assert out.returncode != 0 and TOKEN not in out.stdout and TOKEN not in out.stderr


def test_generic_key_selected_field_keeps_credential_name(fixture_repo):
    root,old=fixture_repo
    out=invoke(root,old,'--mode','read','--allow-path','page.md','--ref','page.md','--field','api_key')
    assert out.returncode != 0 and GENERIC not in out.stdout and GENERIC not in out.stderr


def test_exception_from_authored_section_marker_is_opaque(fixture_repo):
    root,_=fixture_repo
    (root/'bad.md').write_text('---\npage_id: bad\n---\n<!-- wiki:section id='+TOKEN+' version=1 -->\n## First\nText\n<!-- wiki:section id='+TOKEN+' version=1 -->\n## Second\nText\n')
    git(root,'add','.');git(root,'commit','-qm','synthetic invalid sections')
    out=invoke(root,'HEAD','--mode','read','--allow-path','bad.md','--ref','bad.md','--section','safe')
    assert out.returncode != 0 and TOKEN not in out.stdout and TOKEN not in out.stderr
    assert 'Traceback' not in out.stderr


def test_read_refuses_secret_in_returned_identity_metadata(fixture_repo):
    root,_=fixture_repo
    (root/'identity.md').write_text('---\npage_id: '+TOKEN+'\n---\n# Safe body\nOrdinary text.\n')
    git(root,'add','.');git(root,'commit','-qm','synthetic metadata')
    out=invoke(root,'HEAD','--mode','read','--allow-path','identity.md','--ref','identity.md','--whole-body')
    assert out.returncode != 0 and TOKEN not in out.stdout and TOKEN not in out.stderr
