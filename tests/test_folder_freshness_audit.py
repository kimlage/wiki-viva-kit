import yaml
import pytest

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


@pytest.mark.parametrize('relevant', [False, True])
def test_config_change_requalifies_only_affected_folder_authority(query_repo, relevant):
    root, _ = query_repo
    base = prepare_consumer(root)
    git(root, 'checkout', '-qb', 'wiki/config-change')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    if relevant:
        config['context_access']['alpha']['policy']['deny']['read'].append('self/items/a.md')
    else:
        config['presentation'] = {'theme': 'synthetic'}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'change config')
    head = git(root, 'rev-parse', 'HEAD')
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    rows = [row for row in output['pending_reviews'] + output['blockers']
            if row.get('path') == 'alpha/consumer.md' and row['reason'].startswith('dynamic_query')]
    if relevant:
        assert any(row['reason'] == 'dynamic_query_requalification_required' for row in rows), rows
    else:
        assert not rows, rows


def test_unrelated_config_does_not_replay_unavailable_idle_receipt(query_repo, monkeypatch):
    root, _ = query_repo
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1]); data['information_requirements'][0]['selected_digest'] = '0' * 64
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'unavailable receipt')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/unrelated-config')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text()); config['presentation'] = {'theme': 'synthetic'}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'unrelated config')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.dynamic_query_audit as qa
    monkeypatch.setattr(qa, 'reproduce_query', lambda *args, **kwargs: pytest.fail('unaffected query replayed'))
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert not any(row.get('path') == 'alpha/consumer.md' and row['reason'].startswith('dynamic_query')
                   for row in output['blockers'] + output['pending_reviews'])


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


def test_unchanged_legacy_history_warns_without_replay_in_scoped_audit(query_repo, monkeypatch):
    import shutil
    root, _ = query_repo
    # Keep the synthetic tracked member visible in both graph snapshots.
    shutil.rmtree(root / 'alpha/items/clone/.git')
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1])
    receipt = data['information_requirements'][0]
    for key in ('authority_format', 'entry_folder', 'entry_index'):
        receipt.pop(key)
    receipt['temporal'] = 'historical'
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'preserve historical receipt')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/preserved-history')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['presentation'] = {'theme': 'synthetic'}
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'unrelated config')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.dynamic_query_audit as qa
    import wiki_core.freshness_impact as impact
    from scripts import wiki_audit as audit
    monkeypatch.setattr(qa, 'reproduce_query', lambda *args, **kwargs: pytest.fail('historical receipt replayed'))
    monkeypatch.setattr(audit, 'ROOT', root)
    reports = []
    def capture(*args, **kwargs):
        report = repository_report(*args, **kwargs)
        reports.append(report)
        return report
    monkeypatch.setattr(impact, 'repository_report', capture)
    errors, warnings = [], []
    audit.audit_freshness_budget(errors, warnings, load_config(root), base_ref=base,
                                 query_context='alpha', query_policy_revision=base, query_head=head)
    assert not errors
    assert 'alpha/consumer.md: historical query preserved; authorized revalidation not performed' in warnings
    assert reports[0]['query_revalidation']['affected'] == 0
    assert any(row['reason'] == 'historical_query_preserved_unverified' and not row['verification_performed']
               for row in reports[0]['pending_reviews'])


