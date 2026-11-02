import importlib.util, json, subprocess, tempfile, sys
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from wiki_core.context_policy import load_policy
from wiki_core.context_packet import build_packet
from wiki_core.context_impact import assess_impact
from wiki_core.context_integration import preflight

spec=importlib.util.spec_from_file_location('flow_tests', BASE/'tests/test_context_flow.py')
tests=importlib.util.module_from_spec(spec); spec.loader.exec_module(tests)
outer=Path(tempfile.mkdtemp(prefix='wiki-context-pilot-'))
repo=outer/'approved'; repo.mkdir()
tests.repo.__wrapped__(repo)
def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
def approve(): git(repo,'update-ref','refs/remotes/origin/main',git(repo,'rev-parse','HEAD'))
def commit(message): git(repo,'add','.'); git(repo,'commit','-qm',message); return git(repo,'rev-parse','HEAD')
source=repo/'finance/tax/source.md'
source.write_text('---\ntitle: Synthetic source\n---\n<!-- wiki:section id=amount version=1 -->\n## Amount\nSynthetic monthly amount: 100 units.\n')
before=commit('synthetic source baseline 100'); approve()
source.write_text('---\ntitle: Synthetic source\n---\n<!-- wiki:section id=amount version=1 -->\n## Amount\nSynthetic monthly amount: 140 units.\n')
base=commit('synthetic source update 140'); approve()
policy=load_policy(repo,base)
graph=tests.graph(before)
graph['edges'].append({'type':'source_ref','source':'finance/tax/interpretation.md','target':'finance/tax/source.md','consumed_fields':['section:amount'],'consumed_revision':before,'use':'interpret','classification':'synthetic'})
proof=outer/'proof'; proof.mkdir()
results={}
for ctx, target, content in [
 ('tax','finance/tax/interpretation.md','# Fiscal interpretation\n\nThe synthetic increase warrants an independent tax classification review.\n'),
 ('costs','finance/costs/result.md','# Costs interpretation\n\nThe synthetic recurring amount increased by 40 units per month.\n')]:
    candidates=assess_impact(repo,policy,graph,before=before,after=base,destination_context=ctx)
    assert len(candidates['candidates'])==1
    item={'ref':'finance/tax/source.md','producer':'tax','reason':'same synthetic source, separate interpretation','use':'interpret','classification':'synthetic','section':'amount'}
    packet=build_packet(repo,policy,ctx,base,[item],20000,task_id='pilot-'+ctx,goal='independently interpret the synthetic source',output=target,integrator='independent reviewer')
    assert packet['inputs'][0]['text']=='Approved rule\n'
    assert '140 units' in packet['inputs'][1]['text']
    branch='wiki/'+ctx+'-pilot'; work=outer/ctx
    git(repo,'worktree','add','-qb',branch,str(work),base)
    (work/target).write_text(content)
    git(work,'add',target)
    git(work,'-c','user.name=Synthetic '+ctx,'-c','user.email='+ctx+'@example.invalid','commit','-qm','synthetic '+ctx+' interpretation')
    head=git(work,'rev-parse','HEAD')
    result={'schema_version':'wiki.task-result/v1','status':'completed','task_id':packet['task_id'],'context_id':ctx,'packet_digest':packet['packet_digest'],'changes':[{'path':target,'action':'modified'}],'read_coverage':{'observed_refs':packet['declared_read_set'],'missing':[]},'blockers':[]}
    preview=preflight(repo,policy,context_id=ctx,base=base,head=head,branch=branch,packet=packet,result=result)
    for name,obj in [('packet',packet),('result',result),('impact',candidates),('preflight',preview)]: (proof/(ctx+'-'+name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    results[ctx]={'branch':branch,'base':base,'head':head,'worktree':str(work),'target':target,'packet_digest':packet['packet_digest'],'preflight':preview['state']}
(proof/'inventory.json').write_text(json.dumps(graph,indent=2)+'\n')
summary={'repository':str(repo),'proof':str(proof),'baseline_revision':before,'approved_base':base,'branches':results,'reviews':'not performed','merges':'not performed','consumers':'two synthetic contract consumers in one Python process; no external harness run'}
(proof/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
