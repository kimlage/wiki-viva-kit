"""Optional finite schedule admission advice; never executes or stores work."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from .context_policy import PolicyError, safe_path
from .context_packet import blocker, _reject_secrets
from .repository_reader import RepositoryReader, RepositoryReadError

MAX_BYTES = 65536
SCHEMA = Path(__file__).resolve().parents[1] / 'docs/references/schemas/wiki-context-schedule-v1.schema.json'


def _validate(value, part=None):
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode()) > MAX_BYTES: raise PolicyError('schedule input exceeds budget')
        _reject_secrets(encoded)
        schema = json.loads(SCHEMA.read_text())
        if part: schema = {'$ref': '#/$defs/' + part, '$defs': schema['$defs']}
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    except (ValidationError, ValueError, TypeError, RecursionError) as exc:
        raise PolicyError('invalid schedule input') from exc


def validate_schedule(schedule):
    _validate(schedule, 'schedule')
    safe_path(schedule['task_template'])
    try: ZoneInfo(schedule['trigger']['timezone'])
    except (ZoneInfoNotFoundError, ValueError) as exc: raise PolicyError('invalid timezone') from exc
    return {**schedule, 'enabled': schedule.get('enabled', False)}


def occurrence_id(schedule, due_at):
    """External scheduler supplies occurrence time; no cron/DST calculation here."""
    return hashlib.sha256(json.dumps([schedule['context_id'], schedule['id'], _time(due_at).isoformat()], separators=(',', ':')).encode()).hexdigest()


def _time(value):
    # JSON Schema format checkers are optional; validate independently so a
    # clean installation never accepts an unzoned or malformed timestamp.
    match = re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-]([0-9]{2}):([0-9]{2}))", value
    ) if isinstance(value, str) else None
    if not match or (match.group(1) is not None and (int(match.group(1)) > 23 or int(match.group(2)) > 59)):
        raise PolicyError('invalid schedule timestamp')
    try:
        return dt.datetime.fromisoformat(value.replace('t', 'T').replace('z', 'Z').replace('Z', '+00:00')).astimezone(dt.timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise PolicyError('invalid schedule timestamp') from exc


def evaluate_wake(policy, schedule, wake, observation=None):
    """Return bounded advice from caller state, without persistence or execution.

    The caller is responsible for an authorized, complete, atomically reserved
    scheduler snapshot. Unknown binding never authorizes actual admission.
    """
    _validate({'schedule': schedule, 'wake': wake, 'observation': observation})
    schedule = validate_schedule(schedule)
    now, due, latest = map(_time, (wake['now'], wake['due_at'], wake['latest_due_at']))
    if observation is not None:
        for field in ('last_wake', 'next_expected'):
            if observation[field] is not None: _time(observation[field])
    cid = schedule['context_id']
    # Reject a mixed-owner snapshot before disclosing IDs, counts or observations.
    if any(t['context_id'] != cid for t in wake['tasks'] + wake['records']):
        raise PolicyError('snapshot outside selected context')
    for items, key in ((wake['tasks'], 'task_id'), (wake['records'], 'task_id')):
        if len({x[key] for x in items}) != len(items): raise PolicyError('duplicate task identity')
    out = {'schema_version': 'wiki.schedule-decision/v1', 'decision': 'no-op',
           'reason': 'disabled', 'eligible': [], 'blockers': [], 'llm_calls': 0,
           'execution_authorized': False, 'admission': 'blocked',
           'binding': 'unknown' if observation is None else 'reported',
           'observation': None, 'state_write': 'not_performed',
           'cost': 'not_measured', 'process_termination': 'unknown'}
    def blocked(reason, status='pending'):
        out.update(decision='blocked', reason=reason, eligible=[])
        out['blockers'] = [blocker('evaluate_schedule', 'selected_context', reason,
            'external_adapter', 'revalidate retained state and authority',
            'current authorization and reconciled state', status)]
        return out
    if wake['global_paused']:
        out['reason'] = 'global_paused'; return out
    try:
        current = policy.fresh()
        if current.policy_revision != schedule['policy_revision']: return blocked('policy_changed')
        if cid not in current.contexts: return blocked('context_unavailable')
        ref = schedule['task_template']
        if current.owner_of(ref) != cid or not current.permits(cid, 'read', ref):
            return blocked('template_denied', 'denied')
        if current.contexts[cid]['owner'] != schedule['owner']: return blocked('owner_changed')
        # Only safe tracked regular-file metadata is inspected; no catalogue/blob read.
        reader = RepositoryReader(current._binding[0], current.policy_revision)
        if ref not in reader.paths: return blocked('template_missing_or_unsupported')
    except (PolicyError, RepositoryReadError):
        return blocked('policy_unavailable')
    # Observations are reports, never independently verified installation evidence.
    out['observation'] = observation
    if wake['global_paused']:
        out['reason'] = 'global_paused'; return out
    if not schedule['enabled']: return out
    if observation and observation['paused']:
        out['reason'] = 'reported_paused'; return out
    if latest < due or latest > now: return blocked('invalid_occurrence_order')
    if due > now or due != latest:
        out['reason'] = 'not_latest_due'; return out
    if wake['active_runs']:
        return blocked('overlap_skip_and_record')
    records = {r['task_id']: r for r in wake['records']}
    # An expired lease is deliberately not accepted as evidence of termination.
    statuses = {r['status'] for r in records.values()}
    if 'uncertain' in statuses: return blocked('effect_reconciliation_required', 'uncertain')
    if 'running' in statuses: return blocked('executor_completion_unknown', 'uncertain')
    if 'denied' in statuses: return blocked('authorization_denied', 'denied')
    occurrence = occurrence_id(schedule, due_at=due.isoformat())
    limits = schedule['limits']
    budget = min(limits['max_tasks_per_wake'], max(0, limits['max_attempts_per_wake'] - wake['attempts_this_wake']))
    candidates = []
    for task in sorted(wake['tasks'], key=lambda t: t['task_id']):
        previous = records.get(task['task_id'])
        if previous:
            if previous['occurrence_id'] == occurrence and previous['status'] == 'completed': continue
            if previous['fingerprint'] == task['fingerprint'] and previous['status'] == 'completed': continue
            same_effect = previous['fingerprint'] == task['fingerprint']
            # A completed older version releases a new effect budget, never a
            # retry budget for that earlier effect. Other unresolved versions wait.
            if not same_effect and previous['status'] != 'completed': continue
            if same_effect:
                if previous['attempts'] >= limits['max_attempts_per_effect']: continue
                if previous['attempts'] and previous['status'] != 'safe_failure': continue
        effect = hashlib.sha256(json.dumps(['wiki.schedule-effect/v1', cid,
            task['task_id'], task['fingerprint']], separators=(',', ':')).encode()).hexdigest()
        candidates.append({'task_id': task['task_id'], 'occurrence_id': occurrence,
            'task_identity': hashlib.sha256(json.dumps(['wiki.schedule-task/v1', cid,
                task['task_id']], separators=(',', ':')).encode()).hexdigest(),
            'work_id': effect, 'effect_id': effect, 'effect_identity_version': 'wiki.schedule-effect/v1'})
    # Revalidate once more before returning references to eligible work.
    try:
        if policy.fresh().policy_revision != schedule['policy_revision']: return blocked('policy_changed')
    except PolicyError: return blocked('policy_unavailable')
    out['eligible'] = candidates[:budget]
    out.update(decision='eligible' if out['eligible'] else 'no-op',
               reason='changed_work' if out['eligible'] else 'no_changed_work_or_budget')
    return out
