"""Historical v1 requalification fails closed until scoped authority exists."""
from copy import deepcopy

import pytest
import yaml

from tests.test_folder_mandatory_v2 import equivalent_repo, git, put, commit
from wiki_core.context_packet import build_packet
from wiki_core.context_policy import load_policy
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_requalification_v2 import RequalificationError, requalify_explicit_v1_requirement
from wiki_core.repository_reader import RepositoryReader


def prepare(repo, output='a/result.md', packet_output=None):
    put(repo, 'a/source.md', '---\nstatus: recorded\n---\nSynthetic source\n'); commit(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    evidence = [{'ref':'a/source.md','producer':'area','reason':'synthetic evidence','use':'interpret',
                 'classification':'synthetic','field':'status'}]
    old = build_packet(repo, load_policy(repo, 'HEAD'), 'area', base, evidence, 50000,
                       task_id='synthetic-task', goal='review', output=packet_output or output, integrator='independent')
    requirement = {'target':'a/source.md','fields':['field:status'],'temporal':'current','max_age_days':30,
                   'consumed_revision':base,'use':'interpret','classification':'synthetic'}
    body = '---\n' + yaml.safe_dump({'page_id':'synthetic-result','page_type':'claim',
                                      'information_requirements':[requirement]}) + '---\nInterpretation\n'
    git(repo, 'checkout', '-qb', 'wiki/requalify-fixture'); put(repo, output, body)
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'proposal')
    proposal = git(repo, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.task-result/v1','status':'completed','task_id':old['task_id'],
              'context_id':old['context_id'],'packet_digest':old['packet_digest'],
              'changes':[{'path':output,'action':'created'}],
              'read_coverage':{'observed_refs':old['declared_read_set'],'missing':[]},'blockers':[]}
    git(repo, 'checkout', '-q', '-'); git(repo, 'merge', '--ff-only', 'wiki/requalify-fixture')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return base, proposal, old, result, body


def call(repo, packet, result, proposal, *, folder='a', index='a/index.md', consumer='a/result.md'):
    return requalify_explicit_v1_requirement(repo, load_folder_policy_v2(repo, 'HEAD'),
                 folder=folder, index_path=index, consumer=consumer, requirement_index=0,
                 packet=packet, result=result, proposal_head=proposal)


def test_refuses_global_legacy_loader_without_opening_other_owner(equivalent_repo, monkeypatch):
    base, proposal, packet, result, body = prepare(equivalent_repo)
    import wiki_core.context_policy as legacy
    def denied(*args, **kwargs):
        raise AssertionError('legacy global policy loader was invoked')
    monkeypatch.setattr(legacy, '_policy_at', denied)
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if self.revision == base and ref == 'a/source.md':
            raise AssertionError('historical source body was read')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(RequalificationError, match='historical v1 policy access unavailable; normative equivalence not assessed'):
        call(equivalent_repo, packet, result, proposal)
    assert (equivalent_repo/'a/result.md').read_text()==body


def test_current_owner_move_does_not_create_equivalence(equivalent_repo, monkeypatch):
    base, proposal, packet, result, _ = prepare(equivalent_repo, output='a/new/result.md')
    put(equivalent_repo, 'a/new/AGENTS.md', 'New context instruction\n')
    put(equivalent_repo, 'a/new/index.md', 'New context index\n')
    controls = equivalent_repo/'wiki-context-controls.yaml'; data=yaml.safe_load(controls.read_text())
    data['controls']['a/new']={'policy':{'read':['self'],'write':['self']},'imports':[],'exports':[]}
    controls.write_text(yaml.safe_dump(data)); commit(equivalent_repo)
    import wiki_core.context_policy as legacy
    monkeypatch.setattr(legacy, '_policy_at', lambda *a, **k: pytest.fail('global legacy policy opened'))
    with pytest.raises(RequalificationError, match='historical v1 policy access unavailable'):
        call(equivalent_repo, packet, result, proposal, folder='a/new', index='a/new/index.md', consumer='a/new/result.md')
    assert packet['context_id'] == 'area' and packet['policy_revision'] == base


def test_changed_normative_body_never_returns_byte_equivalence(equivalent_repo, monkeypatch):
    _, proposal, packet, result, _ = prepare(equivalent_repo)
    put(equivalent_repo, 'docs/contract.md', 'Changed normative body\n'); commit(equivalent_repo)
    original = RepositoryReader.read
    def spy(self, ref, *args, **kwargs):
        if ref == 'docs/contract.md': raise AssertionError('normative body read without qualified replay')
        return original(self, ref, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', spy)
    with pytest.raises(RequalificationError, match='normative equivalence not assessed'):
        call(equivalent_repo, packet, result, proposal)


def test_dynamic_query_gets_distinct_blocker(equivalent_repo):
    _, proposal, packet, result, body = prepare(equivalent_repo)
    _, fm, rest = body.split('---\n',2)
    data = yaml.safe_load(fm); data['information_requirements'][0]['query'] = {'scope':'a'}
    put(equivalent_repo, 'a/result.md', '---\n'+yaml.safe_dump(data)+'---\n'+rest); commit(equivalent_repo)
    with pytest.raises(RequalificationError, match='dynamic v1 query requires independent v2 requalification'):
        call(equivalent_repo, packet, result, proposal)


def test_no_self_reported_global_scope_parameter_is_accepted(equivalent_repo):
    _, proposal, packet, result, _ = prepare(equivalent_repo)
    p=load_folder_policy_v2(equivalent_repo,'HEAD')
    with pytest.raises(TypeError):
        requalify_explicit_v1_requirement(equivalent_repo,p,folder='a',index_path='a/index.md',
            consumer='a/result.md',requirement_index=0,packet=packet,result=result,proposal_head=proposal,
            global_scope_verified=True)


def test_requalification_cli_reports_blocker_without_disclosure(equivalent_repo, tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    _, proposal, packet, result, body = prepare(equivalent_repo)
    packet_path = tmp_path.parent/(tmp_path.name+'-legacy-packet.json')
    result_path = tmp_path.parent/(tmp_path.name+'-legacy-result.json')
    packet_path.write_text(json.dumps(packet)); result_path.write_text(json.dumps(result))
    tool = Path(__file__).resolve().parents[1]/'scripts/wiki_folder_requalify_v1.py'
    proc = subprocess.run([sys.executable,str(tool),'--repo',str(equivalent_repo),'--approved-revision','HEAD',
                           '--folder','a','--index','a/index.md','--consumer','a/result.md','--requirement-index','0',
                           '--packet',str(packet_path),'--result',str(result_path),'--proposal-head',proposal],
                          capture_output=True,text=True)
    assert proc.returncode != 0 and not proc.stdout
    assert 'historical_policy_authority_unavailable' in proc.stderr
    assert (equivalent_repo/'a/result.md').read_text()==body
