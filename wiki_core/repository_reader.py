"""Deterministic reads from one immutable Git commit, independent of snapshots.

This is a low-level content primitive. Current authorization belongs to the
policy wrapper, including when that wrapper requests historical content.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from typing import Any, Iterable

from wiki_core.content_sections import select_section
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.git_env import local_git_environment, local_git_executable, local_git_tree
from wiki_core.git_safety import GitSafetyError


class RepositoryReadError(ValueError):
    pass


def canonical_path(value: str) -> str:
    if (not isinstance(value, str) or not value or '\\' in value
            or any(ord(char) < 32 for char in value)):
        raise RepositoryReadError('unsafe repository path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'.', '..'} for part in value.split('/')):
        raise RepositoryReadError('unsafe repository path')
    if any(part.lower() in {'.git', '.env', '.aws', '.ssh', 'secrets', 'credentials'}
           or part.lower().startswith('.env.') for part in path.parts):
        raise RepositoryReadError('restricted repository path')
    if path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}:
        raise RepositoryReadError('restricted repository path')
    return path.as_posix()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=str).encode()).hexdigest()


class RepositoryReader:
    def __init__(self, root: Path | str, revision: str = 'HEAD', *, exact_path: str | None = None, before_tree=None):
        self.root = Path(root).resolve()
        if not isinstance(revision, str) or not revision or revision.startswith('-'):
            raise RepositoryReadError('invalid repository revision')
        self.revision = self._git('rev-parse', '--verify', f'{revision}^{{commit}}').decode().strip()
        try:
            if before_tree is not None: before_tree()
            selection = () if exact_path is None else ('--', ':(literal)' + canonical_path(exact_path))
            tree = local_git_tree(self.root, 'ls-tree', '-r', '-z', self.revision, *selection)
        except GitSafetyError as exc:
            raise RepositoryReadError('repository tree enumeration unavailable or exceeded limit') from exc
        entries = tree.split(b'\0')
        self._entries = {}
        self._unsupported = []
        self._invalid_paths = []
        for entry in entries:
            if not entry:
                continue
            info, raw_path = entry.split(b'\t', 1)
            mode, kind, blob = info.decode().split()
            try:
                path = raw_path.decode('utf-8')
            except UnicodeError:
                self._invalid_paths.append(raw_path)
                continue
            try:
                canonical_path(path)
            except RepositoryReadError:
                continue
            if kind == 'blob' and mode in {'100644', '100755'}:
                self._entries[path] = blob
            else:
                self._unsupported.append(path)
        self._documents: dict[str, dict] = {}
        self._blob_sizes: dict[str, int] = {}

    @property
    def paths(self) -> tuple[str, ...]:
        """Safe tracked regular-file paths, without reading content."""
        return tuple(sorted(self._entries))

    @property
    def unsupported_paths(self) -> tuple[str, ...]:
        """Tracked symlink/submodule paths; content is never followed."""
        return tuple(sorted(self._unsupported))

    @property
    def invalid_paths(self) -> tuple[bytes, ...]:
        return tuple(self._invalid_paths)

    def blob_size(self, path: str) -> int:
        path = canonical_path(path)
        if path not in self._entries:
            raise RepositoryReadError('repository file missing or unsupported')
        blob = self._entries[path]
        if blob not in self._blob_sizes:
            self._blob_sizes[blob] = int(self._git('cat-file', '-s', blob))
        return self._blob_sizes[blob]

    def _git(self, *args: str) -> bytes:
        result = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(self.root), *args], capture_output=True, env=local_git_environment())
        if result.returncode:
            raise RepositoryReadError('repository revision or object unavailable')
        return result.stdout

    def _document(self, path: str, before_blob=None) -> dict:
        path = canonical_path(path)
        if path not in self._entries:
            raise RepositoryReadError(f'repository file missing or unsupported: {path}')
        if before_blob is not None: before_blob(path)
        blob = self._entries[path]
        if blob not in self._documents:
            if self.blob_size(path) > 2_000_000:
                raise RepositoryReadError('repository file too large')
            if before_blob is not None: before_blob(path)
            raw = self._git('cat-file', 'blob', blob)
            if len(raw) > 2_000_000:
                raise RepositoryReadError('repository file too large')
            try:
                text = raw.decode('utf-8')
            except UnicodeError as exc:
                raise RepositoryReadError('repository file is not UTF-8 text') from exc
            try:
                fm, body = parse_frontmatter(text)
            except RecursionError:
                raise RepositoryReadError('repository frontmatter exceeds nesting limit') from None
            self._documents[blob] = {'content': raw, 'text': text,
                'body': body, 'frontmatter': fm, 'content_sha256': hashlib.sha256(raw).hexdigest()}
        if before_blob is not None: before_blob(path)
        try:
            return deepcopy(self._documents[blob])
        except RecursionError:
            raise RepositoryReadError('repository frontmatter exceeds nesting limit') from None

    def catalogue(self, *, allowed_paths: Iterable[str] | None = None,
                  filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Metadata only; path restrictions apply before reading any blobs.

        No snippets, counts or matching information about excluded paths escape.
        Filters compare frontmatter values exactly (a list matches membership).
        """
        allowed = {canonical_path(path) for path in allowed_paths} if allowed_paths is not None else None
        rows = []
        for path in sorted(self._entries):
            if not path.endswith('.md') or (allowed is not None and path not in allowed):
                continue
            document = self._document(path)
            fm = document['frontmatter']
            if not isinstance(fm.get('page_id'), str) or not fm['page_id']:
                continue
            if any((fm.get(key) not in value if isinstance(value, (list, tuple, set))
                    else fm.get(key) != value) for key, value in (filters or {}).items()):
                continue
            rows.append({'path': path, 'page_id': fm['page_id'], 'id': fm['page_id'],
                'revision': self.revision, 'blob': self._entries[path],
                'content_digest': document['content_sha256'], 'content_sha256': document['content_sha256'],
                'frontmatter': fm, **{key: fm.get(key) for key in ('title', 'page_type', 'context', 'visibility')}})
        return rows

    # American spelling for callers that use catalog terminology.
    catalog = catalogue

    def query(self, *, allowed_paths: Iterable[str] | None = None,
              filters: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self.catalogue(allowed_paths=allowed_paths, filters=filters)
        return {'revision': self.revision, 'pages': rows,
            'selection_fingerprint': _digest({'filters': filters or {}, 'pages': rows})}

    def read(self, ref: str, section: str | None = None, field: str | None = None, *, byte_range=None, before_blob=None) -> dict[str, Any]:
        if sum(value is not None for value in (section, field, byte_range)) > 1:
            raise RepositoryReadError('content selectors are mutually exclusive')
        if byte_range is not None:
            if (not isinstance(byte_range, dict) or set(byte_range) != {'kind', 'start', 'end'}
                    or byte_range.get('kind') != 'utf8-line-bytes/v1'
                    or type(byte_range.get('start')) is not int or type(byte_range.get('end')) is not int
                    or byte_range['start'] < 0 or byte_range['end'] <= byte_range['start']
                    or byte_range['end'] > 2_000_000 or byte_range['end'] - byte_range['start'] > 65_536):
                raise RepositoryReadError('invalid byte range')
        if ref in self._entries:
            path = canonical_path(ref)
        else:
            if byte_range is not None or '/' in ref or ref.endswith('.md'):
                canonical_path(ref)
                raise RepositoryReadError(f'repository file missing or unsupported: {ref}')
            matches = [row['path'] for row in self.catalogue() if row['page_id'] == ref]
            if len(matches) != 1:
                raise RepositoryReadError(f'page identity missing or ambiguous: {ref}')
            path = matches[0]
        document = (self._document(path) if before_blob is None else
                    self._document(path, before_blob=before_blob))
        result = {**document, 'path': path, 'page_id': document['frontmatter'].get('page_id'),
            'revision': self.revision, 'blob': self._entries[path],
            'content_digest': document['content_sha256'],
            'origin': {'kind': 'git', 'revision': self.revision, 'path': path, 'blob': self._entries[path]}}
        if section is not None:
            selected = select_section(document['text'], section)
            result.update(section=selected.id, section_version=selected.version,
                text=selected.text, body=selected.text, content=selected.text.encode(), frontmatter={},
                content_digest=selected.content_digest)
        if field is not None:
            if field not in document['frontmatter']:
                raise RepositoryReadError(f'missing frontmatter field: {field}')
            value = document['frontmatter'][field]
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            result.update(field=field, value=value, text=text, body=text, content=text.encode(), frontmatter={field: value},
                content_digest=hashlib.sha256(text.encode()).hexdigest())
        if byte_range is not None:
            start, end = byte_range['start'], byte_range['end']
            raw = document['content']
            if (end > len(raw)
                    or (start != 0 and raw[start - 1:start] != b'\n')
                    or (end != len(raw) and raw[end - 1:end] != b'\n')):
                raise RepositoryReadError('invalid byte range')
            try:
                text = raw[start:end].decode('utf-8')
            except UnicodeError as exc:
                raise RepositoryReadError('invalid byte range') from exc
            result.update(byte_range=deepcopy(byte_range), page_id=None, text=text, body=text,
                content=raw[start:end], frontmatter={},
                content_digest=hashlib.sha256(raw[start:end]).hexdigest())
        return result
