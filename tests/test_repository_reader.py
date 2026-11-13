from pathlib import Path
import subprocess

import pytest

from wiki_core.content_sections import SectionError
from wiki_core.repository_reader import RepositoryReader, RepositoryReadError


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit(root):
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'synthetic fixture')
    return git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'synthetic@example.test')
    git(tmp_path, 'config', 'user.name', 'Synthetic fixture')
    (tmp_path / 'memories').mkdir()
    (tmp_path / 'memories/policy.md').write_text('---\npage_id: policy\npage_type: operational_rule\ncontext: system\ntitle: Policy\n---\n# Policy\n<!-- wiki:section id=criteria version=1 -->\n## Criteria\nApproved condition.\n### Exception\nKeep this exception.\n')
    (tmp_path / 'AGENTS.md').write_text('Preserve independent review.\n')
    commit(tmp_path)
    return tmp_path


def test_read_identity_fields_section_and_origin(repository):
    reader = RepositoryReader(repository)
    whole = reader.read('policy')
    assert whole['page_id'] == 'policy'
    assert whole['revision'] == git(repository, 'rev-parse', 'HEAD')
    assert whole['origin']['path'] == 'memories/policy.md'
    selected = reader.read('policy', section='criteria')
    assert selected['content'] == selected['text'].encode()
    assert 'Keep this exception.' in selected['text']
    assert selected['content_digest'] != whole['content_digest']
    assert reader.read('policy', field='context')['value'] == 'system'
    with pytest.raises(RepositoryReadError, match='missing frontmatter'):
        reader.read('policy', field='absent')
    with pytest.raises(SectionError, match='missing section'):
        reader.read('policy', section='absent')


def test_revision_stays_coherent_across_worktree_mutations_and_commits(repository):
    reader = RepositoryReader(repository)
    before = reader.read('policy')
    path = repository / 'memories/policy.md'
    path.write_text(path.read_text().replace('Approved condition.', 'Unapproved worktree change.'))
    assert reader.read('policy') == before
    assert RepositoryReader(repository).read('policy') == before
    commit(repository)
    assert reader.read('policy') == before
    assert RepositoryReader(repository).read('policy')['text'] != before['text']
    assert RepositoryReader(repository, before['revision']).read('policy') == before


def test_blob_size_reuse_keeps_read_guards(repository, monkeypatch):
    reader = RepositoryReader(repository)
    original_git = reader._git
    size_calls = []
    guards = []
    def tracked(*args):
        if args[:2] == ('cat-file', '-s'):
            size_calls.append(args[-1])
        return original_git(*args)
    monkeypatch.setattr(reader, '_git', tracked)
    assert reader.blob_size('memories/policy.md') > 0
    reader.read('memories/policy.md', before_blob=guards.append)
    before_second = len(guards)
    reader.read('memories/policy.md', before_blob=guards.append)
    assert len(size_calls) == 1
    assert len(guards) > before_second > 0


@pytest.mark.parametrize('ref', ['../outside.md', '/etc/passwd', 'memories/../AGENTS.md', '.git/config', '.env', 'secrets/token.md', 'memories\\policy.md'])
def test_unsafe_or_secret_paths_rejected(repository, ref):
    with pytest.raises(RepositoryReadError):
        RepositoryReader(repository).read(ref)


def test_committed_symlink_not_followed(repository):
    (repository / 'memories/link.md').symlink_to('policy.md')
    commit(repository)
    with pytest.raises(RepositoryReadError):
        RepositoryReader(repository).read('memories/link.md')


def test_filter_scope_precedes_blob_read_and_catalog_has_no_snippets(repository, monkeypatch):
    (repository / 'memories/restricted.md').write_text('---\npage_id: restricted\ncontext: private\n---\nRestricted synthetic body.\n')
    commit(repository)
    reader = RepositoryReader(repository)
    original = reader._document
    def guarded(path):
        assert path != 'memories/restricted.md'
        return original(path)
    monkeypatch.setattr(reader, '_document', guarded)
    query = reader.query(allowed_paths=['memories/policy.md'], filters={'context': 'system'})
    assert [row['page_id'] for row in query['pages']] == ['policy']
    assert 'text' not in query['pages'][0] and 'body' not in query['pages'][0]


def test_enumeration_fingerprint_detects_added_removed_pages(repository):
    before = RepositoryReader(repository).query(filters={'context': 'system'})
    (repository / 'memories/new.md').write_text('---\npage_id: new\ncontext: system\n---\nNew synthetic page.\n')
    commit(repository)
    after = RepositoryReader(repository).query(filters={'context': 'system'})
    assert before['selection_fingerprint'] != after['selection_fingerprint']
    assert len(after['pages']) == 2
    (repository / 'memories/new.md').unlink()
    commit(repository)
    assert len(RepositoryReader(repository).query()['pages']) == 1


def test_duplicate_page_ids_fail_explicit_lookup(repository):
    (repository / 'memories/duplicate.md').write_bytes((repository / 'memories/policy.md').read_bytes())
    commit(repository)
    with pytest.raises(RepositoryReadError, match='ambiguous'):
        RepositoryReader(repository).read('policy')


def test_narrow_selection_does_not_deliver_other_frontmatter(repository):
    reader = RepositoryReader(repository)
    assert reader.read('policy', section='criteria')['frontmatter'] == {}
    assert reader.read('policy', field='context')['frontmatter'] == {'context': 'system'}


def test_cli_requires_explicit_scope_revision_and_body_mode(repository):
    import json
    import sys
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_read.py'
    base = [sys.executable, str(script), '--root', str(repository), '--revision', 'HEAD',
            '--mode', 'read', '--allow-path', 'memories/policy.md', '--ref', 'policy']
    missing = subprocess.run(base, capture_output=True, text=True)
    assert missing.returncode != 0 and 'explicit selector' in missing.stderr
    selected = subprocess.run([*base, '--section', 'criteria'], check=True, capture_output=True, text=True)
    result = json.loads(selected.stdout)
    assert result['section'] == 'criteria'
    assert 'Keep this exception.' in result['text']
    assert result['policy_enforced'] is False
    assert 'frontmatter' not in result
    denied = subprocess.run([*base[:-1], 'AGENTS.md', '--whole-body'], capture_output=True, text=True)
    assert denied.returncode != 0