def test_renamed_historical_query_member_is_still_affected(query_repo):
    import shutil
    root, _ = query_repo
    shutil.rmtree(root / 'alpha/items/clone/.git')
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1])
    receipt = data['information_requirements'][0]
    for key in ('authority_format', 'entry_folder', 'entry_index'):
        receipt.pop(key)
    receipt['temporal'] = 'historical'
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'historical receipt')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/historical-rename')
    git(root, 'mv', 'alpha/items/a.md', 'alpha/moved.md')
    git(root, 'commit', '-qm', 'move member outside scope')
    head = git(root, 'rev-parse', 'HEAD')
    global_output = repository_report(root, load_config(root), base)
    assert any(row.get('path') == 'alpha/consumer.md' and 'revalidation' in row['reason']
               for row in global_output['blockers'])
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert 'alpha/items/a.md' in output['changed_paths']
    assert any(row.get('path') == 'alpha/consumer.md' and 'requalification' in row['reason']
               for row in output['blockers'] + output['pending_reviews'])
    assert not any(row.get('path') == 'alpha/consumer.md' and row['reason'] == 'historical_query_preserved_unverified'
                   for row in output['pending_reviews'])
    git(root, 'mv', 'alpha/moved.md', 'alpha/items/a.md')
    path.write_text(path.read_text() + '\nChanged interpretation.\n')
    git(root, 'add', 'alpha/consumer.md'); git(root, 'commit', '-qm', 'edit historical consumer')
    head = git(root, 'rev-parse', 'HEAD')
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert any(row.get('path') == 'alpha/consumer.md' and 'revalidation' in row['reason']
               for row in output['blockers'])


