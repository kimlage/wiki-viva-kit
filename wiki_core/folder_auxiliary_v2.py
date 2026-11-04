"""Qualify selected auxiliary instructions under a context's current ceilings.

This opt-in view never adds a context or grants access. It reads only markers
whose existing context already permits reading, at the supplied policy revision.
"""
from __future__ import annotations

from copy import copy
from pathlib import Path

from markdown_it import MarkdownIt
from wiki_core.context_policy import ContextPolicy, PolicyError, safe_path, within
from wiki_core.folder_policy_v2 import FORMAT
from wiki_core.repo_read import contains_access_secrets


AUXILIARY_HEADING = 'Wiki v2: auxiliary'
AUXILIARY_STATEMENT = 'This folder adds instructions; ownership stays with the nearest context.'


def has_auxiliary_declaration(text: str) -> bool:
    """Require one exact top-level heading and plain single-paragraph marker."""
    tokens = MarkdownIt('commonmark').parse(text)
    seen = 0
    for index, token in enumerate(tokens):
        if token.type != 'heading_open' or token.tag != 'h2' or token.level != 0:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].content.strip() != AUXILIARY_HEADING:
            continue
        seen += 1
        after = index + 3
        if (after + 2 >= len(tokens) or tokens[after].type != 'paragraph_open'
                or tokens[after + 1].type != 'inline'
                or tokens[after + 1].content.strip() != AUXILIARY_STATEMENT
                or tokens[after + 2].type != 'paragraph_close'):
            return False
        following = after + 3
        if following < len(tokens) and not (tokens[following].type == 'heading_open'
                                              and tokens[following].tag in ('h1', 'h2')):
            return False
    return seen == 1


def require_equivalent_auxiliary_metadata(current, current_reader, historical, historical_reader, folder, start_folder):
    """Prove historical auxiliary markers match authorized current Git blobs.

    No historical body is read. This is conservative: any changed ancestor
    instruction or auxiliary boundary requires separate requalification.
    """
    if (folder not in current.folder_ids or historical.folder_ids.get(folder) != current.folder_ids[folder]
            or current_reader.revision != current.policy_revision
            or historical_reader.revision != historical.policy_revision
            or Path(current_reader.root).resolve() != Path(historical_reader.root).resolve()):
        raise PolicyError('historical auxiliary authority unavailable')
    start_folder = safe_path(start_folder)
    context = current.folder_ids[folder]
    if (ContextPolicy.owner_of(current, start_folder) != context
            or ContextPolicy.owner_of(historical, start_folder) != context):
        raise PolicyError('historical auxiliary owner changed')
    parts = start_folder.split('/')
    directories = ['.'] + ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    for directory in directories:
        path = current.instruction_paths.get(directory)
        if historical.instruction_paths.get(directory) != path:
            raise PolicyError('historical auxiliary instruction chain changed')
        if path is not None and (path not in current_reader.paths or path not in historical_reader.paths
                or current_reader._entries[path] != historical_reader._entries[path]):
            raise PolicyError('historical auxiliary instruction blob changed')
    root = current.contexts[context]['root']
    def boundaries(policy):
        return {path for path in policy.unindexed_instruction_folders
                if within(start_folder, path) and within(path, root) and path != root}
    if boundaries(current) != boundaries(historical):
        raise PolicyError('historical auxiliary boundaries changed')


def historical_auxiliary_view(current, current_reader, historical, historical_reader, folder, start_folder):
    """Preauthorize equivalent historical markers without opening their bodies.

    The caller must first qualify the current view, which validates the marker
    bodies. Identical Git objects plus equivalent boundaries allow checking all
    historical evidence connections before any historic marker is opened.
    """
    context = current.folder_ids[folder]
    if getattr(current, '_auxiliary_context', None) != context:
        raise PolicyError('current auxiliary view is not qualified')
    require_equivalent_auxiliary_metadata(current, current_reader, historical, historical_reader, folder, start_folder)
    start_folder = safe_path(start_folder)
    root = current.contexts[context]['root']
    boundaries = {path for path in historical.unindexed_instruction_folders
                  if within(start_folder, path) and within(path, root) and path != root}
    if (not boundaries or boundaries != set(getattr(current, '_qualified_auxiliary', ()))
            or not any(path.startswith(start_folder + '/') for path in historical_reader.paths)):
        raise PolicyError('historical auxiliary boundaries unavailable')
    for boundary in boundaries:
        path = historical.instruction_paths[boundary]
        if (ContextPolicy.owner_of(historical, path) != context or not historical.permits(context, 'read', path)):
            raise PolicyError('historical auxiliary instruction is not authorized')
    scoped = copy(historical)
    scoped._auxiliary_context = context
    scoped._qualified_auxiliary = frozenset(boundaries)
    return scoped


def qualify_auxiliary(policy, reader, folder: str, start_folder: str, *, max_bytes: int):
    """Return actor-scoped policy view for one selected physical start path.

    Denied marker paths are checked before even asking for blob size or body.
    Both policy and reader must be at the same fixed revision. The caller must
    separately revalidate the trusted ref before and after its operation.
    """
    if getattr(policy, 'format_version', None) != FORMAT or folder not in policy.folder_ids:
        raise PolicyError('auxiliary context unavailable')
    if reader.revision != policy.policy_revision or Path(reader.root).resolve() != Path(policy._inspection_root).resolve():
        raise PolicyError('auxiliary revision or repository mismatch')
    if type(max_bytes) is not int or max_bytes < 1:
        raise PolicyError('invalid auxiliary byte budget')
    start_folder = safe_path(start_folder)
    root = policy.contexts[policy.folder_ids[folder]]['root']
    context = policy.folder_ids[folder]
    if not within(start_folder, root) or ContextPolicy.owner_of(policy, start_folder) != context:
        raise PolicyError('auxiliary start is outside selected context')
    boundaries = [p for p in policy.unindexed_instruction_folders
                  if within(start_folder, p) and within(p, root) and p != root]
    boundaries.sort(key=lambda x: len(x.split('/')))
    if not boundaries or not any(path.startswith(start_folder + '/') for path in reader.paths):
        raise PolicyError('auxiliary start is unavailable')
    qualified = []
    total = 0
    for boundary in boundaries:
        path = policy.instruction_paths[boundary]
        # Nearest indexed owner and current read permission precede blob reads.
        if ContextPolicy.owner_of(policy, path) != context or not policy.permits(context, 'read', path):
            raise PolicyError('auxiliary instruction is not authorized')
        if path not in reader.paths:
            raise PolicyError('auxiliary instruction unavailable')
        total += reader.blob_size(path)
        if total > max_bytes:
            raise PolicyError('auxiliary instructions exceed byte budget')
        text = reader.read(path)['text']
        if not text.strip() or contains_access_secrets(text) or not has_auxiliary_declaration(text):
            raise PolicyError('auxiliary declaration missing or invalid')
        qualified.append(boundary)
    scoped = copy(policy)
    scoped._auxiliary_context = context
    scoped._qualified_auxiliary = frozenset(qualified)
    return scoped
