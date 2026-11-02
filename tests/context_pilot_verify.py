import json, subprocess, sys, tempfile
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from wiki_core.context_policy import load_policy
from wiki_core.context_requirements import requirements_from_result, assess_approved_impact
from wiki_core.context_impact import assess_impact, report_review
from wiki_core.information_relations import authored_graph, dependency_edges
from wiki_core.config import WikiConfig

if len(sys.argv)!=4: raise SystemExit('usage: python tests/context_pilot_verify.py PILOT_DIRECTORY REVIEWED_COST_HEAD PREVIEW_HEAD')
outer=Path(sys.argv[1]).resolve()
if outer.parent != Path(tempfile.gettempdir()).resolve() or not outer.name.startswith('wiki-context-pilot-'): raise SystemExit('expected dedicated synthetic pilot directory')
repo=outer/'approved';proof=outer/'proof'
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE).decode().strip()
head=sys.argv[2]; preview=sys.argv[3]; approved=git(repo,'rev-parse','refs/remotes/origin/main')
assert git(repo,'rev-parse','HEAD')==approved
git(repo,'merge-base','--is-ancestor',head,approved)
policy=load_policy(repo,approved);packet=json.loads((proof/'costs-packet-final.json').read_text());result=json.loads((proof/'costs-result-final.json').read_text())
requirements=requirements_from_result(repo,policy,packet=packet,result=result,output_path='finance/costs/result.md',proposal_head=head,temporal='current',max_age_days=30)
assert requirements['self_input_read'] and len(requirements['information_requirements'])==1
source_revision=packet['content_revision']; before=assess_approved_impact(repo,policy,consumers=['finance/costs/result.md'],before=source_revision,after=approved,destination_context='costs')
assert before['candidates']==[]
original=json.loads((proof/'costs-impact.json').read_text())['candidates'][0]
review=report_review(repo,policy,original,disposition='updated',reason='Independent interpretation reviewed and incorporated in synthetic repository',evidence_revision=approved)
assert review['verification']=='reported_not_verified' and review['next_impact_allowed']
# The preview is a separately prepared synthetic source commit, never merged here.
graph=authored_graph(repo,WikiConfig(paths={'memory_root':'finance'})); edges,_=dependency_edges(graph)
canonical=[e for e in edges if e.get('dependent')=='finance/costs/result.md' and e.get('field')=='information_requirements']
assert len(canonical)==1 and canonical[0]['consumed_revision']==source_revision
impact=assess_impact(repo,policy,graph,before=source_revision,after=preview,destination_context='costs')
matching=[c for c in impact['candidates'] if c['target']=='finance/costs/result.md' and c['selector']=='section:amount' and c['state']=='review_pending']
assert matching
safe_impact=assess_approved_impact(repo,policy,consumers=['finance/costs/result.md'],before=source_revision,after=preview,destination_context='costs')
assert len(safe_impact['candidates'])==1
out={'approved_merge':approved,'requirements':requirements,'current_impact':before,'reported_review':review,'preview':{'source_revision':preview,'status':'unapproved_synthetic_preview','canonical_inventory_edge':canonical[0],'matching_candidates':matching,'authorized_page_projection':safe_impact},'fact_freshness':'not_assessed_no_external_observation'}
print(json.dumps(out,ensure_ascii=False,indent=2,default=str))