def test_historical_query_with_current_dependent_blocks_unqualified_policy_change(query_repo):
    import shutil
    root, _ = query_repo
    shutil.rmtree(root / 'alpha/items/clone/.git')
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1])
    receipt = data['information_requirements'][0]
    for key in ('authority_format', 'entry_folder', 'entry_index'):
        receipt.pop(key)
    receipt['temporal'] = 'historical'
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    dependent = {'page_id': 'reader', 'page_type': 'action', 'action_state': 'open',
                 'information_requirements': [{'target': 'alpha/consumer.md', 'fields': ['*'],
                                               'temporal': 'current', 'max_age_days': 30}]}
    write(root, 'alpha/reader.md', '---\n' + yaml.safe_dump(dependent) + '---\nActive reader.\n')
    git(root, 'add', 'alpha/consumer.md', 'alpha/reader.md'); git(root, 'commit', '-qm', 'historical dependency')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/current-history-use')
    config = yaml.safe_load((root / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['deny']['read'].append('self/items/a.md')
    write(root, 'wiki.config.yaml', yaml.safe_dump(config))
    git(root, 'add', 'wiki.config.yaml'); git(root, 'commit', '-qm', 'revoke member')
    head = git(root, 'rev-parse', 'HEAD')
    for options in ({}, {'query_context': 'alpha', 'query_policy_revision': base, 'query_head': head}):
        output = repository_report(root, load_config(root), base, **options)
        assert any(row.get('path') == 'alpha/consumer.md'
                   and row['reason'] == 'dynamic_query_requires_authorized_revalidation'
                   for row in output['blockers'])
        assert not any(row.get('path') == 'alpha/consumer.md' and row['reason'] == 'historical_query_preserved_unverified'
                       for row in output['pending_reviews'])


@pytest.mark.parametrize('also_change_selected', [False, True])
def test_legacy_query_requalifies_when_unbound_rule_changes(query_repo, monkeypatch, also_change_selected):
    root, _ = query_repo
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1])
    folder_data = yaml.safe_load(raw[1])
    folder_data['page_id'] = 'folder-consumer'
    write(root, 'alpha/folder-consumer.md', '---\n' + yaml.safe_dump(folder_data) + '---\n' + raw[2])
    for name, state in [('idle', None), ('active', 'open')]:
        dependent = {'page_id': name, 'page_type': 'claim', 'information_requirements': [
            {'target': 'alpha/consumer.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30}]}
        if state: dependent['action_state'] = state
        write(root, f'alpha/{name}.md', '---\n' + yaml.safe_dump(dependent) + '---\nDependent.\n')
    write(root, 'alpha/other/AGENTS.md', '# Independent instructions\n')
    write(root, 'alpha/other/index.md', '# Independent index\n')
    other = {'page_id': 'other', 'page_type': 'claim', 'information_requirements': [
        {'target': 'alpha/consumer.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30}]}
    write(root, 'alpha/other/private-dependent.md', '---\n' + yaml.safe_dump(other) + '---\nDependent.\n')
    for key in ('authority_format', 'entry_folder', 'entry_index'):
        data['information_requirements'][0].pop(key)
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    write(root, 'rules.md', '# Historical rule\n')
    git(root, 'add', 'alpha/consumer.md', 'alpha/folder-consumer.md', 'alpha/idle.md', 'alpha/active.md', 'alpha/other', 'rules.md'); git(root, 'commit', '-qm', 'legacy receipt and rule')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/legacy-rule-review')
    write(root, 'rules.md', '# Changed historical rule\n')
    if also_change_selected:
        item = root / 'alpha/items/a.md'
        item.write_text(item.read_text().replace('amount: 5', 'amount: 9'))
        git(root, 'add', 'alpha/items/a.md')
    git(root, 'add', 'rules.md'); git(root, 'commit', '-qm', 'change legacy rule')
    head = git(root, 'rev-parse', 'HEAD')
    import wiki_core.freshness_impact as module
    monkeypatch.setattr(module, '_query_policy_change_marker', lambda *_args: (_ for _ in ()).throw(AssertionError('v1 manifest scan')))
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert any(row.get('path') == 'alpha/consumer.md' and row['reason'] == 'dynamic_query_requalification_required'
               and row['priority'] == 'on_demand' for row in output['pending_reviews'])
    assert not any(row.get('path') == 'alpha/consumer.md' for row in output['blockers'])
    folder_rows = [row for row in output['blockers'] + output['pending_reviews']
                   if row.get('path') == 'alpha/folder-consumer.md' and row['reason'].startswith('dynamic_query')]
    assert bool(folder_rows) == also_change_selected
    priorities = {row['path']: row['priority'] for row in output['pending_reviews']
                  if row['reason'] == 'upstream_interpretation_pending'}
    assert priorities['alpha/idle.md'] == 'on_demand'
    assert priorities['alpha/active.md'] == 'immediate'
    assert output['query_revalidation']['coverage_limit'] == 'outside_selected_context_not_assessed'
    assert not any(row['reason'] == 'dynamic_impact_authority_boundary' for row in output['blockers'])


def test_query_outside_authorized_owner_has_generic_limited_coverage(query_repo):
    root, _ = query_repo
    prepare_consumer(root)
    write(root, 'alpha/other/AGENTS.md', '# Independent instructions\n')
    write(root, 'alpha/other/index.md', '# Independent index\n')
    raw = (root / 'alpha/consumer.md').read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1]); data['page_id'] = 'other-consumer'
    write(root, 'alpha/other/private-consumer.md', '---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    git(root, 'add', 'alpha/other'); git(root, 'commit', '-qm', 'other owner query')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/other-query')
    item = root / 'alpha/items/a.md'
    item.write_text(item.read_text().replace('amount: 5', 'amount: 9'))
    git(root, 'add', 'alpha/items/a.md'); git(root, 'commit', '-qm', 'change selected value')
    head = git(root, 'rev-parse', 'HEAD')
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    assert output['query_revalidation']['coverage_limit'] == 'outside_selected_context_not_assessed'
    assert output['query_revalidation']['affected'] == 1
    assert not any(row.get('path') == 'alpha/other/private-consumer.md' and row['reason'].startswith('dynamic_query')
                   for row in output['blockers'] + output['pending_reviews'])


@pytest.mark.parametrize('case', ['selected', 'legacy_deferred', 'legacy_active', 'legacy_direct'])
def test_folder_dynamic_change_propagates_through_ordinary_and_query_consumers(query_repo, case):
    root, _ = query_repo
    prepare_consumer(root)
    path = root / 'alpha/consumer.md'
    raw = path.read_text().split('---\n', 2)
    data = yaml.safe_load(raw[1]); data['amount'] = 5
    if case != 'selected':
        for key in ('authority_format', 'entry_folder', 'entry_index'):
            data['information_requirements'][0].pop(key)
        write(root, 'rules.md', '# Historical rule\n')
    path.write_text('---\n' + yaml.safe_dump(data) + '---\n' + raw[2])
    dependent = {'page_id': 'ordinary', 'page_type': 'claim', 'information_requirements': [
        {'target': 'alpha/consumer.md', 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30}]}
    write(root, 'alpha/ordinary.md', '---\n' + yaml.safe_dump(dependent) + '---\nDependent.\n')
    git(root, 'add', 'alpha/consumer.md', 'alpha/ordinary.md')
    if case != 'selected': git(root, 'add', 'rules.md')
    git(root, 'commit', '-qm', 'ordinary dependent')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(root)
    from wiki_core.context_packet import qualify_folder_context
    qualify_folder_context(root, policy, 'alpha', 'alpha/aux', 'alpha/index.md', 100000)
    entry = {'target': 'alpha/collection.md', 'reason': 'interpret upstream', 'use': 'interpretation',
             'classification': 'context', 'query': {'scope': 'alpha', 'filters': {'page_id': 'consumer'},
             'field': 'amount', 'max_enumerated': 100, 'max_matches': 20, 'max_scan_bytes': 100000}}
    row, _, _ = select_query(policy, 'alpha', RepositoryReader(root, 'HEAD'), entry)
    req = {'target': entry['target'], 'fields': ['*'], 'temporal': 'current', 'max_age_days': 30,
           'consumed_revision': row['revision'], 'use': entry['use'], 'classification': entry['classification'],
           'query': entry['query'], 'members_digest': row['members_digest'], 'selected_digest': row['selected_digest'],
           'query_policy_revision': row['policy_revision'], 'authority_digest': row['authority_digest'],
           'authority_format': 'folder', 'entry_folder': row['entry_folder'], 'entry_index': row['entry_index']}
    if case != 'selected': req['selected_digest'] = '0' * 64
    query_consumer = {'page_id': 'downstream-query', 'page_type': 'claim', 'information_requirements': [req]}
    if case == 'legacy_active': query_consumer['action_state'] = 'open'
    write(root, 'alpha/downstream-query.md', '---\n' + yaml.safe_dump(query_consumer) + '---\nQuery consumer.\n')
    git(root, 'add', 'alpha/downstream-query.md'); git(root, 'commit', '-qm', 'query dependent')
    git(root, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'checkout', '-qb', 'wiki/folder-closure')
    if case in ('selected', 'legacy_direct'):
        item = root / 'alpha/items/a.md'; item.write_text(item.read_text().replace('amount: 5', 'amount: 9'))
        git(root, 'add', 'alpha/items/a.md')
    if case != 'selected':
        write(root, 'rules.md', '# Changed historical rule\n'); git(root, 'add', 'rules.md')
    git(root, 'commit', '-qm', 'selected input changed')
    head = git(root, 'rev-parse', 'HEAD')
    output = repository_report(root, load_config(root), base, query_context='alpha',
                               query_policy_revision=base, query_head=head)
    reasons = {(row['path'], row['reason']) for row in output['pending_reviews']}
    if case == 'selected':
        assert ('alpha/consumer.md', 'dynamic_query_changed') in reasons
        assert ('alpha/ordinary.md', 'upstream_interpretation_pending') in reasons
        assert ('alpha/downstream-query.md', 'dynamic_query_upstream_pending') in reasons
    elif case == 'legacy_deferred':
        assert any(row['path'] == 'alpha/downstream-query.md' and row['priority'] == 'on_demand'
                   and row['reason'] == 'dynamic_query_requires_authorized_revalidation' for row in output['pending_reviews'])
        assert not any(row['path'] == 'alpha/downstream-query.md' for row in output['blockers'])
    else:
        assert any(row['path'] == 'alpha/downstream-query.md' and row['reason'] == 'dynamic_query_requires_authorized_revalidation'
                   for row in output['blockers'])
