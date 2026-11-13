"""Explicit read from an independent Git repository, without network access.

The verified remote name identifies the configured Git target, not an
independently authenticated service or an access grant. The caller remains
responsible for effective permissions and authorized disclosure.
"""
from __future__ import annotations

import re
import html
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from wiki_core.detectors import contains_secret_structure
from wiki_core.git_env import local_git_environment, local_git_executable
from wiki_core.repository_reader import RepositoryReader, RepositoryReadError, canonical_path


class RepoReadError(ValueError):
    pass


def _git(root: Path, *args: str) -> str:
    result = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(root), *args], capture_output=True, env=local_git_environment())
    if result.returncode:
        raise RepoReadError('git_repository_or_remote_unavailable')
    try:
        return result.stdout.decode('utf-8').strip()
    except UnicodeError as exc:
        raise RepoReadError('git_output_invalid_encoding') from exc


class _LocalRepositoryReader(RepositoryReader):
    """Disable lazy promisor fetches, replacement refs and environment redirection."""
    def __init__(self, root, revision, *, exact_path=None, before_access=None):
        self._before_access = before_access
        self._size_cache = {}
        super().__init__(root, revision, exact_path=exact_path, before_tree=before_access)

    def blob_size(self, path):
        # A pinned Git object ID has immutable size; actual body I/O still
        # performs the live host/policy guard in _git immediately beforehand.
        if path not in self._size_cache:
            self._size_cache[path] = super().blob_size(path)
        return self._size_cache[path]

    def _git(self, *args: str) -> bytes:
        if self._before_access is not None: self._before_access()
        result = subprocess.run([local_git_executable(), '--no-lazy-fetch', '-C', str(self.root), *args], capture_output=True,
                                env=local_git_environment())
        if result.returncode:
            raise RepositoryReadError('repository revision or object unavailable')
        return result.stdout


def remote_identity(remote: str) -> tuple[str, str]:
    """Return credential-free host/path identity and transport; never echo input."""
    if not isinstance(remote, str) or not remote or any(ord(c) < 33 or ord(c) == 127 for c in remote):
        raise RepoReadError('remote_invalid_or_unsafe')
    if contains_secret_structure(remote):
        raise RepoReadError('remote_invalid_or_unsafe')
    if '://' in remote:
        try:
            parsed = urlsplit(remote)
            host = parsed.hostname
            port = parsed.port
            if parsed.scheme not in ('https', 'ssh') or not host or parsed.query or parsed.fragment:
                raise ValueError()
            if (parsed.scheme == 'https' and parsed.username is not None) or parsed.password is not None:
                raise ValueError()
            if parsed.scheme == 'ssh' and parsed.username not in (None, 'git'):
                raise ValueError()
            transport = parsed.scheme
            path = parsed.path.lstrip('/')
        except ValueError as exc:
            raise RepoReadError('remote_invalid_or_unsafe') from exc
    else:
        match = re.fullmatch(r'(?:git@)?([A-Za-z0-9.-]+):([A-Za-z0-9._/-]+)', remote)
        if not match:
            raise RepoReadError('remote_unsupported_or_unsafe')
        host, path, port, transport = match.group(1), match.group(2), None, 'ssh'
    if not re.fullmatch(r'[A-Za-z0-9.-]+', host) or not re.fullmatch(r'[A-Za-z0-9._/-]+', path):
        raise RepoReadError('remote_invalid_or_unsafe')
    parts = path.removesuffix('.git').split('/')
    if len(parts) < 2 or any(not part or part in ('.', '..') for part in parts):
        raise RepoReadError('remote_invalid_or_unsafe')
    identity = host.lower() + (f':{port}' if port is not None else '') + '/' + '/'.join(parts)
    if contains_secret_structure(identity):
        raise RepoReadError('remote_invalid_or_unsafe')
    return identity, transport


# Userinfo ends at the authority boundary; an email in a path or search query
# is not URL userinfo. Scan each decoding layer so escaped delimiters inside
# actual userinfo do not hide it when the whole URL is itself encoded.
_CREDENTIAL_URL = re.compile(r'(?i)\b(?:https?|ssh)://[^/\s<>"\'?#]+@')
_CREDENTIAL_QUERY = re.compile(
    r'(?i)[?&](?:[a-z0-9_-]*(?:signature|credential|token|secret|password|passwd|authorization|api[_-]?key)'
    r'|x-goog-[a-z0-9_-]+|x-amz-[a-z0-9_-]+|sig|code|auth|key)='
)
_MAX_BLOB_BYTES = 2_000_000


