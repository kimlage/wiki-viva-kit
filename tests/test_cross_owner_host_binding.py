"""Cross-owner packet qualification is bound by the trusted in-process host."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_folder_policy_core import repo, git, write, enable_alpha, folder_policy
from wiki_core.context_packet import build_packet, qualify_folder_context
from wiki_core.context_policy import PolicyError
from wiki_core.coordination_context import CoordinationBinding, prepare_packet
from wiki_core.repository_reader import RepositoryReader
from wiki_core import coordination_context as coord
from wiki_core.context_requirements import requirements_from_result, RequirementError


def setup_shared(repo):
    enable_alpha(repo)
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    root_rule = {'from_context': '.', 'to_context': 'beta', 'selector': 'AGENTS.md',
                 'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    evidence_rule = {'from_context': 'beta', 'to_context': 'alpha', 'selector': 'beta/source.md',
                     'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'].append(root_rule)
    config['context_access']['alpha']['imports'].append(evidence_rule)
    config['context_access']['beta'] = {'owner': 'beta operator', 'imports': [copy.deepcopy(root_rule)],
        'exports': [copy.deepcopy(evidence_rule)], 'policy': {'read': ['self', 'AGENTS.md'], 'write': ['self']}}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, 'beta/source.md', '# Authorized synthetic source\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'authorize cross context')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return [{'ref': 'beta/source.md', 'producer': 'beta', 'reason': 'selected source',
             'use': 'interpretation', 'classification': 'context'}]


def selection(repo, evidence, binding):
    return build_packet(repo, folder_policy(repo), 'alpha', 'HEAD', evidence, 100000,
                        task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
                        entry_folder='alpha', trusted_binding=binding)


def test_packet_does_not_open_historically_denied_evidence(repo, monkeypatch):
    evidence = setup_shared(repo)
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['policy']['deny'] = {'read': ['beta/source.md']}
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'deny historical source')
    denied = git(repo, 'rev-parse', 'HEAD')
    config['context_access']['alpha']['policy'].pop('deny')
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'restore source access')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    original = RepositoryReader.read
    def guarded(reader, ref, **kwargs):
        assert not (reader.revision == denied and ref == 'beta/source.md'), 'denied historical evidence opened'
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='historical evidence read not authorized'):
        build_packet(repo, folder_policy(repo), 'alpha', denied, evidence, 100000,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=binding)


def test_packet_rejects_unapproved_content_before_opening_evidence(repo, monkeypatch):
    evidence = setup_shared(repo)
    branch = git(repo, 'branch', '--show-current')
    git(repo, 'checkout', '-qb', 'wiki/unapproved-content')
    write(repo, 'beta/source.md', '# Unapproved source\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'unapproved content')
    unapproved = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', branch)
    original = RepositoryReader.read
    def guarded(reader, ref, **kwargs):
        assert reader.revision != unapproved, 'unapproved body opened'
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='content revision is not approved'):
        build_packet(repo, folder_policy(repo), 'alpha', unapproved, evidence, 100000,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=binding)


def test_packet_rejects_history_from_changed_producer_owner(repo, monkeypatch):
    evidence = setup_shared(repo)
    old = git(repo, 'rev-parse', 'HEAD')
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['beta']['owner'] = 'new beta owner'
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change producer owner')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    original = RepositoryReader.read
    def guarded(reader, ref, **kwargs):
        assert not (reader.revision == old and ref == 'beta/source.md'), 'previous owner evidence opened'
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='historical evidence read not authorized'):
        build_packet(repo, folder_policy(repo), 'alpha', old, evidence, 100000,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=binding)


@pytest.mark.parametrize('denied_before', [True, False])
def test_impact_rechecks_historical_cross_owner_authority(repo, monkeypatch, denied_before):
    from wiki_core.context_requirements import assess_approved_impact
    setup_shared(repo)
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    if denied_before:
        config['context_access']['alpha']['policy']['deny'] = {'read': ['beta/source.md']}
        write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'deny historical evidence')
    before = git(repo, 'rev-parse', 'HEAD')
    config['context_access']['alpha']['policy'].pop('deny', None)
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    write(repo, 'beta/source.md', '# Changed source\n')
    requirement = {'target': 'beta/source.md', 'fields': ['*'], 'temporal': 'current',
                   'max_age_days': 30, 'consumed_revision': before,
                   'use': 'interpretation', 'classification': 'context'}
    write(repo, 'alpha/result.md', '---\n' + yaml.safe_dump({'page_id': 'result',
        'information_requirements': [requirement]}) + '---\nInterpretation\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'change and reference source')
    after = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'update-ref', 'refs/remotes/origin/main', after)
    opened = []
    original = RepositoryReader.read
    def spy(reader, ref, **kwargs):
        if ref == 'beta/source.md' and reader.revision == before:
            opened.append(ref)
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    binding = CoordinationBinding(('.', 'alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    result = assess_approved_impact(repo, folder_policy(repo), consumers=['alpha/result.md'],
        before=before, after=after, destination_context='alpha', trusted_binding=binding)
    if denied_before:
        assert not opened and not result['candidates']
        assert 'some connections unavailable' in result['coverage']
    else:
        assert opened
        assert [item['state'] for item in result['candidates']] == ['review_pending']


def test_bound_producer_is_qualified_without_disclosing_its_rules(repo):
    evidence = setup_shared(repo)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    packet = selection(repo, evidence, binding)
    refs = [item['ref'] for item in packet['inputs']]
    assert 'beta/source.md' in refs
    assert 'beta/AGENTS.md' not in refs and 'beta/index.md' not in refs
    head = git(repo, 'rev-parse', 'HEAD')
    payload = {'context_id': 'alpha', 'approved_revision': head, 'content_revision': head,
        'entry_folder': 'alpha', 'task': {'task_id': 'cross', 'goal': 'review', 'output': 'alpha/output.md',
        'integrator': 'operator', 'max_bytes': 100000, 'evidence': evidence}}
    assert prepare_packet(repo, binding, payload)['packet'] == packet


def test_binding_is_rechecked_for_preflight_and_requirements(repo, monkeypatch):
    evidence = setup_shared(repo)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    packet = selection(repo, evidence, binding)
    base = git(repo, 'rev-parse', 'HEAD')
    branch = git(repo, 'branch', '--show-current')
    git(repo, 'checkout', '-qb', 'wiki/cross-host')
    write(repo, 'alpha/output.md', '# Proposed interpretation\n')
    git(repo, 'add', 'alpha/output.md'); git(repo, 'commit', '-qm', 'proposal')
    head = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.task-result/v1','status':'completed','task_id':'cross','context_id':'alpha',
              'packet_digest':packet['packet_digest'],'changes':[{'path':'alpha/output.md','action':'created'}],
              'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':packet['coverage']['missing']},'blockers':[]}
    payload = {'context_id':'alpha','approved_revision':base,'base':base,'head':head,'branch':'wiki/cross-host',
               'packet':packet,'result':result}
    assert coord.prepare_preflight(repo,binding,payload)['preflight']['state']=='independent_review_required'
    restricted = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    original = RepositoryReader.read
    opened = []
    def spy(reader, ref, **kwargs):
        opened.append(ref)
        return original(reader, ref, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(coord.ProtectedCoordinationError): coord.prepare_preflight(repo,restricted,payload)
    assert 'beta/source.md' not in opened
    git(repo, 'checkout', '-q', branch); git(repo, 'merge', '--no-ff', '--no-edit', 'wiki/cross-host')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    options = dict(packet=packet,result=result,output_path='alpha/output.md',proposal_head=head,temporal='current',max_age_days=30)
    opened.clear()
    with pytest.raises(RequirementError):
        requirements_from_result(repo,folder_policy(repo),trusted_binding=restricted,**options)
    assert 'beta/source.md' not in opened
    output = requirements_from_result(repo,folder_policy(repo),trusted_binding=binding,**options)
    assert any(row['target']=='beta/source.md' for row in output['information_requirements'])


def test_binding_missing_executor_blocks_all_routes_before_context_bodies(repo, monkeypatch):
    from wiki_core.context_integration import preflight, IntegrationError
    evidence = setup_shared(repo)
    valid = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    packet = selection(repo, evidence, valid)
    policy = folder_policy(repo)
    restricted = CoordinationBinding(('beta',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *args, **kwargs: pytest.fail('context body opened'))
    with pytest.raises(PolicyError, match='host binding'):
        build_packet(repo, policy, 'alpha', 'HEAD', [], 100000, task_id='t', goal='g', output='o',
                     integrator='i', entry_folder='alpha', trusted_binding=restricted)
    with pytest.raises(IntegrationError, match='host binding'):
        preflight(repo, policy, context_id='alpha', base='HEAD', head='HEAD', branch='wiki/test',
                  packet=packet, result={}, trusted_binding=restricted)
    with pytest.raises(RequirementError, match='host binding'):
        requirements_from_result(repo, policy, packet=packet, result={}, output_path='alpha/output.md',
                                 proposal_head='0'*40, temporal='current', max_age_days=30, trusted_binding=restricted)


def test_nested_cli_keeps_explicit_host_selection_through_preflight_and_requirements(repo, tmp_path):
    evidence = setup_shared(repo)
    kit = Path(__file__).resolve().parents[1]
    base = git(repo, 'rev-parse', 'HEAD')
    request = {'task_id':'cross','goal':'review','output':'alpha/output.md','integrator':'operator',
               'max_bytes':100000,'evidence':evidence}
    request_path = tmp_path/'task-selection.json'; request_path.write_text(json.dumps(request))
    script = str(kit/'scripts/wiki_context.py')
    pack = [sys.executable,script,'--approved-revision',base,'pack','alpha','--content-revision',base,
            '--request',str(request_path)]
    assert subprocess.run(pack,cwd=repo/'alpha/aux',capture_output=True).returncode != 0
    selected = subprocess.run(pack+['--trusted-context','beta'],cwd=repo/'alpha/aux',capture_output=True,text=True,check=True)
    packet=json.loads(selected.stdout)
    assert packet['entry_folder']=='alpha/aux' and any(item['ref']=='beta/source.md' for item in packet['inputs'])
    coordination = [sys.executable,str(kit/'scripts/wiki_coordination.py'),'--root',str(repo),'--context-id','alpha',
                    '--approved-revision',base,'--revision',base,'--packet-request',str(request_path),
                    '--folder','alpha/aux','--trusted-context','beta']
    coordinated = json.loads(subprocess.run(coordination,capture_output=True,text=True,check=True).stdout)
    assert coordinated['packet']==packet
    branch=git(repo,'branch','--show-current');git(repo,'checkout','-qb','wiki/cli-cross')
    write(repo,'alpha/output.md','# Proposed interpretation\n');git(repo,'add','alpha/output.md');git(repo,'commit','-qm','proposal')
    head=git(repo,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':'cross','context_id':'alpha',
            'packet_digest':packet['packet_digest'],'changes':[{'path':'alpha/output.md','action':'created'}],
            'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':packet['coverage']['missing']},'blockers':[]}
    packet_path=tmp_path/'packet.json';result_path=tmp_path/'result.json'
    packet_path.write_text(json.dumps(packet));result_path.write_text(json.dumps(result))
    flow=[sys.executable,str(kit/'scripts/wiki_context_flow.py'),'--repo',str(repo),'--approved-revision',base]
    check=['preflight','--context','alpha','--base',base,'--head',head,'--branch','wiki/cli-cross',
           '--packet',str(packet_path),'--result',str(result_path)]
    assert subprocess.run(flow+check,capture_output=True).returncode != 0
    assert json.loads(subprocess.run(flow+check+['--trusted-context','beta'],capture_output=True,text=True,check=True).stdout)['state']=='independent_review_required'
    git(repo,'checkout','-q',branch);git(repo,'merge','--no-ff','--no-edit','wiki/cli-cross');git(repo,'update-ref','refs/remotes/origin/main','HEAD')
    current=git(repo,'rev-parse','HEAD'); flow=[sys.executable,str(kit/'scripts/wiki_context_flow.py'),'--repo',str(repo),'--approved-revision',current]
    requirements=['requirements','--packet',str(packet_path),'--result',str(result_path),'--output','alpha/output.md',
                  '--proposal-head',head,'--temporal','current','--max-age-days','30']
    assert subprocess.run(flow+requirements+['--trusted-context','beta'],capture_output=True).returncode != 0
    output=json.loads(subprocess.run(flow+requirements+['--context','alpha','--trusted-context','beta'],capture_output=True,text=True,check=True).stdout)
    assert any(row['target']=='beta/source.md' for row in output['information_requirements'])


@pytest.mark.parametrize('binding_mode', ['missing', 'wrong_context', 'wrong_ref'])
def test_unbound_producer_is_refused_before_any_context_body(repo, monkeypatch, binding_mode):
    evidence = setup_shared(repo)
    policy = folder_policy(repo)
    # Earlier qualifications cannot stand in for a current host binding.
    qualify_folder_context(repo, policy, 'beta', 'beta', 'beta/index.md', 100000)
    bindings = {'missing': None,
        'wrong_context': CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml'),
        'wrong_ref': CoordinationBinding(('alpha', 'beta'), 'refs/heads/main', 'wiki.config.yaml')}
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('context body opened'))
    with pytest.raises(PolicyError, match='authorized requalification'):
        build_packet(repo, policy, 'alpha', 'HEAD', evidence, 100000,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=bindings[binding_mode])


def test_cross_owner_exact_connection_required_before_context_body(repo, monkeypatch):
    evidence = setup_shared(repo)
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['alpha']['imports'] = [item for item in config['context_access']['alpha']['imports']
                                                    if item['selector'] != 'beta/source.md']
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'revoke import'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('context body opened'))
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='connection not approved'):
        selection(repo, evidence, binding)


def test_ancestor_qualification_does_not_replace_host_allowlist(repo, monkeypatch):
    setup_shared(repo)
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    rule = {'from_context': '.', 'to_context': 'alpha', 'selector': 'root-evidence.md',
            'use': 'interpretation', 'classification': 'context', 'expires': '2099-01-01'}
    config['context_access']['.']['exports'].append(rule)
    config['context_access']['alpha']['imports'].append(copy.deepcopy(rule))
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config)); write(repo, 'root-evidence.md', '# Root evidence\n')
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'authorize root evidence'); git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    policy = folder_policy(repo)
    qualify_folder_context(repo, policy, 'alpha', 'alpha', 'alpha/index.md', 100000)
    assert '.' in policy._qualified_contexts
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('context body opened'))
    binding = CoordinationBinding(('alpha',), 'refs/remotes/origin/main', 'wiki.config.yaml')
    evidence = [{'ref': 'root-evidence.md', 'producer': '.', 'reason': 'selected',
                 'use': 'interpretation', 'classification': 'context'}]
    with pytest.raises(PolicyError, match='authorized requalification'):
        build_packet(repo, policy, 'alpha', 'HEAD', evidence, 100000,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=binding)


def test_producer_nested_git_is_not_opened(repo, monkeypatch):
    evidence = setup_shared(repo)
    git(repo / 'beta', 'init', '-q')
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('context body opened'))
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='entry folder unavailable'):
        selection(repo, evidence, binding)


def test_producer_qualification_obeys_budget_before_body(repo, monkeypatch):
    evidence = setup_shared(repo)
    monkeypatch.setattr(RepositoryReader, 'read', lambda *a, **kw: pytest.fail('context body opened'))
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='qualification exceeds byte budget'):
        build_packet(repo, folder_policy(repo), 'alpha', 'HEAD', evidence, 1,
            task_id='cross', goal='review', output='alpha/output.md', integrator='operator',
            entry_folder='alpha', trusted_binding=binding)


def test_producer_qualification_rechecks_ref_after_each_body(repo, monkeypatch):
    evidence = setup_shared(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    config = yaml.safe_load((repo / 'wiki.config.yaml').read_text())
    config['context_access']['beta']['policy']['read'] = []
    write(repo, 'wiki.config.yaml', yaml.safe_dump(config))
    git(repo, 'add', '.'); git(repo, 'commit', '-qm', 'revoke producer')
    revoked = git(repo, 'rev-parse', 'HEAD'); git(repo, 'checkout', '-q', '--detach', base)
    original = RepositoryReader.read
    opened = []
    def move(reader, ref, **kwargs):
        opened.append(ref)
        value = original(reader, ref, **kwargs)
        if ref == 'AGENTS.md': git(repo, 'update-ref', 'refs/remotes/origin/main', revoked)
        return value
    monkeypatch.setattr(RepositoryReader, 'read', move)
    binding = CoordinationBinding(('alpha', 'beta'), 'refs/remotes/origin/main', 'wiki.config.yaml')
    with pytest.raises(PolicyError, match='policy changed|not current trusted approval'):
        selection(repo, evidence, binding)
    assert opened == ['AGENTS.md']
