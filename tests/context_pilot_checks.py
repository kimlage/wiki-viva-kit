"""Add local-only negative and explicitly simulated grant evidence to a prepared pilot."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from wiki_core.context_policy import ContextPolicy, load_policy
from wiki_core.context_packet import build_packet, connection_proposal
from wiki_core.context_impact import assess_impact
from wiki_core.context_integration import preflight, IntegrationError

if len(sys.argv)!=2: raise SystemExit('usage: python tests/context_pilot_checks.py PILOT_DIRECTORY')
outer=Path(sys.argv[1]).resolve()
if outer.parent != Path(tempfile.gettempdir()).resolve() or not outer.name.startswith('wiki-context-pilot-'):
    raise SystemExit('pilot directory must be a dedicated temporary directory created by the setup script')
repo=outer/'approved'; proof=outer/'proof'
summary=json.loads((proof/'summary.json').read_text()); base=summary['approved_base']; before=summary['baseline_revision']
policy=load_policy(repo,base); graph=json.loads((proof/'inventory.json').read_text())
grant={'from_context':'tax','to_context':'finance','selector':'finance/tax/source.md','section':'amount','use':'interpret','classification':'synthetic','expires':'2099-01-01'}
assert policy.connection('tax','finance',grant['selector'],'interpret','synthetic',section='amount')=='pending'
proposal=connection_proposal('tax','finance',grant['selector'],'interpret','synthetic',grant['expires'],section='amount')
contexts=copy.deepcopy(list(policy.contexts.values()))
for c in contexts:
    if c['id']=='tax': c['exports'].append(copy.deepcopy(grant))
    if c['id']=='finance': c['imports'].append(copy.deepcopy(grant))
simulation=ContextPolicy({'schema_version':'wiki.context/v1','contexts':contexts},base)
assert simulation.connection('tax','finance',grant['selector'],'interpret','synthetic',section='amount')=='approved'
assert simulation._binding is None and policy.connection('tax','finance',grant['selector'],'interpret','synthetic',section='amount')=='pending'
candidate=assess_impact(repo,policy,graph,before=before,after=base,destination_context='costs')['candidates'][0]
cycle=assess_impact(repo,policy,graph,before=before,after=base,destination_context='costs',trace=[candidate['event_id']])['candidates'][0]['state']
assert cycle=='blocked_cycle_limit'
def git(root,*args): return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
parent=outer/'parent-negative'; git(repo,'worktree','add','-qb','wiki/parent-negative',str(parent),base)
packet=build_packet(repo,policy,'finance',base,[],20000,task_id='parent-negative',goal='negative authorization check',output='test report',integrator='independent reviewer')
(parent/'finance/tax/interpretation.md').write_text('Unauthorized parent modification\n'); git(parent,'add','.'); git(parent,'commit','-qm','synthetic outside scope'); head=git(parent,'rev-parse','HEAD')
result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':packet['task_id'],'context_id':'finance','packet_digest':packet['packet_digest'],'changes':[{'path':'finance/tax/interpretation.md','action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
try: preflight(repo,policy,context_id='finance',base=base,head=head,branch='wiki/parent-negative',packet=packet,result=result)
except IntegrationError as exc:
    assert str(exc)=='write outside context'; out_of_scope='denied'
else: raise AssertionError('out-of-scope change was not denied')
# Use a separate disposable repository so the pending pilot's approval ref never moves.
spec=importlib.util.spec_from_file_location('flow_tests',BASE/'tests/test_context_flow.py'); tests=importlib.util.module_from_spec(spec); spec.loader.exec_module(tests)
revrepo=outer/'revocation-synthetic'; revrepo.mkdir(); tests.repo.__wrapped__(revrepo)
old=git(revrepo,'rev-parse','HEAD'); path=revrepo/'finance/costs/context.yaml'; data=yaml.safe_load(path.read_text()); data['imports']=[]; path.write_text(yaml.safe_dump(data)); git(revrepo,'add','.'); git(revrepo,'commit','-qm','synthetic revoke'); git(revrepo,'update-ref','refs/remotes/origin/main','HEAD'); current=git(revrepo,'rev-parse','HEAD')
redacted=assess_impact(revrepo,load_policy(revrepo,current),tests.graph(old),before=old,after=current,destination_context='costs')
assert redacted['candidates']==[] and 'finance/tax/source.md' not in json.dumps(redacted)
proof_data={'simulation_only':True,'connection_proposal':proposal,'simulated_bilateral_decision':'approved_in_unbound_memory_only','approved_synthetic_policy_connection_after_simulation':'pending','cycle':cycle,'parent_write':out_of_scope,'revoked_connection':'blocked_and_redacted_in_disposable_repository'}
(proof/'negative-simulation.json').write_text(json.dumps(proof_data,indent=2)+'\n')
print(json.dumps(proof_data,indent=2))
