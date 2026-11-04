"""Readiness of explicit factual requirements, separate from incorporation.

No source fetch, permission grant, editorial-date fallback or automatic repair.
The caller must bind these pages/evidence to its authorized immutable readset
and recheck immediately before the actual effect.
"""
from __future__ import annotations

import datetime as dt
from wiki_core.information_relations import dependency_edges, semantic_equal
from wiki_core.temporal import parse_temporal_value, TemporalEventError
from wiki_core.git_env import local_git_environment, local_git_executable


def factual_unit_role(values: dict) -> str:
    """Classify loaded metadata, without establishing truth or read authority.

    Provenance-bearing undeclared pages are not independent RAW observations.
    An invalid explicit declaration never falls back to legacy claim behavior.
    """
    if 'information_role' in values:
        marker = values['information_role']
        page_type = values.get('page_type')
        if (not isinstance(marker, str) or marker != 'factual_unit'
                or not isinstance(page_type, str) or not page_type.strip()):
            return 'invalid'
        return 'factual_unit'
    if values.get('page_type') == 'claim':
        return 'factual_unit'
    if 'evidence_refs' in values and values['evidence_refs'] != []:
        return 'undeclared'
    return 'observation'


def _evidence_issues(graph: dict, claim: str) -> set[str]:
    """A closed claim cycle is not an independent observation.

    Only inspect the caller's already authorized graph. Missing provenance is
    an impediment, never permission to fetch another source implicitly.
    """
    issues=set();visited=set();has_observation=False
    pending=[claim]
    while pending:
        path=pending.pop()
        if path in visited:continue
        visited.add(path)
        if path not in graph['documents']:
            issues.add('information_evidence_missing');continue
        values=graph['nodes'].get(path,{})
        role = factual_unit_role(values)
        if role == 'observation':
            has_observation=True;continue
        if role in {'invalid', 'undeclared'}:
            issues.add('information_requires_scoped_claim')
        refs=values.get('evidence_refs',[])
        if not isinstance(refs,list) or not refs or any(not isinstance(ref,str) for ref in refs):
            issues.add('information_evidence_missing');continue
        if path in refs:issues.add('information_evidence_self_reference')
        pending.extend(refs)
    if not has_observation:issues.add('information_evidence_closed_claim_cycle')
    return issues


