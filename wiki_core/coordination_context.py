"""Explicit protected coordination; caller binding is trusted host configuration."""
from __future__ import annotations
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from wiki_core.context_policy import load_policy, safe_path, PolicyError, revision
from wiki_core.context_packet import build_packet
from wiki_core.context_integration import preflight

class ProtectedCoordinationError(ValueError):
    def __init__(self, code='coordination_input_unavailable', status='pending'):
        self.code=code; self.status=status
        super().__init__(code)

@dataclass(frozen=True)
class CoordinationBinding:
    contexts: tuple[str,...]
    trusted_ref: str
    manifest: str='context.yaml'

    def __post_init__(self):
        if not isinstance(self.contexts,tuple) or not self.contexts or len(self.contexts)>64 or len(set(self.contexts))!=len(self.contexts) or any(not isinstance(c,str) or not re.fullmatch(r'[a-z0-9][a-z0-9/_-]*',c) for c in self.contexts): raise ValueError('invalid coordination host binding')
        if not isinstance(self.trusted_ref,str) or not re.fullmatch(r'refs/(?:heads|remotes)/[A-Za-z0-9][A-Za-z0-9/._-]*',self.trusted_ref) or '..' in self.trusted_ref: raise ValueError('invalid coordination trusted reference')
        if self.manifest!='context.yaml': raise ValueError('invalid coordination manifest')

    @classmethod
    def from_environment(cls, env: Mapping[str,str] | None=None):
        env=os.environ if env is None else env
        if env.get('WIKI_COORDINATION_MANIFEST','').strip(): raise ValueError('coordination manifest override is unsupported')
        contexts=env.get('WIKI_COORDINATION_ALLOWED_CONTEXTS','').strip()
        trusted=env.get('WIKI_COORDINATION_TRUSTED_REF','').strip()
        if not contexts and not trusted: return None
        if not contexts: raise ValueError('incomplete coordination host binding')
        return cls(tuple(c.strip() for c in contexts.split(',')),trusted or 'refs/remotes/origin/main')


def capability(root: Path, binding: CoordinationBinding | None) -> dict:
    if binding is None: return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':False,'reason':'not_available_or_not_authorized'}
    try:
        sha=revision(root,binding.trusted_ref)
        policy=load_policy(root,sha,binding.manifest,trusted_ref=binding.trusted_ref)
        contexts=[c for c in binding.contexts if c in policy.contexts]
    except (ValueError,OSError): contexts=[]
    if not contexts: return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':False,'reason':'not_available_or_not_authorized'}
    return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':True,'contexts':contexts,'policy_revision':sha}


