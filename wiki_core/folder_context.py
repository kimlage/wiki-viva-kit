"""Inspect folder guidance and indexes at a Git revision, without granting access.

This reader is not the native Codex or Claude instruction loader.  It only
examines tracked blobs inside one explicit repository and does not incorporate
user-level instructions, the active application's configuration or permissions.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from wiki_core.context_policy import PolicyError, _git, revision, safe_path
from wiki_core.repo_read import contains_access_secrets
from wiki_core.folder_declarations_v2 import parse_folder_declarations


class FolderContextError(ValueError):
    """The requested revision or context cannot be inspected safely."""


def _blob(root: Path, sha: str, path: str) -> bytes | None:
    """Read a regular tracked blob; reject symlinks and submodules."""
    entry = _git(root, '--literal-pathspecs', 'ls-tree', '-z', sha, '--', path)
    if not entry:
        return None
    # Compare the exact path to prevent a pathspec match becoming authority.
    rows = [line for line in entry.split(b'\0') if line]
    if len(rows) != 1 or b'\t' not in rows[0]:
        raise FolderContextError('ambiguous Git path')
    metadata, name = rows[0].split(b'\t', 1)
    if name != path.encode('utf-8'):
        raise FolderContextError('ambiguous Git path')
    mode, kind, oid = metadata.split(b' ', 2)
    if mode not in (b'100644', b'100755') or kind != b'blob':
        raise FolderContextError('instruction or index is not a regular Git blob')
    oid = oid.decode('ascii')
    if int(_git(root, 'cat-file', '-s', oid)) > 2_000_000:
        raise FolderContextError('instruction or index exceeds file size limit')
    return _git(root, 'cat-file', 'blob', oid)


def inspect_folder(root: str | Path, ref: str, folder: str, *, max_instruction_bytes: int = 32768, index_path: str | None = None) -> dict:
    """Return the tracked instruction lineage and selected context index at ``ref``.

    ``folder`` is a repository-relative directory. Contexts are identified by
    a nonempty AGENTS.override.md or AGENTS.md, with override taking precedence.
    Only the nearest selected context's index is read, never ancestor indexes.
    A nested index defaults to local index.md. A root index is never guessed:
    the caller selects a path explicitly declared in the root instruction.
    A missing/empty selected index is an explicit omission.
    A size limit is fail-closed: no incomplete instruction chain is presented.
    The caller must independently establish access, trusted revision, and policy.
    """
    try:
        root = Path(root).resolve(strict=True)
        actual = Path(_git(root, 'rev-parse', '--show-toplevel').decode('utf-8').strip()).resolve()
        if root != actual:
            raise FolderContextError('repository must be its Git root')
        sha = revision(root, ref)
        folder = safe_path(folder, allow_root=True)
        if not isinstance(max_instruction_bytes, int) or isinstance(max_instruction_bytes, bool) or max_instruction_bytes < 1:
            raise FolderContextError('invalid instruction byte limit')
        if folder != '.':
            kind = _git(root, 'cat-file', '-t', f'{sha}:{folder}').strip()
            if kind != b'tree':
                raise FolderContextError('context folder is not a Git tree')
        components = [] if folder == '.' else folder.split('/')
        directories = ['.'] + ['/'.join(components[:i]) for i in range(1, len(components) + 1)]
        contexts = []
        total = 0
        for directory in directories:
            prefix = '' if directory == '.' else directory + '/'
            selected = None
            for filename in ('AGENTS.override.md', 'AGENTS.md'):
                path = prefix + filename
                body = _blob(root, sha, path)
                if body is not None and body.strip():
                    selected = (path, body)
                    break
            if selected is None:
                continue
            path, body = selected
            total += len(body)
            if total > max_instruction_bytes:
                raise FolderContextError('instruction chain exceeds byte limit')
            instruction_text = body.decode('utf-8')
            if contains_access_secrets(instruction_text):
                raise FolderContextError('secret detected in instruction')
            contexts.append({
                'folder': directory,
                'instructions': {'path': path, 'sha256': hashlib.sha256(body).hexdigest(), 'text': instruction_text},
            })
        selected_index = None
        missing = []
        if contexts:
            active = contexts[-1]['folder']
            prefix = '' if active == '.' else active + '/'
            declared = parse_folder_declarations(contexts[-1]['instructions']['path'], contexts[-1]['instructions']['text'])['indexes']
            conventional = prefix + 'index.md' if active != '.' else None
            allowed = set(declared) | ({conventional} if conventional else set())
            chosen = safe_path(index_path) if index_path is not None else conventional
            if chosen is not None and chosen not in allowed:
                raise FolderContextError('selected index is not declared by the context')
            index = _blob(root, sha, chosen) if chosen is not None else None
            if index is None or not index.strip():
                missing.append(active)
            else:
                index_text = index.decode('utf-8')
                if contains_access_secrets(index_text):
                    raise FolderContextError('secret detected in index')
                selected_index = {'path': chosen, 'sha256': hashlib.sha256(index).hexdigest(), 'text': index_text}
        return {
            'revision': sha,
            'folder': folder,
            'contexts': contexts,
            'active_context': contexts[-1]['folder'] if contexts else None,
            'index': selected_index,
            'complete': bool(contexts) and selected_index is not None,
            'missing_indexes': missing,
            'instruction_bytes': total,
            'limitations': ['Git-tracked content only; not a native instruction-loading proof', 'No access or effect is authorized by this result'],
        }
    except (PolicyError, OSError, UnicodeError) as exc:
        raise FolderContextError(str(exc)) from exc