def assess_information_use(graph: dict, consumer: str, *, now: dt.datetime) -> dict:
    if now.tzinfo is None:
        raise ValueError('information use requires an explicit timezone')
    requirements, _ = dependency_edges(graph)
    rows = []
    for edge in requirements:
        if edge['dependent'] != consumer or edge['type'] != 'operational_prerequisite':
            continue
        path = edge['prerequisite']; values = graph['nodes'].get(path)
        requirement = edge.get('requirement')
        reasons = []
        evidence = []
        verified = None
        deadline = None
        if requirement and requirement.get('source_kind') == 'mandatory':
            # A tracked edge is a declaration, not proof of authority or of a
            # factual claim. Only an explicitly bound check can qualify it.
            status=graph.get('normative_coverage',{}).get(normative_key(consumer,requirement))
            if status != 'equivalent':
                reasons.append('information_normative_changed' if status == 'changed' else 'information_normative_authority_required')
        elif not values or path not in graph['documents']:
            reasons.append('information_target_missing')
        elif requirement and 'query' in requirement:
            # This graph has no current context authority to enumerate a set.
            # A hub timestamp cannot establish member equivalence or facts.
            reasons.append('information_query_requires_authorized_revalidation')
        elif not requirement:
            reasons.append('information_use_scope_unspecified')
        else:
            if requirement['temporal'] == 'current' and graph.get('verification_coverage', {}).get(coverage_key(path, requirement['fields']),
                    graph.get('verification_coverage', {}).get(path)) is not True:
                reasons.append('information_changed_since_verification')
            fields = requirement['fields']
            from wiki_core.content_sections import parse_sections, SectionError
            try:
                sections = parse_sections(graph['documents'][path]) if any(f.startswith('section:') for f in fields) else {}
                if any((f.startswith('section:') and f[8:] not in sections) or (not f.startswith('section:') and f not in {'body','*'} and f.removeprefix('field:') not in values) for f in fields):
                    reasons.append('information_field_missing')
            except SectionError:
                reasons.append('information_field_missing')
            # Type/declaration establishes eligibility only, never truth.
            if factual_unit_role(values) != 'factual_unit':
                reasons.append('information_requires_scoped_claim')
            if values.get('confidence') != 'confirmed' or values.get('temporal_conflicts'):
                reasons.append('information_unconfirmed_or_conflicting')
            evidence = values.get('evidence_refs', [])
            if (not isinstance(evidence, list) or not evidence
                    or any(not isinstance(p, str) or p not in graph['documents'] for p in evidence)):
                reasons.append('information_evidence_missing')
                evidence = []
            else:
                reasons.extend(_evidence_issues(graph,path))
            try:
                verified = parse_temporal_value(str(values.get('verified_at') or ''))
                # Keep precision: month/year cannot establish day-scale freshness.
                if verified.precision not in {'day', 'instant'}:
                    reasons.append('information_verification_precision_insufficient')
                elif verified.lower > now:
                    reasons.append('information_verification_future')
                elif requirement['temporal'] == 'current':
                    if verified.precision == 'day':
                        age = (now.date() - dt.date.fromisoformat(verified.value)).days
                    else:
                        age = (now - verified.lower).total_seconds() / 86400
                    deadline = (verified.upper if verified.precision == 'day' else verified.lower) + dt.timedelta(days=requirement['max_age_days'])
                    if age > requirement['max_age_days']:
                        reasons.append('information_verification_expired')
                for field in ('valid_from', 'valid_to'):
                    if values.get(field) is not None:
                        validity = parse_temporal_value(str(values[field]))
                        if requirement['temporal'] == 'current':
                            if field == 'valid_from' and validity.lower > now:
                                reasons.append('information_not_yet_valid')
                            if field == 'valid_to':
                                deadline = min(deadline, validity.upper) if deadline else validity.upper
                            if field == 'valid_to' and validity.upper < now:
                                reasons.append('information_no_longer_valid')
            except TemporalEventError:
                reasons.append('information_temporal_evidence_invalid')
        row={'target': path, 'fields': requirement['fields'] if requirement else ['*'],
                     'temporal': requirement['temporal'] if requirement else 'current',
                     'verified_at': verified.value if verified else None,
                     'verification_precision': verified.precision if verified else None,
                     'valid_until': deadline.isoformat() if deadline else None,
                     'evidence_refs': evidence, 'blockers': sorted(set(reasons)),
                     'ready': not reasons}
        if requirement and requirement.get('source_kind')=='mandatory':
            row.update(source_kind='mandatory',normative_status=status or 'authority_required',
                       policy_revision=graph.get('normative_policy_revision') if status=='equivalent' else None,
                       review='not_assessed',fact_freshness='not_assessed')
        rows.append(row)
    return {'schema_version': 'wiki_information_use.v1', 'consumer': consumer,
            'requirements': rows, 'ready': not graph['errors'] and all(row['ready'] for row in rows),
            'relation_errors': graph['errors']}


def verification_covers_content(root, path: str, fields: list[str], evidence: list[str]) -> bool:
    """Reject factual edits made after the retained verification declaration.

    Git ancestry is only a revision/coverage check, never proof of truth or a
    live external read. It prevents a recent retained date from certifying new
    content. Unknown provenance stays unusable for current factual execution.
    """
    import re
    import subprocess
    def git(*args):
        return subprocess.check_output([local_git_executable(), '--no-lazy-fetch',*args],cwd=root,stderr=subprocess.DEVNULL,text=True,env=local_git_environment())
    try:
        raw=(root/path).read_text()
        if git('show','HEAD:'+path)!=raw:
            return False
        lines=raw.splitlines(); delimiters=[i for i,line in enumerate(lines) if line=='---']
        if len(delimiters)<2 or delimiters[0]!=0:
            return False
        end=delimiters[1]
        verification=[i for i in range(1,end) if re.match(r'^verified_at:',lines[i])]
        if len(verification)!=1:
            return False
        origins=[];commit=None
        for line in git('blame','--line-porcelain','HEAD','--',path).splitlines():
            match=re.fullmatch(r'([0-9a-f]{40,64}) \d+ \d+(?: \d+)?',line)
            if match:commit=match.group(1)
            elif line.startswith('\t'):origins.append(commit)
        if len(origins)!=len(lines):
            return False
        verified_commit=origins[verification[0]]
        from wiki_core.frontmatter import parse_frontmatter
        def projection(text):
            values, body = parse_frontmatter(text)
            selectors = {('body' if f.startswith('section:') else f.removeprefix('field:')) for f in fields}
            if '*' in selectors: return {'all': (values, body)}
            selectors |= {'page_type','information_role','evidence_refs','confidence','valid_from','valid_to','source_refs'}
            return {field: (True, body) if field == 'body' else (field in values, values.get(field))
                    for field in sorted(selectors)}
        # Compare the complete selected meaning, including absent/deleted
        # fields and deleted prose, at the actual verification declaration.
        if not semantic_equal(projection(git('show',verified_commit+':'+path)),projection(raw)):
            return False
        for ref in evidence:
            current=(root/ref).read_text()
            if git('show','HEAD:'+ref)!=current or git('show',verified_commit+':'+ref)!=current:
                return False
        return True
    except (OSError,subprocess.SubprocessError,UnicodeError):
        return False


