"""Public synthetic flow; a reported result is not an execution or integration."""
import subprocess

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit
from scripts.wiki_build_index import collect_page_chunks
from wiki_core.config import WikiConfig
from wiki_core.find import find
from wiki_core.folder_coordination_v2 import (
    FolderHostBinding, prepare_folder_packet, prepare_folder_preflight,
)
from wiki_core.folder_integration_v2 import preflight_folder_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_reassessment_host_v2 import prepare_folder_reassessment
from wiki_core.index import index_pages
from wiki_core.paths import WikiPaths
from wiki_core.repo_read import read_independent_repo


def test_nested_context_source_and_repo_flow_stops_at_independent_review(project):
    folder = 'a/aux/b'
    source = folder + '/source.md'
    output = folder + '/report.md'
    put(project, '.gitignore', folder + '/node/repo/\ndata/\n')
    put(project, folder + '/node/index.md', '---\npage_id: node\ncontext: system\n---\nnodeflowneedle\n')
    put(project, source, '---\npage_id: source\ncontext: system\namount: 5\n---\nSynthetic source\n')
    requirement = ('---\npage_type: claim\ninformation_requirements:\n  - target: ' + source +
                   '\n    fields: [field:amount]\n    temporal: current\n    max_age_days: 30\n'
                   '    classification: synthetic\n---\n')
    put(project, output, requirement + 'Original independent interpretation\n')

    repo = project / folder / 'node/repo'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Synthetic')
    git(repo, 'config', 'user.email', 'synthetic@example.invalid')
    git(repo, 'remote', 'add', 'origin', 'https://example.test/group/nested.git')
    put(repo, 'AGENTS.md', 'Independent synthetic repository instructions\n')
    put(repo, 'guide.md', '---\npage_id: repo-guide\ncontext: system\n---\nrepoflowneedle\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'independent synthetic repository')
    repo_sha = git(repo, 'rev-parse', 'HEAD')
    commit(project)
    assert git(project, 'check-ignore', folder + '/node/repo/guide.md') == folder + '/node/repo/guide.md'
    assert folder + '/node/repo/guide.md' not in git(project, 'ls-files').splitlines()
    base = git(project, 'rev-parse', 'HEAD')
    original_branch = git(project, 'branch', '--show-current')

    config = WikiConfig()
    config.paths['memory_root'] = folder
    paths = WikiPaths(project, config)
    index_pages(paths.indexes / 'wiki.sqlite', collect_page_chunks(project, paths, config))
    assert find(project, config, 'nodeflowneedle')['status'] == 'ok'
    assert find(project, config, 'repoflowneedle')['status'] == 'no_matches'
    independent = read_independent_repo(repo, 'example.test/group/nested', repo_sha, 'guide.md')
    assert independent['revision'] == repo_sha and 'repoflowneedle' in independent['text']
    assert independent['repository']['identity_evidence'] == 'configured_origin_not_remote_authentication'

    binding = FolderHostBinding(project, (folder,))
    task = {'folder': folder, 'approved_revision': base, 'content_revision': base,
            'task': {'index_path': folder + '/index.md', 'task_id': 'synthetic-flow',
                     'goal': 'inspect synthetic source', 'output': output, 'integrator': 'reviewer',
                     'max_bytes': 30000,
                     'evidence': [{'path': source, 'producer_folder': folder, 'reason': 'source',
                                   'use': 'interpret', 'classification': 'synthetic', 'field': 'amount'},
                                  {'path': output, 'producer_folder': folder, 'reason': 'prior output',
                                   'use': 'interpret', 'classification': 'synthetic'}]}}
    packet = prepare_folder_packet(project, binding, task)['packet']
    assert [row['path'] for row in packet['inputs'][:5]] == [
        'AGENTS.md', 'a/AGENTS.md', 'a/aux/AGENTS.md', folder + '/AGENTS.override.md', folder + '/index.md']
    assert next(row for row in packet['inputs'] if row['path'] == source)['text'] == '5'

    git(project, 'checkout', '-qb', 'wiki/synthetic-flow')
    put(project, output, requirement + 'Proposed independent interpretation\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed',
              'task_id': packet['task_id'], 'context_id': packet['context_id'],
              'packet_digest': packet['packet_digest'],
              'observed': [{'path': row['path'], 'kind': row['kind'], 'revision': row['revision'],
                            'sha256': row['sha256'], 'section': row.get('section'), 'field': row.get('field')}
                           for row in packet['inputs']],
              'changes': [{'path': output, 'action': 'modified'}]}
    policy = load_folder_policy_v2(project, base)
    preflight = preflight_folder_v2(project, policy, base=base, head=head, branch='wiki/synthetic-flow',
                                    packet=packet, result=result)
    assert preflight['state'] == 'independent_review_required'
    assert preflight['requirements_handling']['count'] == 1
    assert preflight['requirements_handling']['freshness'] == 'not_assessed'
    assert preflight['requirements_handling']['legacy_receipt_migration'] == 'not_performed'
    assert preflight['read_coverage'] == 'reported_not_independently_verified'
    assert preflight['merge'] == 'not_performed'
    bound = prepare_folder_preflight(project, binding, {'folder': folder, 'approved_revision': base,
            'base': base, 'head': head, 'branch': 'wiki/synthetic-flow', 'packet': packet, 'result': result})
    assert bound['preflight'] == preflight

    # The proposal is deliberately NOT merged. A simulated reported result
    # is not proof of execution; compare an independently updated source against
    # the previously existing approved consumer and keep verification pending.
    git(project, 'checkout', '-q', original_branch)
    put(project, source, '---\npage_id: source\ncontext: system\namount: 9\n---\nChanged source\n')
    commit(project)
    current = git(project, 'rev-parse', 'HEAD')
    payload = {'folder': folder, 'approved_revision': current, 'source': source, 'candidates': [output],
               'reports': [{'target': output, 'section': None, 'field': 'amount',
                            'packet': packet, 'result': result}]}
    report = prepare_folder_reassessment(project, binding, payload)['reassessment']
    assert report['consumers'][0]['state'] == 'review_pending'
    assert report['consumers'][0]['impact']['verification'] == 'reported_not_independently_verified'
    assert (project / output).read_text(encoding='utf-8').endswith('Original independent interpretation\n')
    with pytest.raises(subprocess.CalledProcessError):
        git(project, 'merge-base', '--is-ancestor', head, current)
