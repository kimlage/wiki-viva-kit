"""Explicit protected coordination; caller binding is trusted host configuration."""
from __future__ import annotations
import os
import re
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from wiki_core.context_policy import load_policy, safe_path, PolicyError, revision
from wiki_core.context_packet import build_packet
from wiki_core.context_integration import preflight
from wiki_core.git_env import local_git_environment, local_git_executable
from wiki_core.repo_host import RepositoryGrant

class ProtectedCoordinationError(ValueError):
    def __init__(self, code='coordination_input_unavailable', status='pending'):
        self.code=code; self.status=status
        super().__init__(code)

@dataclass(frozen=True)
class CoordinationBinding:
    contexts: tuple[str,...]
    trusted_ref: str
    manifest: str='wiki.config.yaml'
    repository_grants: tuple[RepositoryGrant,...]=()

    def __post_init__(self):
        if self.manifest not in ('context.yaml', 'wiki.config.yaml'): raise ValueError('invalid coordination manifest')
        if not isinstance(self.contexts,tuple) or not self.contexts or len(self.contexts)>64 or any(not isinstance(c,str) for c in self.contexts) or len(set(self.contexts))!=len(self.contexts): raise ValueError('invalid coordination host binding')
        for context in self.contexts:
            if self.manifest == 'wiki.config.yaml':
                safe_path(context, allow_root=True)
            elif not re.fullmatch(r'[a-z0-9][a-z0-9/_-]*',context):
                raise ValueError('invalid coordination host binding')
        if not isinstance(self.trusted_ref,str) or not re.fullmatch(r'refs/(?:heads|remotes)/[A-Za-z0-9][A-Za-z0-9/._-]*',self.trusted_ref) or '..' in self.trusted_ref: raise ValueError('invalid coordination trusted reference')
        if (not isinstance(self.repository_grants, tuple) or len(self.repository_grants) > 32
                or any(not isinstance(item, RepositoryGrant) for item in self.repository_grants)
                or len({item.selection_id for item in self.repository_grants}) != len(self.repository_grants)
                or any(item.executor not in self.contexts or item.integrator not in self.contexts for item in self.repository_grants)
                or (self.repository_grants and self.manifest != 'wiki.config.yaml')):
            raise ValueError('invalid coordination host binding')

    @classmethod
    def from_environment(cls, env: Mapping[str,str] | None=None):
        env=os.environ if env is None else env
        if env.get('WIKI_COORDINATION_MANIFEST','').strip(): raise ValueError('coordination manifest override is unsupported')
        contexts=env.get('WIKI_COORDINATION_ALLOWED_CONTEXTS','').strip()
        trusted=env.get('WIKI_COORDINATION_TRUSTED_REF','').strip()
        mode=env.get('WIKI_COORDINATION_CONTEXT_MODE','').strip()
        raw_grants = env.get('WIKI_COORDINATION_REPOSITORY_GRANTS', '').strip()
        if mode not in ('', 'v1', 'folder'): raise ValueError('invalid coordination context mode')
        if not contexts and not trusted and not mode and not raw_grants: return None
        if not contexts: raise ValueError('incomplete coordination host binding')
        grants = []
        if raw_grants:
            if len(raw_grants.encode('utf-8')) > 100_000: raise ValueError('invalid host repository grants')
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError('duplicate host repository field')
                    result[key] = value
                return result
            try:
                rows = json.loads(raw_grants, object_pairs_hook=unique)
                required = {'selection_id', 'root', 'identity', 'revision', 'path', 'executor', 'integrator'}
                if not isinstance(rows, list) or len(rows) > 32: raise ValueError('invalid host repository grants')
                for row in rows:
                    if not isinstance(row, dict) or not required <= set(row) or set(row) - (required | {'max_bytes', 'event_target'}):
                        raise ValueError('invalid host repository grants')
                    grants.append(RepositoryGrant(**row))
            except (TypeError, ValueError, OSError) as exc:
                raise ValueError('invalid host repository grants') from exc
        return cls(tuple(c.strip() for c in contexts.split(',')),trusted or 'refs/remotes/origin/main',
                   'context.yaml' if mode == 'v1' else 'wiki.config.yaml', tuple(grants))


def capability(root: Path, binding: CoordinationBinding | None) -> dict:
    if binding is None: return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':False,'reason':'not_available_or_not_authorized'}
    try:
        sha=revision(root,binding.trusted_ref)
        policy=load_policy(root,sha,binding.manifest,trusted_ref=binding.trusted_ref)
        expected_format = 'folder' if binding.manifest == 'wiki.config.yaml' else None
        if getattr(policy,'format_version',None) != expected_format:
            raise PolicyError('coordination authority format differs')
        contexts=[c for c in binding.contexts if c in policy.contexts]
    except (ValueError,OSError): contexts=[]
    if not contexts: return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':False,'reason':'not_available_or_not_authorized'}
    return {'ok':True,'schema_version':'wiki.coordination-capability/v1','available':True,'contexts':contexts,'policy_revision':sha,
            'new_packet_mode': 'folder' if binding.manifest == 'wiki.config.yaml' else 'historical_only',
            'repository_selections': [{'selection_id': grant.selection_id, 'executor': grant.executor,
                'integrator': grant.integrator, 'publication_configured': grant.event_target is not None}
                for grant in binding.repository_grants]}


