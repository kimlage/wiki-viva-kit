"""Strict, explicit Markdown link declarations in a selected AGENTS body."""
from __future__ import annotations

import posixpath
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from wiki_core.context_policy import PolicyError, safe_path
from wiki_core.repository_reader import canonical_path

_HEADINGS = {
    'Wiki v2: mandatory references': 'mandatory',
    'Wiki v2: indexes': 'indexes',
}


def _resolve(agent_path, href):
    if not isinstance(href, str) or not href or '\\' in href or any(ord(c) < 32 for c in href):
        raise PolicyError('invalid declared local reference')
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path or parsed.path.startswith('/'):
        raise PolicyError('declared reference must be a local file')
    decoded = unquote(parsed.path)
    # Avoid nested encodings and encoded separators or traversal ambiguity.
    if '%' in decoded or '\\' in decoded or '/' in unquote(parsed.path.replace('/', '')):
        raise PolicyError('invalid encoded local reference')
    joined = posixpath.normpath(posixpath.join(str(PurePosixPath(agent_path).parent), decoded))
    if joined in ('.', '..') or joined.startswith('../') or joined.startswith('/'):
        raise PolicyError('declared reference escapes repository')
    try:
        return canonical_path(safe_path(joined))
    except ValueError as exc:
        raise PolicyError('invalid declared local reference') from exc


def parse_folder_declarations(agent_path, text):
    """Parse optional top-level explicit link lists; ordinary links are ignored.

    A present heading must contain one flat bullet list with one plain Markdown
    link per item. Duplicate headings/paths or other blocks fail closed. Values
    are paths only: callers must check ownership, denies, revision and content.
    """
    safe_path(agent_path)
    tokens = MarkdownIt('commonmark').parse(text)
    result = {'mandatory': [], 'indexes': []}
    seen = set(); i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type != 'heading_open' or token.tag != 'h2' or token.level != 0:
            i += 1; continue
        name = tokens[i+1].content.strip() if i + 1 < len(tokens) and tokens[i+1].type == 'inline' else ''
        kind = _HEADINGS.get(name)
        i += 3
        if not kind:
            continue
        if kind in seen:
            raise PolicyError('duplicate folder declaration section')
        seen.add(kind)
        if i >= len(tokens) or tokens[i].type != 'bullet_list_open':
            raise PolicyError('folder declaration needs a flat link list')
        i += 1
        while i < len(tokens) and tokens[i].type != 'bullet_list_close':
            if i + 4 >= len(tokens) or [t.type for t in tokens[i:i+5]] != ['list_item_open', 'paragraph_open', 'inline', 'paragraph_close', 'list_item_close']:
                raise PolicyError('folder declaration needs a flat link list')
            children = tokens[i+2].children or []
            if len(children) != 3 or [c.type for c in children] != ['link_open', 'text', 'link_close']:
                raise PolicyError('folder declaration entry must be one link')
            ref = _resolve(agent_path, children[0].attrs.get('href'))
            if ref in result[kind]:
                raise PolicyError('duplicate folder declaration reference')
            result[kind].append(ref)
            i += 5
        if not result[kind] or i >= len(tokens):
            raise PolicyError('folder declaration needs a flat link list')
        i += 1
        if i < len(tokens) and not (tokens[i].type == 'heading_open' and tokens[i].tag in ('h1', 'h2')):
            raise PolicyError('unexpected folder declaration content')
    return result


def preauthorize_index(policy, folder, index_path):
    """Check selected index metadata before opening any instruction body."""
    index_path = safe_path(index_path)
    if folder not in policy.folder_ids:
        raise PolicyError('selected context unavailable')
    context = policy.folder_ids[folder]
    if policy.owner_of(index_path) != context or not policy.permits(context, 'read', index_path):
        raise PolicyError('selected context index is not authorized by v2 controls')
    return index_path


def authorized_instruction_chain(policy, reader, folder, *, max_bytes, start_folder=None):
    """Read only the physical chain and authorize every declared mandatory ref.

    The caller controls the repository/approved revision and will read the
    declared bodies only after this function verifies owner and denials.
    """
    from wiki_core.context_policy import within
    from wiki_core.repo_read import contains_access_secrets
    context = policy.folder_ids[folder]
    if start_folder is not None and getattr(policy, '_auxiliary_context', None) != context:
        raise PolicyError('auxiliary start is not qualified')
    chain_folder = start_folder if start_folder is not None else folder
    parts = [] if chain_folder == '.' else chain_folder.split('/')
    dirs = ['.'] + ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    rows = []
    running = 0
    for directory in dirs:
        path = policy.instruction_paths.get(directory)
        if path is None:
            continue
        if any(within(path, scope) for scope in policy.effective[context]['deny']['read']):
            raise PolicyError('instruction denied by v2 controls')
        running += reader.blob_size(path)
        if running > max_bytes:
            raise PolicyError('mandatory content exceeds byte budget')
        item = reader.read(path)
        if not item['text'].strip() or contains_access_secrets(item['text']):
            raise PolicyError('invalid or secret folder instruction')
        declarations = parse_folder_declarations(path, item['text'])
        if directory in getattr(policy, '_qualified_auxiliary', ()) and declarations['indexes']:
            raise PolicyError('auxiliary instructions cannot declare a context index')
        if declarations['mandatory']:
            declaring_owner = policy.owner_of(path)
            for ref in declarations['mandatory']:
                if policy.owner_of(ref) != declaring_owner:
                    raise PolicyError('mandatory reference belongs to another context')
                if any(within(ref, scope) for scope in policy.effective[context]['deny']['read']):
                    raise PolicyError('mandatory reference denied by v2 controls')
                if ref not in reader.paths:
                    raise PolicyError('mandatory reference unavailable or unsupported')
        rows.append({'path': path, 'item': item, 'declarations': declarations})
    return rows


def authorized_index(policy, folder, index_path, chain):
    """An explicit caller selection must be conventional or declared locally."""
    index_path = safe_path(index_path)
    entry = next((item for item in chain if item['path'] == policy.instruction_paths.get(folder)), None)
    if entry is None:
        raise PolicyError('selected context instruction unavailable')
    allowed = set(entry['declarations']['indexes'])
    conventional = policy.index_paths.get(folder)
    if folder != '.' and conventional:
        allowed.add(conventional)
    if index_path not in allowed:
        raise PolicyError('selected index is not declared by the context')
    context = policy.folder_ids[folder]
    if policy.owner_of(index_path) != context or not policy.permits(context, 'read', index_path):
        raise PolicyError('selected context index is not authorized by v2 controls')
    return index_path