def bind_verification_coverage(root, graph: dict) -> dict:
    """Bind declared scopes to current authorized Git inputs, without a fetch."""
    import json
    nodes={path:dict(values) for path,values in graph['nodes'].items()}
    by_id={}
    for path,values in nodes.items():
        page_id=values.get('page_id')
        if isinstance(page_id,str):by_id.setdefault(page_id,[]).append(path)
    for values in nodes.values():
        refs=values.get('evidence_refs')
        if isinstance(refs,list):
            values['evidence_refs']=[ref if not isinstance(ref,str) or ref in graph['documents'] else
                by_id[ref][0] if isinstance(ref,str) and len(by_id.get(ref,[]))==1 else ref for ref in refs]
    coverage={}
    dependencies,_=dependency_edges(graph)
    for edge in dependencies:
        requirement=edge.get('requirement')
        if edge['type']!='operational_prerequisite' or not requirement or requirement['temporal']!='current':continue
        if requirement.get('source_kind')=='mandatory': continue
        path=edge['prerequisite'];refs=nodes.get(path,{}).get('evidence_refs',[])
        key=coverage_key(path,requirement['fields'])
        pending=list(refs) if isinstance(refs,list) else [];expanded=set();valid=isinstance(refs,list)
        while pending:
            ref=pending.pop()
            if not isinstance(ref,str) or ref not in graph['documents']:
                valid=False;continue
            if ref==path or ref in expanded:continue
            expanded.add(ref)
            role = factual_unit_role(nodes.get(ref, {}))
            if role in {'invalid', 'undeclared'}:valid=False
            if role != 'observation':
                further=nodes[ref].get('evidence_refs',[])
                if not isinstance(further,list):valid=False
                else:pending.extend(further)
        # Only authorized, loaded provenance may enter a filesystem/Git read.
        # A changed leaf cannot inherit the verification of its unchanged claim.
        coverage[key]=(valid and verification_covers_content(root,path,requirement['fields'],sorted(expanded)))
    return {**graph,'nodes':nodes,'verification_coverage':coverage}