def _secret_check_decodings(text: str):
    # Providers commonly encode signed query keys more than once or use HTML
    # entities in Markdown. If decoding never stabilizes, fail closed.
    for _ in range(8):
        yield text
        decoded = html.unescape(unquote(text))
        if decoded == text:
            return
        text = decoded
    raise RepoReadError('selected_content_contains_access_secrets')


def contains_access_secrets(value: object) -> bool:
    """Conservatively detect secrets and encoded access-bearing URLs in values."""
    if contains_secret_structure(value):
        return True
    pending = [value]
    seen = set()
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            for decoded in _secret_check_decodings(item):
                if contains_secret_structure(decoded) or _CREDENTIAL_URL.search(decoded) or _CREDENTIAL_QUERY.search(decoded):
                    return True
        elif isinstance(item, dict):
            if id(item) in seen:
                continue
            seen.add(id(item))
            pending.extend(item.keys()); pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            if id(item) in seen:
                continue
            seen.add(id(item))
            pending.extend(item)
    return False


def _prepare_repo_read(root: Path, expected_identity: str, revision: str, path: str, *, max_bytes: int, before_access=None):
    """Validate repository metadata and blob size before opening its body."""
    if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_BLOB_BYTES:
        raise RepoReadError('invalid_repository_byte_limit')
    if before_access is not None: before_access()
    root = Path(root).expanduser()
    if not root.is_dir():
        raise RepoReadError('repository_missing')
    root = root.resolve()
    try:
        if before_access is not None: before_access()
        actual_root = Path(_git(root, 'rev-parse', '--show-toplevel')).resolve()
    except RepoReadError as exc:
        raise RepoReadError('git_repository_unavailable') from exc
    if actual_root != root:
        raise RepoReadError('repository_root_mismatch')
    try:
        if before_access is not None: before_access()
        remotes = _git(root, 'remote', 'get-url', '--all', 'origin').splitlines()
    except RepoReadError as exc:
        raise RepoReadError('origin_remote_unavailable') from exc
    if len(remotes) != 1:
        raise RepoReadError('origin_remote_ambiguous')
    identity, transport = remote_identity(remotes[0])
    if not isinstance(expected_identity, str) or identity != expected_identity:
        raise RepoReadError('repository_identity_mismatch')
    try:
        normalized = canonical_path(path)
        reader = _LocalRepositoryReader(root, revision, exact_path=normalized, before_access=before_access)
        if normalized not in reader.paths:
            raise RepoReadError('repository_path_missing_or_unsupported')
        size = reader.blob_size(normalized)
        if size > max_bytes:
            raise RepoReadError('repository_file_too_large')
    except RepositoryReadError as exc:
        raise RepoReadError('repository_revision_or_path_unavailable') from exc
    return reader, normalized, identity, transport, size


def _read_prepared_repo(prepared, *, section=None, field=None):
    reader, normalized, identity, transport, _size = prepared
    try:
        item = reader.read(normalized, section=section, field=field)
    except RepositoryReadError as exc:
        raise RepoReadError('repository_revision_or_path_unavailable') from exc
    result = {
        'schema_version': 'wiki.independent-repo-read/v1',
        'repository': {'identity': identity, 'remote_name': 'origin', 'transport': transport,
                       'identity_evidence': 'configured_origin_not_remote_authentication'},
        'revision': item['revision'], 'path': item['path'], 'blob': item['blob'],
        'document_sha256': item['content_sha256'], 'content_sha256': item['content_digest'],
        'section': section, 'field': field, 'text': item['text'],
        'access': 'caller_authorization_required; no grant or transmission',
    }
    if contains_access_secrets(result):
        raise RepoReadError('selected_content_contains_access_secrets')
    if reader._before_access is not None: reader._before_access()
    return result


def read_independent_repo(root: Path, expected_identity: str, revision: str, path: str,
                          *, section: str | None = None, field: str | None = None,
                          max_bytes: int = _MAX_BLOB_BYTES) -> dict:
    """Read one exact Git path from the selected root and immutable revision."""
    prepared = _prepare_repo_read(root, expected_identity, revision, path, max_bytes=max_bytes)
    return _read_prepared_repo(prepared, section=section, field=field)
