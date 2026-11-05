import yaml

from tests.test_folder_query import query_repo, query
from tests.test_folder_policy_core import repo, git, write, folder_policy
from wiki_core.config import load_config
from wiki_core.context_selection import select_query
from wiki_core.freshness_impact import repository_report
from wiki_core.repository_reader import RepositoryReader


def prepare_consumer(root):
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['paths'] = {'memory_root': 'alpha'}
    config['audit'] = {'freshness_scope': 'impact', 'information_impact': 'use_scoped'}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'configure freshness'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(root)
    from wiki_core.context_packet import qualify_folder_context
    qualify_folder_context(root, policy, 'alpha', 'alpha/aux', 'alpha/index.md', 100000)
    row, _, _ = select_query(policy, 'alpha', RepositoryReader(root, 'HEAD'), query())
    req = {'target': row['request']['target'], 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': row['revision'], 'use': row['request']['use'],
           'classification': row['request']['classification'], 'query': row['request']['query'],
           'members_digest': row['members_digest'], 'selected_digest': row['selected_digest'],
           'query_policy_revision': row['policy_revision'], 'authority_digest': row['authority_digest'],
           'authority_format': 'folder', 'entry_folder': row['entry_folder'], 'entry_index': row['entry_index']}
    page_data = {'page_id': 'consumer', 'page_type': 'claim', 'information_requirements': [req]}
    write(root, 'alpha/consumer.md', '---\n' + yaml.safe_dump(page_data) + '---\nInterpretation\n')
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'record consumption'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return git(root, 'rev-parse', 'HEAD')


def test_folder_dynamic_audit_detects_selected_change(query_repo, monkeypatch):
    root, _ = query_repo
    base = prepare_consumer(root)
    git(root, 'checkout', '-qb', 'wiki/folder-audit')
    item = root / 'alpha/items/a.md'
    item.write_text(item.read_text().replace('amount: 5', 'amount: 9'))
    git(root, 'add', 'alpha/items/a.md'); git(root, 'commit', '-qm', 'change selected value')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.freshness_impact as module
    monkeypatch.setattr(module, '_query_policy_change_marker', lambda *_args: (_ for _ in ()).throw(AssertionError('v1 manifest scan')))
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert any(row['reason'] == 'dynamic_query_changed' for row in output['pending_reviews'])
    assert not any(row['reason'] == 'dynamic_query_requires_authorized_revalidation' for row in output['blockers'])


def test_unrelated_agents_change_does_not_requalify_folder_query(query_repo, monkeypatch):
    root, _ = query_repo
    base = prepare_consumer(root)
    git(root, 'checkout', '-qb', 'wiki/unrelated-instructions')
    write(root, 'beta/AGENTS.md', '# Different unrelated instruction\n')
    git(root, 'add', 'beta/AGENTS.md'); git(root, 'commit', '-qm', 'unrelated instruction change')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.dynamic_query_audit as qa
    original = qa.revalidate_affected
    calls = []
    def spy(*args, **kwargs):
        calls.append((kwargs['affected'], kwargs['changed']))
        return original(*args, **kwargs)
    monkeypatch.setattr(qa, 'revalidate_affected', spy)
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    unwanted = [row for row in output['pending_reviews'] + output['blockers']
                if row.get('path') == 'alpha/consumer.md' and row['reason'].startswith('dynamic_query')]
    assert not unwanted, (unwanted, calls)


def test_legacy_query_receipt_stays_unqualified_in_folder_audit(query_repo, monkeypatch):
    root, _ = query_repo
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1])
    receipt = data['information_requirements'][0]
    for key in ('authority_format', 'entry_folder', 'entry_index'): receipt.pop(key)
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'legacy receipt'); git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/legacy-query-review')
    item = root / 'alpha/items/a.md'
    item.write_text(item.read_text().replace('amount: 5', 'amount: 9'))
    git(root, 'add', 'alpha/items/a.md'); git(root, 'commit', '-qm', 'change selected value')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.freshness_impact as module
    monkeypatch.setattr(module, '_query_policy_change_marker', lambda *_args: (_ for _ in ()).throw(AssertionError('v1 manifest scan')))
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert any(row.get('path') == 'alpha/consumer.md' and 'requalification' in row['reason']
               for row in output['blockers'] + output['pending_reviews'])
