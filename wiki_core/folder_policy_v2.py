"""Experimental folder-derived protected policy, not wired to v1 consumers.

This opt-in parser discovers context boundaries from tracked instruction files.
It does not provide an ACL, migrate v1 identifiers or reuse v1 receipts.
Callers must not pass its result to v1 packet/receipt/integration machinery.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

import yaml

from wiki_core.context_policy import ContextPolicy, PolicyError, UniqueLoader, _git, revision, safe_path
from wiki_core.repository_reader import RepositoryReader


FORMAT = 'wiki.folder-controls/v2'
CONTROLS_PATH = 'wiki-context-controls.yaml'


def folder_id(folder: str) -> str:
    """Stable within v2 for an exact path; moves require explicit migration."""
    folder = safe_path(folder, allow_root=True)
    return 'folder-v2-' + hashlib.sha256(folder.encode('utf-8')).hexdigest()


class FolderPolicyV2(ContextPolicy):
    """Mechanical ceilings for discovered folders; no native ACL is asserted."""
    format_version = FORMAT

    def owner_of(self, path):
        owner = super().owner_of(path)
        root = self.contexts[owner]['root']
        root_depth = 0 if root == '.' else len(root.split('/'))
        for folder in getattr(self, 'unindexed_instruction_folders', ()):
            if (path == folder or path.startswith(folder + '/')) and len(folder.split('/')) > root_depth:
                if (owner == getattr(self, '_auxiliary_context', None)
                        and folder in getattr(self, '_qualified_auxiliary', ())):
                    continue
                raise PolicyError('ownership unavailable below an instruction folder without index')
        return owner

    def fresh(self):
        if not self._binding:
            raise PolicyError('unbound folder v2 policy')
        root, trusted_ref, controls = self._binding
        if controls != CONTROLS_PATH:
            raise PolicyError('untrusted folder controls path')
        return _load_folder_policy_v2(root, self.policy_revision, trusted_ref)


def _read_controls(reader, path):
    if path not in reader.paths:
        if path in reader.unsupported_paths:
            raise PolicyError('unsupported folder controls')
        return {}
    try:
        value = yaml.load(reader.read(path)['text'], Loader=UniqueLoader)
    except (ValueError, yaml.YAMLError, UnicodeError) as exc:
        raise PolicyError('invalid folder controls') from exc
    if not isinstance(value, dict) or set(value) != {'schema_version', 'controls'} or value['schema_version'] != FORMAT:
        raise PolicyError('invalid folder controls version or fields')
    if not isinstance(value['controls'], dict):
        raise PolicyError('invalid folder controls mapping')
    return value['controls']


def _at_revision(root, sha, controls_path):
    reader = RepositoryReader(root, sha)
    if reader.invalid_paths:
        raise PolicyError('invalid Git path prevents folder discovery')
    names = ('AGENTS.md', 'AGENTS.override.md')
    if any(PurePosixPath(path).name in names for path in reader.unsupported_paths):
        raise PolicyError('unsupported folder instruction')
    candidates = {}
    # Git metadata establishes whether a blob is exactly empty without opening
    # instruction bodies from unrelated contexts. Whitespace-only files are
    # conservatively treated as present and fail later if selected.
    empty_oid = hashlib.sha1(b'blob 0\0').hexdigest() if len(sha) == 40 else hashlib.sha256(b'blob 0\0').hexdigest()
    for path in reader.paths:
        name = PurePosixPath(path).name
        if name not in names:
            continue
        folder = str(PurePosixPath(path).parent)
        safe_path(folder, allow_root=True)
        if reader._entries[path] != empty_oid:
            candidates.setdefault(folder, {})[name] = path
    if '.' not in candidates:
        raise PolicyError('root folder instruction required')
    instructions = {folder: files.get('AGENTS.override.md', files.get('AGENTS.md'))
                    for folder, files in candidates.items()}
    index_paths = {}
    for folder in instructions:
        prefix = '' if folder == '.' else folder + '/'
        index = prefix + 'index.md'
        if folder == '.':
            # Root exists independently of a conventional index. Its caller
            # must select one explicitly from its AGENTS declaration.
            index_paths[folder] = index if index in reader.paths else None
        elif index in reader.paths:
            index_paths[folder] = index
    context_instructions = {folder: instructions[folder] for folder in index_paths}
    controls = _read_controls(reader, controls_path)
    # Paths attach mechanics only. They never declare contexts or parentage.
    # A missing entry denies all, including inherited effects; no entry is
    # needed merely to discover a folder in the separate navigation reader.
    if not set(controls) <= set(context_instructions):
        raise PolicyError('mechanical controls refer to an unknown folder')
    ids = {folder: folder_id(folder) for folder in context_instructions}
    contexts = []
    for folder in sorted(context_instructions, key=lambda p: (0 if p == '.' else len(p.split('/')), p)):
        data = controls.get(folder, {'policy': {'read': [], 'write': [], 'capabilities': [],
                                                 'deny': {}, 'publication': []}, 'imports': [], 'exports': []})
        if not isinstance(data, dict) or set(data) != {'policy', 'imports', 'exports'}:
            raise PolicyError('invalid folder controls entry')
        parent_candidates = [p for p in context_instructions if p != folder and (p == '.' or folder.startswith(p + '/'))]
        parent = max(parent_candidates, key=lambda p: 0 if p == '.' else len(p.split('/'))) if parent_candidates else None
        if folder != '.' and parent is None:
            raise PolicyError('folder parent unavailable')
        rules = {}
        for key in ('imports', 'exports'):
            if not isinstance(data[key], list):
                raise PolicyError('invalid folder connection list')
            rules[key] = []
            for rule in data[key]:
                if not isinstance(rule, dict) or rule.get('from_context') not in ids or rule.get('to_context') not in ids:
                    raise PolicyError('unknown folder connection endpoint')
                converted = dict(rule)
                converted['from_context'] = ids[converted['from_context']]
                converted['to_context'] = ids[converted['to_context']]
                rules[key].append(converted)
        contexts.append({'id': ids[folder], 'parent': ids[parent] if parent else None,
                         'root': folder, 'purpose': 'See folder instructions', 'owner': 'not declared',
                         'instructions': [context_instructions[folder]], 'skills': [], 'templates': [],
                         'policy': data['policy'], **rules})
    policy = FolderPolicyV2({'schema_version': 'wiki.context/v1', 'contexts': contexts}, sha)
    policy._inspection_root = str(Path(root).resolve())
    policy.controls_path = controls_path
    policy.folder_ids = ids
    policy.index_paths = index_paths
    policy.instruction_paths = instructions
    policy.unindexed_instruction_folders = sorted(set(instructions) - set(index_paths))
    return policy


def _load_folder_policy_v2(root, approved_revision, trusted_ref):
    """Internal ref-bound loader; historical use requires an ancestry proof."""
    root = Path(root).resolve()
    controls_path = CONTROLS_PATH
    if Path(_git(root, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve() != root:
        raise PolicyError('repository must be its Git root')
    sha = revision(root, approved_revision)
    if sha != revision(root, trusted_ref):
        raise PolicyError('policy revision is not current trusted approval ref')
    result = _at_revision(root, sha, controls_path)
    result._binding = (str(root), trusted_ref, controls_path)
    return result


def load_folder_policy_v2(root, approved_revision):
    """Load from the configured origin/main approval ref; never activate it."""
    return _load_folder_policy_v2(root, approved_revision, 'refs/remotes/origin/main')