def _policy(root, binding, context_id, approved_revision):
    if binding is None: raise ProtectedCoordinationError('coordination_not_available')
    if not isinstance(context_id,str) or context_id not in binding.contexts: raise ProtectedCoordinationError('coordination_not_authorized','denied')
    if not isinstance(approved_revision,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',approved_revision): raise ProtectedCoordinationError('coordination_invalid_request')
    try: policy=load_policy(root,approved_revision,binding.manifest,trusted_ref=binding.trusted_ref)
    except (PolicyError,ValueError,OSError) as exc: raise ProtectedCoordinationError('coordination_policy_unavailable') from exc
    expected_format = 'folder' if binding.manifest == 'wiki.config.yaml' else None
    if getattr(policy,'format_version',None) != expected_format:
        raise ProtectedCoordinationError('coordination_policy_unavailable')
    if context_id not in policy.contexts: raise ProtectedCoordinationError('coordination_not_authorized','denied')
    return policy


def prepare_packet(root, binding, payload):
    if binding is None:
        raise ProtectedCoordinationError('coordination_not_available')
    if binding.manifest != 'wiki.config.yaml':
        raise ProtectedCoordinationError('coordination_v1_retired')
    required_payload={'context_id','approved_revision','content_revision','task'}
    folder_mode = binding is not None and binding.manifest == 'wiki.config.yaml'
    allowed_payload=required_payload | ({'entry_folder','entry_index'} if folder_mode else set())
    if not isinstance(payload,dict) or not required_payload <= set(payload) or set(payload)-allowed_payload: raise ProtectedCoordinationError('coordination_invalid_request')
    if folder_mode and 'entry_folder' not in payload: raise ProtectedCoordinationError('coordination_invalid_request')
    policy=_policy(root,binding,payload['context_id'],payload['approved_revision'])
    folder_options={}
    if folder_mode:
        try:
            folder_options['entry_folder']=safe_path(payload['entry_folder'], allow_root=True)
            if 'entry_index' in payload: folder_options['entry_index']=safe_path(payload['entry_index'])
        except (PolicyError, TypeError) as exc: raise ProtectedCoordinationError('coordination_invalid_request') from exc
    content=payload['content_revision']; task=payload['task']
    if not isinstance(content,str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',content): raise ProtectedCoordinationError('coordination_invalid_request')
    # Approved-mode history is confined to ancestors of the trusted tip.
    if subprocess.run([local_git_executable(), '--no-lazy-fetch','-C',str(root),'merge-base','--is-ancestor',content,policy.policy_revision],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=local_git_environment()).returncode: raise ProtectedCoordinationError('coordination_content_not_approved')
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
        packet=build_packet(root,policy,payload['context_id'],content,evidence,task['max_bytes'],task_id=task['task_id'],goal=task['goal'],output=task['output'],integrator=task['integrator'],omissions=task.get('omissions',[]),queries=task.get('queries',[]),**folder_options)
        selected=[x for x in packet['inputs'] if x['kind']=='evidence' and 'query_id' not in x]
        # Folder qualification may add authorized evidence before the explicit
        # selection. The builder appends explicit evidence in input order.
        if len(selected) < len(expectations): raise ValueError('selected evidence unavailable')
        explicit=selected[-len(expectations):] if expectations else []
        if any(expected is not None and x['document_sha256']!=expected for x,expected in zip(explicit,expectations)): raise ValueError('selected revision differs')
    except PolicyError as exc:
        if str(exc) in {'mandatory content exceeds byte budget', 'selected content exceeds byte budget', 'complete packet exceeds byte budget', 'query enumeration limit exceeded', 'query match limit exceeded', 'query scan byte limit exceeded', 'query operation byte limit exceeded'}:
            raise ProtectedCoordinationError('coordination_budget_exceeded') from exc
        raise ProtectedCoordinationError() from exc
    except (ValueError,KeyError,TypeError,OSError) as exc: raise ProtectedCoordinationError() from exc
    return {'ok':True,'mode':'approved','packet':packet}


def prepare_preflight(root,binding,payload):
    required={'context_id','approved_revision','base','head','branch','packet','result'}
    if not isinstance(payload,dict) or not required <= set(payload) or set(payload) - (required | {'additional_readers'}): raise ProtectedCoordinationError('coordination_invalid_request')
    policy=_policy(root,binding,payload['context_id'],payload['approved_revision'])
    readers = payload.get('additional_readers', [])
    if (not isinstance(readers, list) or len(readers) > 64
            or any(not isinstance(reader, str) or reader not in binding.contexts for reader in readers)
            or len(set(readers)) != len(readers)):
        raise ProtectedCoordinationError('coordination_not_authorized', 'denied')
    for reader in readers:
        _policy(root, binding, reader, payload['approved_revision'])
    if any(not isinstance(payload[k],str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',payload[k]) for k in ('base','head')): raise ProtectedCoordinationError('coordination_invalid_request')
    packet=payload['packet']
    if not isinstance(packet,dict) or packet.get('capability_evidence') is not None or packet.get('required_capabilities') != []:
        raise ProtectedCoordinationError('coordination_preflight_unavailable')
    expected_format = 'folder' if binding.manifest == 'wiki.config.yaml' else None
    if packet.get('authority_format') != expected_format:
        raise ProtectedCoordinationError('coordination_preflight_unavailable')
    try: out=preflight(root,policy,context_id=payload['context_id'],base=payload['base'],head=payload['head'],branch=payload['branch'],packet=payload['packet'],result=payload['result'],trusted_additional_readers=tuple(readers))
    except (ValueError,KeyError,TypeError,OSError) as exc: raise ProtectedCoordinationError('coordination_preflight_unavailable') from exc
    return {'ok':True,'mode':'approved','preflight':out}


def protected_source_stage(root, binding, stage, payload):
    """Dispatch an in-process host-bound source operation without a new service.

    Host binding is supplied out-of-band, never selected by the payload. Results
    are supplied as objects by the calling host rather than as unchecked paths.
    """
    common = {'context_id', 'approved_revision', 'entry_folder', 'entry_index', 'source_ref'}
    optional = {'context_max_bytes', 'request_max_bytes', 'artifact_context', 'perspective_refs', 'context_selection', 'repository_selection'}
    if stage == 'prepare':
        required, permitted = common | {'source_context'}, common | {'source_context'} | optional
    elif stage == 'record':
        required = common | {'source_id', 'request_id', 'results'}
        permitted = required | optional
    elif stage == 'consolidate':
        required = common | {'source_id', 'request_id', 'source_page', 'event_target', 'date'}
        permitted = required | optional | {'candidates'}
    elif stage == 'compare':
        required = common | {'source_id', 'request_id', 'repository_selection',
            'previous_repository_selection', 'current_repository_selection', 'source_page', 'candidates'}
        permitted = required | optional
    elif stage == 'inspect':
        required = common | {'source_id', 'request_id', 'view'}
        permitted = required | optional | {'chunk_ids', 'candidates', 'max_output_bytes'}
    else:
        raise ProtectedCoordinationError('coordination_invalid_request')
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - permitted:
        raise ProtectedCoordinationError('coordination_invalid_request')
    _policy(root, binding, payload['context_id'], payload['approved_revision'])
    try:
        from wiki_core.ingest import protected
        args = dict(payload)
        if stage == 'consolidate':
            from datetime import date
            args['date'] = date.fromisoformat(args['date'])
        operation = {'prepare': protected.prepare, 'record': protected.record,
                     'consolidate': protected.consolidate, 'compare': protected.compare_repositories,
                     'inspect': protected.inspect}[stage]
        return {'ok': True, 'mode': 'approved', 'stage': stage,
                'result': operation(root, binding, **args)}
    except ProtectedCoordinationError:
        raise
    except protected.ProtectedPartialError as exc:
        raise ProtectedCoordinationError('coordination_partial_effects') from exc
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise ProtectedCoordinationError() from exc


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
        'coordination_partial_effects': ('Some artifacts may have been retained before the operation stopped.', 'Inspect and reconcile the selected artifacts before retrying.', 'Possible partial effects have been inspected and resolved.'),
        'coordination_v1_retired': ('New v1 packet composition is retired.', 'Use a host-bound folder context.', 'A current folder binding is available.'),
    }
    reason, action, resume=messages.get(error.code,('The selected input is unavailable or unauthorized.','Verify the selected inputs and current policy.','All required inputs are authorized and available.'))
    interfaces={'coordination_session_required':'Local operator / current cockpit session',
                'coordination_not_available':'Local operator host startup configuration',
                'coordination_not_authorized':'Local operator host / task coordinator',
                'coordination_policy_unavailable':'Local operator host / trusted reference',
                'coordination_preflight_unavailable':'Current task integration coordinator'}
    interface=interfaces.get(error.code,'Current task coordinator')
    return {'ok':False,'error_code':error.code,'blocker':{'action':'prepare_coordination','target':'requested task','reason':reason,'owner':'authorized operator','required_action':action,'interface':interface,'resume_condition':resume,'status':error.status}}
