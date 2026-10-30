"""Readiness of explicit factual requirements, separate from incorporation.

No source fetch, permission grant, editorial-date fallback or automatic repair.
The caller must bind these pages/evidence to its authorized immutable readset
and recheck immediately before the actual effect.
"""
from __future__ import annotations

import datetime as dt
from wiki_core.information_relations import dependency_edges
from wiki_core.temporal import parse_temporal_value, TemporalEventError


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
        if not values or path not in graph['documents']:
            reasons.append('information_target_missing')
        elif not requirement:
            reasons.append('information_use_scope_unspecified')
        else:
            if requirement['temporal'] == 'current' and graph.get('verification_coverage', {}).get(path) is not True:
                reasons.append('information_changed_since_verification')
            fields = requirement['fields']
            if any(f != 'body' and f not in values for f in fields):
                reasons.append('information_field_missing')
            # A claim page is the existing atomic fact surface. A source
            # catalogue timestamp cannot verify arbitrary fields of its streams.
            if values.get('page_type') != 'claim':
                reasons.append('information_requires_scoped_claim')
            if values.get('confidence') != 'confirmed' or values.get('temporal_conflicts'):
                reasons.append('information_unconfirmed_or_conflicting')
            evidence = values.get('evidence_refs', [])
            if (not isinstance(evidence, list) or not evidence
                    or any(not isinstance(p, str) or p not in graph['documents'] for p in evidence)):
                reasons.append('information_evidence_missing')
                evidence = []
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
        rows.append({'target': path, 'fields': requirement['fields'] if requirement else ['*'],
                     'temporal': requirement['temporal'] if requirement else 'current',
                     'verified_at': verified.value if verified else None,
                     'verification_precision': verified.precision if verified else None,
                     'valid_until': deadline.isoformat() if deadline else None,
                     'evidence_refs': evidence, 'blockers': sorted(set(reasons)),
                     'ready': not reasons})
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
        return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL,text=True)
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
            selectors = set(fields) | {'evidence_refs','confidence','valid_from','valid_to','source_refs'}
            return {field: (True, body) if field == 'body' else (field in values, values.get(field))
                    for field in sorted(selectors)}
        # Compare the complete selected meaning, including absent/deleted
        # fields and deleted prose, at the actual verification declaration.
        if projection(git('show',verified_commit+':'+path)) != projection(raw):
            return False
        for ref in evidence:
            current=(root/ref).read_text()
            if git('show','HEAD:'+ref)!=current or git('show',verified_commit+':'+ref)!=current:
                return False
        return True
    except (OSError,subprocess.SubprocessError,UnicodeError):
        return False
