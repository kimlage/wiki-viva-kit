"""Scoped canonical consumer inventory, synthetic bodies only."""
import pytest

from tests.test_folder_policy_v2 import project, put, commit
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_consumers_v2 import inventory_folder_consumers_v2, FolderConsumersError
from wiki_core.repository_reader import RepositoryReader


def setup_consumers(project):
    put(project, 'a/source.md', 'Source\n')
    put(project, 'a/consumer.md', '---\ninformation_requirements:\n  - target: a/source.md\n    fields: ["*"]\n    temporal: current\n    max_age_days: 30\n---\nConsumer\n')
    put(project, 'a/aux/b/private.md', 'Private sibling body\n')
    commit(project)
    return load_folder_policy_v2(project, 'HEAD')


def test_metadata_scope_excludes_other_owners_and_auxiliary_bodies(project, monkeypatch):
    policy = setup_consumers(project); original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path.startswith('a/aux/'):
            raise AssertionError('another owner or auxiliary body opened')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    out = inventory_folder_consumers_v2(project, policy, folder='a', scope='a')
    assert out['consumers'][0]['path'] == 'a/consumer.md'
    assert out['consumers'][0]['requirements'][0]['target'] == 'a/source.md'
    assert out['coverage'] == 'selected_authorized_paths_only'
    assert out['declarations'] == 'not_v2_receipts_or_read_proof'


def test_explicit_other_owner_denied_before_any_candidate_body(project, monkeypatch):
    policy = setup_consumers(project); original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path in ('a/consumer.md', 'a/aux/b/private.md'):
            raise AssertionError('candidate body opened before all permissions checked')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderConsumersError):
        inventory_folder_consumers_v2(project, policy, folder='a', candidates=['a/consumer.md', 'a/aux/b/private.md'])


def test_unresolved_page_id_fails_without_cataloguing_bodies(project, monkeypatch):
    policy = setup_consumers(project)
    put(project, 'a/consumer.md', '---\ninformation_requirements:\n  - target: opaque-page-id\n    fields: ["*"]\n    temporal: current\n    max_age_days: 30\n---\nConsumer\n'); commit(project)
    policy = load_folder_policy_v2(project, 'HEAD'); original = RepositoryReader.read
    def spy(self, path, *args, **kwargs):
        if path == 'a/source.md': raise AssertionError('page-id resolution scanned unrelated content')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(FolderConsumersError):
        inventory_folder_consumers_v2(project, policy, folder='a', candidates=['a/consumer.md'])


def test_retaining_one_unresolved_literal_never_resolves_other_targets(project):
    setup_consumers(project)
    put(project, 'a/consumer.md', '''---
information_requirements:
  - target: a/missing.md
    fields: ["*"]
    temporal: current
    max_age_days: 30
---
Consumer
''')
    commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    args = dict(folder='a', candidates=['a/consumer.md'])
    with pytest.raises(FolderConsumersError):
        inventory_folder_consumers_v2(project, policy, **args)
    out = inventory_folder_consumers_v2(project, policy, retain_unresolved_target='a/missing.md', **args)
    assert out['consumers'][0]['requirements'][0]['target'] == 'a/missing.md'
    with pytest.raises(FolderConsumersError):
        inventory_folder_consumers_v2(project, policy, retain_unresolved_target='a/other.md', **args)


def test_inventory_cli_uses_explicit_owner_and_reports_limited_coverage(project):
    import json
    import subprocess
    import sys
    from pathlib import Path
    setup_consumers(project)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_consumers_v2.py'
    proc = subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
                           '--folder', 'a', '--candidate', 'a/consumer.md'], capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout)
    assert result['selection'] == 'explicit_candidates_only'
    assert result['coverage'] == 'selected_authorized_paths_only'
    assert result['consumers'][0]['path'] == 'a/consumer.md'
    assert 'Private sibling body' not in proc.stdout + proc.stderr
