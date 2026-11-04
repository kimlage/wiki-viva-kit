"""Read-only preview of mechanical v1 to folder-v2 controls.

The preview reads all v1 manifests and candidate AGENTS internally. Only a
coordinator with effective authorization for the entire scope may run it;
aggregate CLI output is not process isolation. This never grants access,
migrates v1 receipts or approves instructions. A caller must explicitly ask
to write a ready proposal, which remains unapproved and inactive.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import stat
from pathlib import Path
import re

import yaml

from wiki_core.context_policy import PolicyError, _git, load_policy, revision, within
from wiki_core.folder_declarations_v2 import parse_folder_declarations
from wiki_core.folder_policy_v2 import CONTROLS_PATH, FORMAT, FolderPolicyV2, _at_revision, folder_id
from wiki_core.repo_read import contains_access_secrets
from wiki_core.repository_reader import RepositoryReader
from wiki_core.git_safety import dangerous_local_config_keys


class FolderMigrationError(ValueError):
    pass


class FolderMigrationUncertain(FolderMigrationError):
    """A proposal file was created, but its final binding is not established."""


def _fixed_sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', value):
        raise FolderMigrationError('fixed_revision_required')
    return value


def _ensure_binding_current(root: Path, approved: str, candidate: str) -> None:
    try:
        if (revision(root, 'refs/remotes/origin/main') != approved
                or revision(root, 'HEAD') != candidate):
            raise FolderMigrationError('migration_binding_moved')
    except FolderMigrationError:
        raise
    except (ValueError, OSError) as exc:
        raise FolderMigrationError('migration_binding_unavailable') from exc


def _boundary_scope_proof(policy, boundaries: list[str]) -> dict:
    """Conservative prefix proof; no body reads or claims about external callers."""
    result = {'boundary_count': len(boundaries), 'read_scope_intersections': 0,
              'write_scope_intersections': 0, 'read_fully_denied_intersections': 0,
              'write_fully_denied_intersections': 0, 'read_uncovered_intersections': 0,
              'write_uncovered_intersections': 0, 'contexts_with_effective_capabilities': 0,
              'contexts_with_effective_publication': 0, 'connection_selector_intersections': 0}
    def intersects(left: str, right: str) -> bool:
        return within(left, right) or within(right, left)
    for context in policy.contexts:
        effective = policy.effective[context]
        for action in ('read', 'write'):
            for boundary in boundaries:
                for scope in effective[action]:
                    if not intersects(boundary, scope):
                        continue
                    result[action + '_scope_intersections'] += 1
                    intersection = boundary if within(boundary, scope) else scope
                    if any(within(intersection, denial) for denial in effective['deny'][action]):
                        result[action + '_fully_denied_intersections'] += 1
                    else:
                        # Partial deny or absence of deny is insufficient to
                        # prove every possible descendant inaccessible.
                        result[action + '_uncovered_intersections'] += 1
        for action in ('capabilities', 'publication'):
            if set(effective[action]) - set(effective['deny'][action]):
                result['contexts_with_effective_' + action] += 1
        for kind in ('imports', 'exports'):
            result['connection_selector_intersections'] += sum(
                any(intersects(boundary, rule['selector']) for boundary in boundaries)
                for rule in policy.contexts[context][kind])
    return result


def prepare_folder_controls(root: Path, approved_revision: str, candidate_revision: str) -> tuple[dict, bytes | None]:
    """Compare approved v1 with a candidate folder tree; no writes or output."""
    root = Path(root).resolve()
    approved = _fixed_sha(approved_revision)
    candidate = _fixed_sha(candidate_revision)
    try:
        if Path(_git(root, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve() != root:
            raise FolderMigrationError('repository_root_mismatch')
        v1 = load_policy(root, approved)
        _ensure_binding_current(root, approved, candidate)
        _git(root, 'merge-base', '--is-ancestor', approved, candidate)
        reader = RepositoryReader(root, candidate)
        if reader.revision != candidate:
            raise FolderMigrationError('candidate_revision_mismatch')
        if CONTROLS_PATH in reader.paths or CONTROLS_PATH in reader.unsupported_paths:
            raise FolderMigrationError('candidate_controls_already_present')
        discovery = _at_revision(root, candidate, CONTROLS_PATH)
    except FolderMigrationError:
        raise
    except (ValueError, OSError, UnicodeError) as exc:
        raise FolderMigrationError('approved_policy_or_candidate_unavailable') from exc

    by_id = {identity: item['root'] for identity, item in v1.contexts.items()}
    old_roots = set(by_id.values())
    new_roots = set(discovery.folder_ids)
    blockers: set[str] = set()
    if old_roots != new_roots:
        blockers.add('context_folders_changed')
    boundary_proof = _boundary_scope_proof(v1, discovery.unindexed_instruction_folders)
    blocking_counts = ('read_uncovered_intersections', 'write_uncovered_intersections',
                       'contexts_with_effective_capabilities', 'contexts_with_effective_publication',
                       'connection_selector_intersections')
    if discovery.unindexed_instruction_folders and any(boundary_proof[key] for key in blocking_counts):
        # A denied/narrowing boundary cannot be assumed harmless if any
        # effective scope, effect or selector might touch it in the future.
        blockers.add('unindexed_instruction_boundaries')
    if old_roots != new_roots:
        _ensure_binding_current(root, approved, candidate)
        return {'status': 'blocked', 'blockers': sorted(blockers), 'written': False}, None

    controls = {}
    synthesized = []
    indexes_by_folder = {}
    missing_mandatory = 0
    missing_indexes = 0
    try:
        for old_id, item in sorted(v1.contexts.items(), key=lambda pair: pair[1]['root']):
            folder = item['root']
            if item.get('workflow') or item.get('defaults'):
                # Their consumers must be understood and migrated separately;
                # the mechanical preview cannot silently discard them.
                blockers.add('structured_fields_need_review')
            new_id = folder_id(folder)
            parent_folder = by_id[item['parent']] if item['parent'] is not None else None
            discovered_parent_id = discovery.contexts[new_id]['parent']
            discovered_parent = (discovery.contexts[discovered_parent_id]['root']
                                 if discovered_parent_id else None)
            if parent_folder != discovered_parent:
                blockers.add('physical_lineage_changed')
            entry = {'policy': copy.deepcopy(item['policy']), 'imports': [], 'exports': []}
            for kind in ('imports', 'exports'):
                for rule in item[kind]:
                    converted = copy.deepcopy(rule)
                    converted['from_context'] = by_id[rule['from_context']]
                    converted['to_context'] = by_id[rule['to_context']]
                    entry[kind].append(converted)
            controls[folder] = entry
            runtime_entry = copy.deepcopy(entry)
            for kind in ('imports', 'exports'):
                for rule in runtime_entry[kind]:
                    rule['from_context'] = folder_id(rule['from_context'])
                    rule['to_context'] = folder_id(rule['to_context'])
            instruction = discovery.instruction_paths[folder]
            text = reader.read(instruction)['text']
            if not text.strip() or contains_access_secrets(text):
                raise FolderMigrationError('candidate_instruction_unavailable_or_unsafe')
            declarations = parse_folder_declarations(instruction, text)
            indexes_by_folder[folder] = declarations['indexes']
            expected = set(item['instructions'] + item['skills'] + item['templates']) - {instruction}
            declared = set(declarations['mandatory'])
            if expected != declared or any(ref not in reader.paths for ref in declared):
                missing_mandatory += 1
                blockers.add('mandatory_reference_parity_unproven')
            if folder == '.' and not declarations['indexes']:
                missing_indexes += 1
                blockers.add('root_index_not_declared')
            synthesized.append({'id': new_id, 'parent': folder_id(parent_folder) if parent_folder else None,
                'root': folder, 'purpose': 'See folder instructions', 'owner': 'not declared',
                'instructions': [instruction], 'skills': [], 'templates': [], **runtime_entry})
        v2 = FolderPolicyV2({'schema_version': 'wiki.context/v1', 'contexts': synthesized}, candidate)
        v2.unindexed_instruction_folders = discovery.unindexed_instruction_folders
        for folder, declared_indexes in indexes_by_folder.items():
            candidates = list(declared_indexes)
            if folder != '.' and discovery.index_paths.get(folder):
                candidates.append(discovery.index_paths[folder])
            if not candidates:
                blockers.add('context_index_unavailable')
            for ref in candidates:
                try:
                    if (ref not in reader.paths or v2.owner_of(ref) != folder_id(folder)
                            or not v2.permits(folder_id(folder), 'read', ref)):
                        blockers.add('context_index_unavailable')
                except PolicyError:
                    blockers.add('context_index_unavailable')
        if any(v1.effective[old_id] != v2.effective[folder_id(item['root'])]
               for old_id, item in v1.contexts.items()):
            blockers.add('effective_limits_changed')
        # Preserve bilateral rules byte-for-byte except for endpoint identity;
        # v1 constructor validates endpoints, ownership and policy semantics.
        for old_id, item in v1.contexts.items():
            newer = v2.contexts[folder_id(item['root'])]
            for kind in ('imports', 'exports'):
                restored = copy.deepcopy(newer[kind])
                reverse = {folder_id(path): old for old, path in by_id.items()}
                for rule in restored:
                    rule['from_context'] = reverse[rule['from_context']]
                    rule['to_context'] = reverse[rule['to_context']]
                if restored != item[kind]:
                    blockers.add('bilateral_rules_changed')
                for rule in item[kind]:
                    kwargs = {k: rule[k] for k in ('section', 'field') if k in rule}
                    # Compare at expiry and one day later to preserve both
                    # effective and expired decisions, without renewing grants.
                    expiry = dt.date.fromisoformat(rule['expires'])
                    dates = [expiry] + ([expiry + dt.timedelta(days=1)] if expiry < dt.date.max else [])
                    for date in dates:
                        try:
                            a = v1.connection(rule['from_context'], rule['to_context'], rule['selector'],
                                              rule['use'], rule['classification'], today=date, **kwargs)
                            b = v2.connection(folder_id(by_id[rule['from_context']]), folder_id(by_id[rule['to_context']]),
                                              rule['selector'], rule['use'], rule['classification'], today=date, **kwargs)
                            if a != b:
                                blockers.add('connection_decision_changed')
                        except PolicyError:
                            blockers.add('connection_decision_unavailable')
        proposal = {'schema_version': FORMAT, 'controls': controls}
        if contains_access_secrets(proposal):
            raise FolderMigrationError('proposed_controls_contain_access_secrets')
    except FolderMigrationError:
        raise
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise FolderMigrationError('migration_comparison_unavailable') from exc
    raw = yaml.safe_dump(proposal, allow_unicode=True, sort_keys=True).encode('utf-8')
    _ensure_binding_current(root, approved, candidate)
    report = {'status': 'blocked' if blockers else 'ready_for_review', 'blockers': sorted(blockers),
              'context_count': len(controls), 'unindexed_instruction_boundary_count': len(discovery.unindexed_instruction_folders),
              'ownership_change': ('none' if not discovery.unindexed_instruction_folders else
                                   'blocked_unproven' if 'unindexed_instruction_boundaries' in blockers else
                                   'ownership_changed_no_effective_grants'),
              'boundary_scope_proof': boundary_proof,
              'contexts_with_mandatory_mismatch': missing_mandatory, 'contexts_without_root_index_declaration': missing_indexes,
              'written': False,
              'limitations': ['global authorized coordinator required; aggregate output is not isolation',
                              'ownership changes can affect callers even when no effective grants intersect',
                              'ready does not prove purpose, owner or normative equivalence or any new grant',
                              'no approval, native session, historical receipt, schedule or requirement migration proved',
                              'writing requires the exact clean candidate worktree before sync']}
    return report, raw if not blockers else None


def write_folder_controls(root: Path, approved_revision: str, candidate_revision: str) -> dict:
    """Recompute, then create the unapproved candidate in an exact worktree."""
    report, proposal = prepare_folder_controls(root, approved_revision, candidate_revision)
    if report.get('status') != 'ready_for_review' or proposal is None:
        raise FolderMigrationError('blocked_proposal_not_written')
    root = Path(root).resolve()
    try:
        if _git(root, 'rev-parse', '--verify', 'HEAD').decode().strip() != _fixed_sha(candidate_revision):
            raise FolderMigrationError('candidate_worktree_revision_mismatch')
        if dangerous_local_config_keys(root):
            raise FolderMigrationError('candidate_git_config_requires_review')
        if _git(root, '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false',
                '-c', 'core.hooksPath=/dev/null', 'status', '--porcelain', '--untracked-files=all'):
            raise FolderMigrationError('candidate_worktree_not_clean')
        if revision(root, 'refs/remotes/origin/main') != _fixed_sha(approved_revision):
            raise FolderMigrationError('approved_policy_moved')
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(root / CONTROLS_PATH, flags, 0o600)
        try:
            with os.fdopen(fd, 'w+b') as stream:
                stream.write(proposal)
                stream.flush()
                stream.seek(0)
                if stream.read() != proposal:
                    raise FolderMigrationUncertain('proposal_written_binding_uncertain')
                st = os.fstat(stream.fileno())
                target = os.lstat(root / CONTROLS_PATH)
                if (st.st_dev, st.st_ino) != (target.st_dev, target.st_ino):
                    raise FolderMigrationUncertain('proposal_written_binding_uncertain')
        except (OSError, ValueError) as exc:
            # Do not unlink by path: another actor could have replaced it.
            raise FolderMigrationUncertain('proposal_written_binding_uncertain') from exc
        try:
            _ensure_binding_current(root, _fixed_sha(approved_revision), _fixed_sha(candidate_revision))
        except FolderMigrationError as exc:
            # The exclusive file remains for explicit inspection; no ready or
            # deletion claim is safe after a concurrent ref movement.
            raise FolderMigrationUncertain('proposal_written_binding_uncertain') from exc
        try:
            # Ref checking can itself race with replacement of the file. Open
            # again without following links and compare both inode and bytes.
            # This is a readback, not an atomic compare-and-swap.
            verify_fd = os.open(root / CONTROLS_PATH, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(verify_fd, 'rb') as verify:
                observed = os.fstat(verify.fileno())
                path_stat = os.lstat(root / CONTROLS_PATH)
                if (not stat.S_ISREG(path_stat.st_mode)
                        or (st.st_dev, st.st_ino) != (observed.st_dev, observed.st_ino)
                        or (observed.st_dev, observed.st_ino) != (path_stat.st_dev, path_stat.st_ino)
                        or verify.read(len(proposal) + 1) != proposal):
                    raise FolderMigrationUncertain('proposal_written_binding_uncertain')
        except (OSError, ValueError) as exc:
            raise FolderMigrationUncertain('proposal_written_binding_uncertain') from exc
        return report
    except FolderMigrationError:
        raise
    except (OSError, ValueError) as exc:
        raise FolderMigrationError('proposal_not_written') from exc