def normative_key(consumer, requirement):
    import json
    return json.dumps([consumer,requirement],ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _normative_metadata_unchanged(root, source, approved, head):
    """Compare tree/index/stat metadata without opening a proposed rule body."""
    import re
    import os
    import stat
    import subprocess
    from pathlib import Path
    from wiki_core.context_policy import safe_path
    source=safe_path(source)
    def git(*args):
        return subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'--literal-pathspecs',*args],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=local_git_environment())
    def tree(revision):
        out=git('ls-tree','-z',revision,'--',source)
        if out.returncode: return None
        parts=out.stdout.split(b'\0')
        if len(parts)!=2 or not parts[0].startswith((b'100644 blob ',b'100755 blob ')): return None
        meta,sep,name=parts[0].partition(b'\t')
        return meta if sep and name==source.encode('utf-8') else None
    original=tree(approved); proposed=tree(head)
    if original is None or proposed is None: return None
    if original!=proposed: return 'changed'
    # Python's Windows ctime may describe creation, not change. It cannot
    # conservatively detect an altered working file without opening its body.
    if os.name=='nt': return None
    index=git('ls-files','--stage','-z','--',source)
    if index.returncode: return None
    parts=index.stdout.split(b'\0')
    if len(parts)!=2: return None
    meta,sep,name=parts[0].partition(b'\t')
    tree_mode,_,tree_oid=original.split(b' ',2)
    if not sep or name!=source.encode('utf-8') or meta!=tree_mode+b' '+tree_oid+b' 0': return 'changed'
    debug=git('ls-files','--debug','-z','--',source)
    if debug.returncode: return None
    name,sep,details=debug.stdout.partition(b'\0')
    if not sep or name!=source.encode('utf-8'): return None
    match=re.search(rb'ctime: (\d+):(\d+)\n\s*mtime: (\d+):(\d+)\n.*?size: (\d+)\s+flags: ([0-9a-fA-F]+)',details,re.S)
    if not match or match.group(6)!=b'0': return None
    parent=Path(root)
    for part in source.split('/')[:-1]:
        parent=parent/part
        if not stat.S_ISDIR(parent.lstat().st_mode): return None
    st=(Path(root)/source).lstat()
    if not stat.S_ISREG(st.st_mode): return 'changed'
    csec,cns,msec,mns,size=map(int,match.groups()[:5])
    if ((st.st_ctime_ns//1_000_000_000,st.st_ctime_ns%1_000_000_000)!=(csec,cns)
            or (st.st_mtime_ns//1_000_000_000,st.st_mtime_ns%1_000_000_000)!=(msec,mns)
            or st.st_size!=size or bool(st.st_mode & 0o111)!=(tree_mode==b'100755')):
        return 'changed'
    return 'equivalent'


def bind_normative_coverage(root, graph, policy, context_id, *, head):
    """Revalidate explicit normative consumption in one approved context.

    The caller remains responsible for the global graph's access boundary.
    Unbound/other-owner edges have no proof. Proposed changes to a rule or a
    new requirement do not gain approval from this check.
    """
    if getattr(policy, 'format_version', None):
        raise ValueError('v2 normative coverage is unavailable; v1 receipts require explicit migration')
    import subprocess
    import re
    from pathlib import Path
    from wiki_core.context_normative import normative_history
    from wiki_core.context_policy import PolicyError, is_context_instruction
    from wiki_core.detectors import scan_text
    from wiki_core.information_relations import information_requirements
    from wiki_core.repository_reader import RepositoryReader
    policy=policy.fresh()
    if Path(root).resolve()!=Path(policy._binding[0]) or not isinstance(head,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',head):
        raise ValueError('invalid normative binding')
    ancestor=subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'merge-base','--is-ancestor',policy.policy_revision,head],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=local_git_environment())
    if ancestor.returncode: raise ValueError('invalid normative binding')
    # A native instruction boundary can change independently of v1 manifests.
    # Until that boundary is migrated and requalified, do not certify old
    # normative consumption from the proposal's new tree.
    diff=subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'diff','--no-ext-diff','--no-textconv','--no-renames','--name-only','-z',policy.policy_revision,head,'--'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=local_git_environment())
    if diff.returncode: raise ValueError('normative instruction comparison unavailable')
    try:
        changed=[raw.decode('utf-8') for raw in diff.stdout.split(b'\0') if raw]
    except UnicodeError as exc:
        raise ValueError('normative instruction comparison unavailable') from exc
    if any(is_context_instruction(path) for path in changed):
        return {**graph,'normative_coverage':{},'normative_policy_revision':policy.policy_revision}
    reader=RepositoryReader(root,policy.policy_revision); coverage={}
    dependencies,_=dependency_edges(graph)
    for edge in dependencies:
        req=edge.get('requirement',{})
        if req.get('source_kind')!='mandatory': continue
        target=edge['dependent']; source=edge['prerequisite']; key=normative_key(target,req)
        try:
            if policy.owner_of(target)!=context_id or not policy.permits(context_id,'read',target): continue
            if req.get('target')!=source or req.get('fields')!=['*'] or req.get('temporal')!='current' or req.get('use')!='normative': continue
            if not normative_history(policy,context_id,source,req['consumed_revision']): continue
            metadata=_normative_metadata_unchanged(root,source,policy.policy_revision,head)
            if metadata=='changed': coverage[key]='changed'; continue
            if metadata!='equivalent': continue
            approved=reader.read(target)
            declared=information_requirements(approved['frontmatter'],lambda ref:[ref])
            if req not in declared: continue
            old=RepositoryReader(root,req['consumed_revision']).read(source)
            now=reader.read(source)
            if any(x.category=='secret' for x in scan_text(old['text']+'\n'+now['text'])): continue
            metadata=_normative_metadata_unchanged(root,source,policy.policy_revision,head)
            if metadata=='changed': coverage[key]='changed'; continue
            if metadata!='equivalent': continue
            coverage[key]='equivalent' if old['content_digest']==now['content_digest'] else 'changed'
        except (PolicyError,ValueError,KeyError,TypeError,OSError):
            continue
    policy.fresh()
    return {**graph,'normative_coverage':coverage,'normative_policy_revision':policy.policy_revision}


def coverage_key(path: str, fields: list[str]) -> str:
    import json
    return json.dumps([path,sorted(fields)],separators=(',',':'))