def _policy(root, binding, context_id, approved_revision):
    if binding is None: raise ProtectedCoordinationError('coordination_not_available')
    if not isinstance(context_id,str) or context_id not in binding.contexts: raise ProtectedCoordinationError('coordination_not_authorized','denied')
    if not isinstance(approved_revision,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',approved_revision): raise ProtectedCoordinationError('coordination_invalid_request')
    try: policy=load_policy(root,approved_revision,binding.manifest,trusted_ref=binding.trusted_ref)
    except (PolicyError,ValueError,OSError) as exc: raise ProtectedCoordinationError('coordination_policy_unavailable') from exc
    if context_id not in policy.contexts: raise ProtectedCoordinationError('coordination_not_authorized','denied')
    return policy


def prepare_packet(root, binding, payload):
    if not isinstance(payload,dict) or set(payload)!={'context_id','approved_revision','content_revision','task'}: raise ProtectedCoordinationError('coordination_invalid_request')
    policy=_policy(root,binding,payload['context_id'],payload['approved_revision'])
    content=payload['content_revision']; task=payload['task']
    if not isinstance(content,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',content): raise ProtectedCoordinationError('coordination_invalid_request')
    # Approved-mode history is confined to ancestors of the trusted tip.
    if subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',content,policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: raise ProtectedCoordinationError('coordination_content_not_approved')
    required={'task_id','goal','output','integrator','max_bytes','evidence'}
    if not isinstance(task,dict) or not required<=set(task) or set(task)-(required|{'omissions','queries'}): raise ProtectedCoordinationError('coordination_invalid_request')
    if type(task['max_bytes']) is not int or not 0<=task['max_bytes']<=1_000_000 or not isinstance(task['evidence'],list) or len(task['evidence'])>128: raise ProtectedCoordinationError('coordination_invalid_request')
    evidence=[]; expectations=[]
    for e in task['evidence']:
        if not isinstance(e,dict): raise ProtectedCoordinationError('coordination_invalid_request')
        entry=dict(e); expected=entry.pop('expected_document_sha256',None)
        if 'producer' not in entry:
            try: entry['producer']=policy.owner_of(safe_path(entry.get('ref')))
            except (ValueError,KeyError,TypeError) as exc: raise ProtectedCoordinationError() from exc
        if expected is not None and (not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected)): raise ProtectedCoordinationError('coordination_invalid_request')
        evidence.append(entry); expectations.append(expected)
    try:
        packet=build_packet(root,policy,payload['context_id'],content,evidence,task['max_bytes'],task_id=task['task_id'],goal=task['goal'],output=task['output'],integrator=task['integrator'],omissions=task.get('omissions',[]),queries=task.get('queries',[]))
        selected=[x for x in packet['inputs'] if x['kind']=='evidence' and 'query_id' not in x]
        if any(expected is not None and x['document_sha256']!=expected for x,expected in zip(selected,expectations)): raise ValueError('selected revision differs')
    except PolicyError as exc:
        if str(exc) in {'mandatory content exceeds byte budget', 'selected content exceeds byte budget', 'complete packet exceeds byte budget', 'query enumeration limit exceeded', 'query match limit exceeded', 'query scan byte limit exceeded', 'query operation byte limit exceeded'}:
            raise ProtectedCoordinationError('coordination_budget_exceeded') from exc
        raise ProtectedCoordinationError() from exc
    except (ValueError,KeyError,TypeError,OSError) as exc: raise ProtectedCoordinationError() from exc
    return {'ok':True,'mode':'approved','packet':packet}


def prepare_preflight(root,binding,payload):
    required={'context_id','approved_revision','base','head','branch','packet','result'}
    if not isinstance(payload,dict) or set(payload)!=required: raise ProtectedCoordinationError('coordination_invalid_request')
    policy=_policy(root,binding,payload['context_id'],payload['approved_revision'])
    if any(not isinstance(payload[k],str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',payload[k]) for k in ('base','head')): raise ProtectedCoordinationError('coordination_invalid_request')
    packet=payload['packet']
    if not isinstance(packet,dict) or packet.get('capability_evidence') is not None or packet.get('required_capabilities') != []:
        raise ProtectedCoordinationError('coordination_preflight_unavailable')
    try: out=preflight(root,policy,context_id=payload['context_id'],base=payload['base'],head=payload['head'],branch=payload['branch'],packet=payload['packet'],result=payload['result'])
    except (ValueError,KeyError,TypeError,OSError) as exc: raise ProtectedCoordinationError('coordination_preflight_unavailable') from exc
    return {'ok':True,'mode':'approved','preflight':out}


def blocker_response(error: ProtectedCoordinationError):
    messages={
        'coordination_session_required': ('A valid local operator session is required.', 'Unlock the local operator in its supported interface.', 'A valid operator session is available.'),
        'coordination_not_available': ('Protected coordination is unavailable in the host configuration.', 'Have the host operator configure and restart the binding.', 'A trusted host binding is configured.'),
        'coordination_not_authorized': ('The requested context is not authorized by the host binding.', 'Use an authorized context or request a specific binding change.', 'The host binding authorizes the requested context.'),
        'coordination_invalid_request': ('The task selection or request is invalid.', 'Correct the explicitly selected task and retry.', 'The request satisfies the packet contract.'),
        'coordination_policy_unavailable': ('The approved policy revision is unavailable or has changed.', 'Refresh the trusted revision and revalidate the task.', 'The task is bound to the current approved policy.'),
        'coordination_content_not_approved': ('The selected content revision is not in approved history.', 'Choose a revision in the approved history.', 'The content revision is approved and still authorized.'),
        'coordination_budget_exceeded': ('The selected task packet exceeds its byte budget.', 'Reduce the authorized selection or revise the packet limit, then retry.', 'The complete packet fits the chosen byte limit.'),
        'coordination_preflight_unavailable': ('The proposal did not satisfy the current preflight.', 'Revalidate the packet, result, branch and current base.', 'The exact proposal satisfies the current preflight.'),
    }
    reason, action, resume=messages.get(error.code,('The selected input is unavailable or unauthorized.','Verify the selected inputs and current policy.','All required inputs are authorized and available.'))
    interfaces={'coordination_session_required':'Local operator / current cockpit session',
                'coordination_not_available':'Local operator host startup configuration',
                'coordination_not_authorized':'Local operator host / task coordinator',
                'coordination_policy_unavailable':'Local operator host / trusted reference',
                'coordination_preflight_unavailable':'Current task integration coordinator'}
    interface=interfaces.get(error.code,'Current task coordinator')
    return {'ok':False,'error_code':error.code,'blocker':{'action':'prepare_coordination','target':'requested task','reason':reason,'owner':'authorized operator','required_action':action,'interface':interface,'resume_condition':resume,'status':error.status}}
