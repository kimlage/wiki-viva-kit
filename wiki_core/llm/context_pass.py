"""Contextual LLM pass delegated to the agent running the repo.

Architecture: `wiki_core` (deterministic code) gathers and selects the relevant
excerpts and assembles a context PACKET (request). The agent running the repo
(Claude/Codex/Gemini) performs the deep read and writes the RESULT to the cache.
There is no embedded LLM client in Python; the intelligence lives in the agent,
via a skill.

The honesty gate lives in `source_pending()` + `validate_result()`: while there
is any chunk without a valid result and `required_context_pass` is on, the
auditor fails — no source is consolidated without the deep read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_core.llm.cache import cache_key
from wiki_core.ids import sha256_text

CONTEXT_PASS_SCHEMA_VERSION = "wiki_llm_context_pass.v4"

# cache_key is always a sha256 hex digest (wiki_core.llm.cache.cache_key) and is
# used as a FILENAME in the cache dir: anything else is rejected to block path
# traversal (e.g. "../../memorias/x") through --record-result payloads.
CACHE_KEY_RE = re.compile(r"[0-9a-f]{64}")

DEFAULT_CONTEXT_MAX_BYTES = 100_000
DEFAULT_REQUEST_MAX_BYTES = 256_000
MAX_LOCAL_REQUEST_BYTES = 2_000_000


class ContextRequestBlocked(ValueError):
    """A bounded preparation refused; callers can report it without raw inputs."""
    def __init__(self, code: str, reason: str):
        self.code = code
        super().__init__(reason)


def canonical_request_text(request: dict) -> str:
    """The exact UTF-8 representation delivered and persisted by the callers."""
    return json.dumps(request, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n"


def local_request_identity(request: dict) -> str:
    """Identify the semantic local request, excluding changing cache counters."""
    import hashlib
    if (not is_local_folder_request(request) or not isinstance(request.get('source_id'), str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', request['source_id'])):
        raise ValueError('local request identity unavailable')
    rows = request.get('chunks')
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        raise ValueError('local request identity unavailable')
    for row in rows:
        if (any(not isinstance(row.get(key), str) or not row[key] for key in ('chunk_id', 'source_id'))
                or any(not isinstance(row.get(key), str) or not CACHE_KEY_RE.fullmatch(row[key])
                       for key in ('chunk_hash_sha256', 'context_sha256', 'cache_key'))):
            raise ValueError('local request identity unavailable')
    envelope = {k: v for k, v in request.items() if k not in
                ('folder_request_id', 'byte_accounting', 'pending_llm_calls', 'cached_calls', 'chunks')}
    envelope['chunks'] = [{k: v for k, v in row.items() if k not in
                           ('result_exists', 'result_source_id', 'result_chunk_id')} for row in rows]
    return hashlib.sha256(canonical_request_text(envelope).encode('utf-8')).hexdigest()


def local_request_path(paths, request: dict) -> Path:
    import hashlib
    identity = local_request_identity(request)
    if request.get('folder_request_id') != identity:
        raise ValueError('local request identity differs')
    source = hashlib.sha256(request['source_id'].encode('utf-8')).hexdigest()
    return paths.extraction_events / f'folder-{source}-{identity}-llm-context-request.json'


def load_local_request(paths, path: Path, *, max_bytes: int = MAX_LOCAL_REQUEST_BYTES) -> dict:
    """Read one explicitly selected request; its identity does not grant access."""
    import os
    from wiki_core.context_selection import strict_json_loads
    from wiki_core.traversal import require_wiki_path
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError('local request budget unavailable')
    max_bytes = min(max_bytes, MAX_LOCAL_REQUEST_BYTES)
    candidate = Path(path)
    events = paths.extraction_events
    relative_events = events.relative_to(paths.root)
    absolute_events = Path(os.path.abspath(events))
    if candidate.parent not in (events, relative_events, absolute_events):
        raise ValueError('local request unavailable')
    # Normalize only the trusted root, not a user-selected traversal.
    candidate = events / candidate.name
    require_wiki_path(paths.root, candidate.relative_to(paths.root).as_posix())
    if not candidate.is_file() or candidate.stat().st_size > max_bytes:
        raise ValueError('local request unavailable')
    with candidate.open('rb') as stream:
        content = stream.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError('local request unavailable')
    request = strict_json_loads(content.decode('utf-8'))
    if local_request_path(paths, request) != candidate:
        raise ValueError('local request differs')
    return request


def retain_local_request(paths, request: dict) -> Path:
    """Retain the first semantic request without replacing existing work."""
    import os
    import tempfile
    from wiki_core.traversal import require_wiki_path
    text = canonical_request_text(request)
    if len(text.encode('utf-8')) > MAX_LOCAL_REQUEST_BYTES:
        raise ContextRequestBlocked('request_budget_exceeded',
            'The complete local request exceeds the 2000000 byte retention limit; choose a smaller source or stage. No chunk was truncated.')
    path = local_request_path(paths, request)
    require_wiki_path(paths.root, path.relative_to(paths.root).as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    require_wiki_path(paths.root, path.relative_to(paths.root).as_posix())
    fd, temporary = tempfile.mkstemp(prefix='.wiki-retain-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            load_local_request(paths, path)
    finally:
        os.unlink(temporary)
    return path


def request_limits(context_max_bytes=DEFAULT_CONTEXT_MAX_BYTES,
                   request_max_bytes=DEFAULT_REQUEST_MAX_BYTES) -> dict:
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
           for value in (context_max_bytes, request_max_bytes)):
        raise ContextRequestBlocked("invalid_context_budget", "Context and request byte budgets must be positive integers.")
    return {"context_max_bytes": context_max_bytes, "request_max_bytes": request_max_bytes}


def enforce_request_budget(request: dict, *, context_max_bytes=DEFAULT_CONTEXT_MAX_BYTES,
                           request_max_bytes=DEFAULT_REQUEST_MAX_BYTES) -> dict:
    limits = request_limits(context_max_bytes, request_max_bytes)
    context_bytes = len(canonical_request_text(request.get("block_context_package") or {}).encode("utf-8")) - 1
    if 'repository_context' in request:
        context_bytes += len(canonical_request_text(request['repository_context']).encode('utf-8')) - 1
    if context_bytes > context_max_bytes:
        raise ContextRequestBlocked("context_budget_exceeded", "Required context exceeds its byte budget; choose an authorized narrower stage or revise the explicit budget.")
    if request.get("request_limits", limits) != limits:
        raise ContextRequestBlocked("request_limits_changed", "Rebuild the contextual request when its explicit byte budgets change.")
    request["request_limits"] = limits
    request["byte_accounting"] = {"context_bytes": context_bytes,
        "source_text_bytes": sum(len(row["text"].encode("utf-8")) for row in request.get("chunks", [])),
        "request_bytes": 0}
    while True:
        size = len(canonical_request_text(request).encode("utf-8"))
        if request["byte_accounting"]["request_bytes"] == size:
            break
        request["byte_accounting"]["request_bytes"] = size
    if size > request_max_bytes:
        raise ContextRequestBlocked("request_budget_exceeded", "The complete request exceeds its byte budget; choose a smaller explicit source or stage, or revise the authorized budget. No chunk was truncated.")
    if is_local_folder_request(request) and size > MAX_LOCAL_REQUEST_BYTES:
        raise ContextRequestBlocked("request_budget_exceeded", "The complete local request exceeds the 2000000 byte retention limit; choose a smaller source or stage. No chunk was truncated.")
    return request


def preparation_blocker(exc: Exception, source_id: str, owner: str) -> dict:
    """Do not echo denied paths, source text, credentials or parser diagnostics."""
    from wiki_core.context_packet import blocker
    if not isinstance(exc, ContextRequestBlocked) and "byte budget" in str(exc).casefold():
        exc = ContextRequestBlocked("context_budget_exceeded", "Required context cannot fit its explicit byte budget; choose an authorized narrower stage or revise the budget.")
    if isinstance(exc, ContextRequestBlocked):
        code, reason, status = exc.code, str(exc), "denied" if exc.code.endswith("_denied") else "pending"
        required = ("Inspect possible partial local artifacts and resolve them before retrying."
                    if code == "local_persistence_partial" else
                    "Check the selected folder and index; for an auxiliary folder explicitly select its indexed ancestor."
                    if code == "local_folder_unavailable" else
                    "Install and configure the approved v4 deep-read prompt, then re-emit and read the bound request."
                    if code == "approved_prompt_migration_required"
                    else "Choose an explicit smaller source/stage or an authorized byte budget, then prepare again."
                    if code in {"context_budget_exceeded", "request_budget_exceeded", "invalid_context_budget", "retained_request_exceeds_budget"}
                    else "Ask the coordinator to stage an authorized source or resolve the current context/read scope through the supported task interface; then re-emit and read the bound request.")
    else:
        denied = "denied" in str(exc).casefold()
        code = "context_access_denied" if denied else "context_preparation_unavailable"
        reason = "Approved context is unavailable or denied; no compatibility fallback was used."
        status = "denied" if denied else "pending"
        required = "Ask the context owner/integrator to verify the current approved context, exact read scope and available inputs."
    return {"error_code": code, "blocker": blocker("prepare_context_request", "source:" + source_id,
        reason, owner, required,
        ("Possible partial local artifacts have been inspected and resolved."
         if code == "local_persistence_partial" else
         "The selected folder instructions and index are available without crossing a Git boundary."
         if code == "local_folder_unavailable" else
         "The prompt required by the selected approved route is installed and configured."
         if code == "approved_prompt_migration_required" else
         "Current approved context is readable and the complete untruncated request fits both explicit byte budgets."),
        status=status, interface="Calling harness task interface and coordinator task record")}


DEFAULT_QUADRANTS = [
    "interior_individual",
    "exterior_individual",
    "interior_collective",
    "exterior_collective",
]

RESULT_REQUIRED_KEYS = [
    "cache_key",
    "source_id",
    "chunk_id",
    "prompt_version",
    "schema_version",
    "model_profile",
    "produced_by",
    "quadrants",
    "claims",
    "decisions",
    "actions",
    "risks",
    "uncertainties",
    "relationships",
    "sensitivity",
]

PERSPECTIVE_STATUSES = {
    "extracted",
    "not_applicable",
    "pending",
    "blocked",
    "skipped_with_reason",
}

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def require_approved_prompt_version(version: str, *, folder: bool = False) -> None:
    """Reject legacy or missing prompt guidance before approved source reads."""
    path = PROMPTS_DIR / f"context_deep_read.{version}.md"
    expected = "v5" if folder else "v4"
    if version != expected or path.is_symlink() or not path.is_file():
        raise ContextRequestBlocked(
            "approved_prompt_migration_required",
            f"Approved ingestion requires the installed {expected} deep-read prompt; migrate the configured prompt version before preparing this request.",
        )


def load_prompt(name: str, version: str, *, allow_fallback: bool = True) -> str:
    path = PROMPTS_DIR / f"{name}.{version}.md"
    if allow_fallback:
        if not path.exists():
            path = PROMPTS_DIR / f"{name}.v1.md"
        if not path.exists():
            raise FileNotFoundError(f"prompt not found: {name}.{version}")
        return path.read_text(encoding="utf-8")
    # The approved path never consults v1, even if v4 disappears after validation.
    try:
        if path.is_symlink():
            raise OSError("prompt is a symlink")
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContextRequestBlocked("approved_prompt_migration_required", f"Approved ingestion requires the installed {version} deep-read prompt; restore it before preparing this request.") from exc


def result_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def read_result(cache_dir: Path, key: str) -> dict[str, object] | None:
    if not CACHE_KEY_RE.fullmatch(key):
        return None
    path = result_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def validate_result(result: dict[str, object]) -> list[str]:
    if not isinstance(result, dict):
        return ["result_not_object"]
    errors: list[str] = []
    for key in RESULT_REQUIRED_KEYS:
        if key not in result:
            errors.append(f"missing_key:{key}")
    for key in ("cache_key", "source_id", "chunk_id", "prompt_version", "schema_version", "model_profile", "produced_by"):
        if key in result and (not isinstance(result[key], str) or not result[key].strip()):
            errors.append(f"identity_invalid:{key}")
    quadrants = result.get("quadrants")
    if isinstance(quadrants, dict):
        for quadrant in DEFAULT_QUADRANTS:
            value = quadrants.get(quadrant)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"quadrant_empty:{quadrant}")
    else:
        errors.append("quadrants_not_object")
    sensitivity = result.get("sensitivity")
    if not isinstance(sensitivity, dict) or not isinstance(sensitivity.get("has_pii"), bool):
        errors.append("sensitivity_missing_has_pii")
    for field in ("claims", "decisions", "actions", "risks", "uncertainties", "relationships", "entities"):
        if field in result and not isinstance(result[field], list):
            errors.append(f"collection_not_list:{field}")
    schema_version = str(result.get("schema_version") or "")
    required_perspectives = result.get("perspectives_required") or []
    if not isinstance(required_perspectives, list) or any(not isinstance(x, str) for x in required_perspectives):
        errors.append("perspectives_required_not_list")
        required_perspectives = []
    if schema_version.endswith(".v3") or schema_version.endswith(".v4") or required_perspectives:
        perspectives = result.get("perspectives")
        if not isinstance(perspectives, dict):
            errors.append("perspectives_not_object")
        else:
            for perspective_id in required_perspectives if isinstance(required_perspectives, list) else []:
                block = perspectives.get(str(perspective_id))
                if not isinstance(block, dict):
                    errors.append(f"perspective_missing:{perspective_id}")
                    continue
                status = str(block.get("status") or "")
                if status not in PERSPECTIVE_STATUSES:
                    errors.append(f"perspective_invalid_status:{perspective_id}")
                if status in {"not_applicable", "blocked", "skipped_with_reason"}:
                    if not str(block.get("reason") or "").strip():
                        errors.append(f"perspective_missing_reason:{perspective_id}")
    return errors


def write_result(cache_dir: Path, result: dict[str, object], *, preserve_existing: bool = False,
                 request: dict | None = None, before_write=None) -> Path:
    if request is not None and is_local_folder_request(request):
        rows = request.get('chunks')
        if (not preserve_existing or not callable(before_write) or not isinstance(rows, list)
                or not any(result_matches_request(result, request, row, recording=True)
                           for row in rows if isinstance(row, dict))):
            raise ValueError('local result requires bound recording')
        before_write()
        cache_dir = result_cache_for_request(cache_dir, request)
    if preserve_existing:
        from wiki_core.repo_read import contains_access_secrets
        if contains_access_secrets(result):
            raise ValueError('access secret in selected result')
    errors = validate_result(result)
    if errors:
        raise ValueError("invalid LLM pass result: " + ", ".join(errors))
    key = str(result["cache_key"])
    if not CACHE_KEY_RE.fullmatch(key):
        raise ValueError(
            f"invalid cache_key {key!r}: expected a sha256 hex digest "
            "(64 lowercase hex chars); refusing to use it as a cache filename"
        )
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = result_path(cache_dir, key)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if preserve_existing:
        try:
            with path.open('x', encoding='utf-8') as stream:
                stream.write(payload)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
                raise ValueError('existing result unavailable; preserved') from None
            from wiki_core.context_selection import strict_json_loads
            with path.open('rb') as stream:
                existing = strict_json_loads(stream.read(2_000_001).decode('utf-8'))
            if json.dumps(existing, sort_keys=True, ensure_ascii=False, allow_nan=False) != \
                    json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False):
                raise ValueError('existing result differs; preserved') from None
    else:
        path.write_text(payload, encoding='utf-8')
    return path


def _source_hash(manifest: dict[str, object]) -> str:
    return str(manifest.get("hash_sha256") or manifest.get("source_id"))



# Only semantic inputs delivered to the reader belong in interpretation identity.
# Capture timestamps, source-wide hashes and aggregate counters do not.
_CONTEXT_FIELDS = (
    "prompt_name", "prompt", "source_context", "quadrants_required",
    "quadrant_map", "quadrant_semantics", "quadrant_boundary_rule", "root_entity",
    "input_channel", "input_stage_status", "target_pages", "perspectives_required",
    "perspectives_optional", "block_context_package", "request_limits", "source_authorization", "repository_context",
)


def context_fingerprint(request: dict, provenance: dict) -> str:
    envelope = {key: request.get(key) for key in _CONTEXT_FIELDS}
    for optional in ("request_limits", "source_authorization", "repository_context"):
        if optional not in request:  # Historical envelopes remain inspectable.
            envelope.pop(optional, None)
    envelope["provenance"] = provenance
    return sha256_text(json.dumps(envelope, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"), allow_nan=False))


def result_matches_request(result: object, request: dict, row: dict, *, recording=False) -> bool:
    """Validate the recorded interpretation, rather than file existence.

    Legacy requests remain inspectable with their original identities. They
    cannot satisfy a new contextual request. For a bound result, a stable origin
    plus unchanged semantic inputs/chunk permits reuse across source versions;
    its original source/chunk IDs remain visible as the provenance of that read.
    New recordings must name the exact emitted source and chunk.
    """
    if not isinstance(result, dict) or not isinstance(row, dict):
        return False
    key = row.get("cache_key")
    if not isinstance(key, str) or not CACHE_KEY_RE.fullmatch(key) or result.get("cache_key") != key:
        return False
    validation = dict(result)
    validation["perspectives_required"] = request.get("perspectives_required", result.get("perspectives_required", []))
    if validate_result(validation):
        return False
    for perspective in request.get("perspectives_required", []):
        if result.get("perspectives", {}).get(perspective, {}).get("status") in {"pending", "blocked"}:
            return False
    for field in ("prompt_version", "schema_version", "model_profile"):
        if request.get(field) is not None and result.get(field) != request[field]:
            return False
    bound = row.get("context_sha256")
    if (request.get("context_binding_version") == 1 or result.get("context_sha256") is not None) and bound is None:
        return False
    if bound is not None:
        if (not isinstance(row.get("text"), str)
                or sha256_text(row["text"]) != row.get("chunk_hash_sha256")):
            return False
        if (not isinstance(bound, str) or not CACHE_KEY_RE.fullmatch(bound)
                or result.get("context_sha256") != bound
                or result.get("chunk_hash_sha256") != row.get("chunk_hash_sha256")
                or context_fingerprint(request, row.get("provenance", {})) != bound
                or cache_key(str(row.get("chunk_hash_sha256")), str(request.get("prompt_version")),
                             str(request.get("schema_version")), str(request.get("model_profile")),
                             context_sha256=bound) != key):
            return False
    if recording or bound is None:
        expected_source = row.get("source_id", request.get("source_id"))
        if expected_source is not None and result.get("source_id") != expected_source:
            return False
        if row.get("chunk_id") is not None and result.get("chunk_id") != row["chunk_id"]:
            return False
    return True


def is_local_folder_request(request: object) -> bool:
    from wiki_core.input_stage import LOCAL_FOLDER_INPUT_STATUS
    return isinstance(request, dict) and request.get('input_stage_status') == LOCAL_FOLDER_INPUT_STATUS


def result_cache_for_request(cache_dir: Path, request: object) -> Path:
    """Separate selected local results; a cache path is not an access grant."""
    return Path(cache_dir) / 'local-folder' if is_local_folder_request(request) else Path(cache_dir)


def read_matching_result(cache_dir: Path, request: dict, row: dict, *, root: Path | None = None) -> dict | None:
    if is_local_folder_request(request) and root is None:
        raise ValueError('local_result_root_unavailable')
    cache_dir = result_cache_for_request(cache_dir, request)
    key = row.get("cache_key") if isinstance(row, dict) else None
    if root is not None and isinstance(key, str) and CACHE_KEY_RE.fullmatch(key):
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(root, files=(result_path(cache_dir, key),))
    result = read_result(cache_dir, key) if isinstance(key, str) else None
    return result if result_matches_request(result, request, row) else None


def local_entry_selection(root: Path, folder: str | None, index_path: str | None, *,
                          cwd: Path, approved_revision: str | None, policy_context: str | None):
    """Resolve explicit selection or a nested cwd; no access is granted."""
    from wiki_core.context_policy import safe_path
    from wiki_core.repo_read import contains_access_secrets
    if contains_access_secrets([folder, index_path]):
        raise ValueError('context selection unavailable')
    if approved_revision is not None or policy_context is not None:
        if folder is not None or index_path is not None:
            raise ValueError('folder selection cannot replace an approved policy')
        return None, None
    if folder is None:
        try:
            relative = Path(cwd).resolve(strict=True).relative_to(Path(root).resolve(strict=True))
        except ValueError:
            relative = None
        if relative is not None and relative.parts:
            folder = relative.as_posix()
        elif index_path is not None:
            folder = '.'
    if folder is not None:
        folder = safe_path(folder, allow_root=True)
    if index_path is not None:
        index_path = safe_path(index_path)
    return folder, index_path


def validate_local_entry_source(root: Path, source: str) -> str:
    """Validate an explicit local file without crossing wiki Git boundaries."""
    from urllib.parse import urlsplit
    from wiki_core.repo_read import contains_access_secrets
    from wiki_core.traversal import require_wiki_path
    if not isinstance(source, str) or contains_access_secrets(source):
        raise ValueError('source selection unavailable')
    if urlsplit(source).scheme in ('http', 'https'):
        return source
    trusted_root = Path(root).resolve(strict=True)
    candidate = Path(source).expanduser()
    if not candidate.is_absolute():
        candidate = trusted_root / candidate
    try:
        relative = candidate.relative_to(trusted_root).as_posix()
    except ValueError:
        raise ValueError('source outside wiki requires separately authorized selection') from None
    selected = require_wiki_path(trusted_root, relative)
    if not selected.is_file():
        raise ValueError('selected source unavailable')
    return str(selected)


def _folder_documents(root: Path, folder: str, index_path: str | None, max_bytes: int) -> list[dict]:
    """Read a physical instruction chain and one local index, without grants."""
    from wiki_core.context_policy import safe_path, within
    from wiki_core.detectors import scan_text
    from wiki_core.repo_read import contains_access_secrets
    from wiki_core.traversal import require_wiki_path

    if contains_access_secrets([folder, index_path]):
        raise ValueError('context selection unavailable')
    folder = safe_path(folder, allow_root=True)
    directory = require_wiki_path(root, folder)
    if not directory.is_dir():
        raise ValueError('selected context folder unavailable')
    if index_path is None and folder == '.':
        raise ValueError('root context requires an explicit index')
    if index_path is not None:
        index_path = safe_path(index_path)
    parts = [] if folder == '.' else folder.split('/')
    directories = ['.'] + ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]
    documents = []
    instruction_dirs = []
    remaining = max_bytes

    def read(ref):
        nonlocal remaining
        path = require_wiki_path(root, ref)
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError('context document unavailable')
        with path.open('rb') as stream:
            raw = stream.read(remaining + 1)
        if len(raw) > remaining:
            raise ValueError('context document budget exceeded')
        text = raw.decode('utf-8')
        if contains_access_secrets(text) or any(item.category == 'secret' for item in scan_text(text)):
            raise ValueError('access secret in context document')
        return text, len(raw)

    for directory_ref in directories:
        prefix = '' if directory_ref == '.' else directory_ref + '/'
        selected = None
        for name in ('AGENTS.override.md', 'AGENTS.md'):
            ref = prefix + name
            item = read(ref)
            if item is not None and item[0].strip():
                selected = (ref, *item)
                break
        if selected is not None:
            ref, text, size = selected
            instruction_dirs.append(directory_ref)
            remaining -= size
            documents.append({'path': ref, 'page_id': None, 'text': text,
                              'content_sha256': sha256_text(text), 'origin': 'working_tree'})
    if not documents:
        raise ValueError('context instructions unavailable')
    # A folder is an implicit context only when it has both its own
    # instructions and an index. An auxiliary directory can contribute
    # instructions without becoming the indexed context.
    def nearest_index():
        for directory_ref in reversed(instruction_dirs):
            if directory_ref == '.':
                continue  # Root entry needs an explicitly selected index.
            for name in ('index.md', 'README.md'):
                ref = directory_ref + '/' + name
                path = require_wiki_path(root, ref)
                if path.exists():
                    if not path.is_file():
                        raise ValueError('selected context index unavailable')
                    return ref
        raise ValueError('selected context index unavailable')

    if index_path is None:
        index_path = nearest_index()
    else:
        index_directory = Path(index_path).parent.as_posix()
        if index_directory not in instruction_dirs or not within(folder, index_directory):
            raise ValueError('selected index is not in a qualified context')
    if not within(index_path, folder):
        # An ancestor index is valid only as the current nearest context, or
        # as an explicitly selected root index. Recheck on every reconstruction.
        is_root_index = '/' not in index_path and '.' in instruction_dirs
        if not is_root_index and index_path != nearest_index():
            raise ValueError('selected index is outside the context folder')
    if any(item['path'] == index_path for item in documents):
        raise ValueError('index must be distinct from instructions')
    selected_index = read(index_path)
    if selected_index is None or not selected_index[0].strip():
        raise ValueError('selected context index unavailable')
    text, _size = selected_index
    documents.append({'path': index_path, 'page_id': None, 'text': text,
                      'content_sha256': sha256_text(text), 'origin': 'working_tree'})
    return documents


def _repo_selections(root: Path, selections, expected_documents=None):
    """Validate host-supplied selections before opening any repository body."""
    from wiki_core.repo_read import contains_access_secrets, remote_identity
    from wiki_core.repository_reader import canonical_path
    if selections is None:
        selections = ()
    if not isinstance(selections, (list, tuple)) or len(selections) > 16 or contains_access_secrets(selections):
        raise ValueError('repository selection unavailable')
    selected = []
    for item in selections:
        if (not isinstance(item, (list, tuple)) or len(item) != 4
                or any(not isinstance(value, str) or not value for value in item)):
            raise ValueError('repository selection unavailable')
        repo_root, identity, revision, path = item
        if (not Path(repo_root).is_absolute() or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
                or canonical_path(path) != path or remote_identity('https://' + identity)[0] != identity):
            raise ValueError('repository selection unavailable')
        resolved = Path(repo_root).resolve(strict=True)
        if not resolved.is_dir() or resolved == Path(root).resolve() or contains_access_secrets(str(resolved)):
            raise ValueError('repository selection unavailable')
        selected.append((str(resolved), identity, revision, path))
    if len(set(selected)) != len(selected):
        raise ValueError('repository selection unavailable')
    if expected_documents is not None:
        try:
            expected = [(row['repository_root'], row['repository_read']['repository']['identity'],
                         row['repository_read']['revision'], row['repository_read']['path'])
                        for row in expected_documents if row.get('origin') == 'independent_git']
        except (AttributeError, KeyError, TypeError):
            raise ValueError('repository selection unavailable') from None
        if selected != expected:
            raise ValueError('repository selection changed')
    return selected


def _repo_documents(selections, max_bytes):
    from wiki_core.repo_read import _prepare_repo_read, _read_prepared_repo
    documents = []
    if selections and max_bytes <= 0:
        raise ValueError('context document budget exceeded')
    prepared = [_prepare_repo_read(Path(repo_root), identity, revision, path,
                                   max_bytes=min(max_bytes, 2_000_000))
                for repo_root, identity, revision, path in selections]
    if sum(item[4] for item in prepared) > max_bytes:
        raise ValueError('context document budget exceeded')
    for (repo_root, _identity, _revision, path), item in zip(selections, prepared):
        receipt = _read_prepared_repo(item)
        text = receipt.pop('text')
        documents.append({'path': path, 'page_id': None, 'text': text,
            'content_sha256': receipt['content_sha256'], 'origin': 'independent_git',
            'repository_root': repo_root, 'repository_read': receipt})
    return documents


def ingestion_block_context(root: Path, config, input_context: dict,
                            perspectives_required: list[str], *,
                            approved_revision: str | None = None,
                            policy_context: str | None = None,
                            task_id: str = "source-context-pass",
                            context_max_bytes: int = DEFAULT_CONTEXT_MAX_BYTES,
                            content_revision: str = "HEAD",
                            entry_folder: str | None = None,
                            entry_index: str | None = None,
                            repo_selections=None, expected_documents=None) -> dict:
    """Construct the real contextual inputs at both production call sites.

    This working-tree adapter claims no authorization or immutable revision.
    New approved ingestion must use the host-bound folder source stage.
    """
    if approved_revision is not None or policy_context is not None:
        raise ContextRequestBlocked('v1_ingestion_retired',
            'New approved ingestion through the v1 entry is retired. Use the folder source-stage with a trusted host binding; historical artifacts remain unchanged.')
    if entry_index is not None and entry_folder is None:
        raise ValueError('index requires a context folder')
    if repo_selections is not None and entry_folder is None:
        raise ValueError('repository selection requires a context folder')
    if entry_folder is not None:
        from wiki_core.context_policy import safe_path
        repos = _repo_selections(root, repo_selections, expected_documents)
        selected = _folder_documents(root, entry_folder, entry_index, context_max_bytes)
        selected_index = selected[-1]['path']
        remaining = context_max_bytes - sum(len(row['text'].encode('utf-8')) for row in selected)
        selected.extend(_repo_documents(repos, remaining))
        return {'schema_version': 'wiki_block_stack.v1', 'center': None, 'stack': [], 'lenses': [],
                'write_policy': 'proposal_branch_only', 'target_obligations': [],
                'policy_mode': 'legacy_working_tree_compatibility', 'policy_enforced': False,
                'entry_folder': safe_path(entry_folder, allow_root=True), 'entry_index': selected_index,
                'documents': selected,
                'unresolved_context_refs': ['source configuration not selected', 'linked sources not inspected',
                                            'other context not inspected']}
    from wiki_core.template_blocks import load_block_world, block_context_package
    from wiki_core.repository_reader import canonical_path
    from wiki_core.detectors import scan_text
    world = load_block_world(root, config)
    root_info = input_context.get("root_entity") or {}
    anchor = world.by_id.get(root_info.get("page_id")) or world.by_path.get(root_info.get("path"))
    package = block_context_package(world, anchor) if anchor else {
        "schema_version": "wiki_block_stack.v1", "center": None, "stack": [], "lenses": [],
        "write_policy": "proposal_branch_only", "target_obligations": []}
    refs = ["AGENTS.md"]
    refs.extend(path for path in config.audit.get("core_pages", [])
                if world.by_path.get(path, {}).get("page_type") == "operational_rule")
    if anchor:
        refs.append(anchor["path"])
    refs.extend(str((input_context.get(name) or {}).get("path")) for name in ("input_channel", "source_config") if (input_context.get(name) or {}).get("path"))
    refs.extend(perspectives_required)
    documents = []
    unresolved = []
    seen = set()
    for ref in refs:
        page = world.by_id.get(ref) or world.by_path.get(ref)
        path = page["path"] if page else ref
        canonical_path(path)
        target = root / path
        if not target.is_file():
            unresolved.append(ref)
            continue
        if path in seen:
            continue
        seen.add(path)
        cursor = root
        for part in Path(path).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("symlink context paths are not supported")
        text = target.read_text(encoding="utf-8")
        if any(f.category == "secret" for f in scan_text(text)):
            raise ValueError("access secret in contextual input")
        documents.append({"path": path, "page_id": page["id"] if page else None,
            "text": text, "content_sha256": sha256_text(text), "origin": "working_tree"})
    package.update(policy_mode="legacy_working_tree_compatibility", policy_enforced=False,
                   documents=documents, unresolved_context_refs=unresolved)
    return package


def build_context_request(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    *,
    context_root: Path | None = None,
    prompt_name: str = "context_deep_read",
    quadrants: list[str] | None = None,
    perspectives_required: list[str] | None = None,
    perspectives_optional: list[str] | None = None,
    root_entity: dict[str, object] | None = None,
    input_channel: dict[str, object] | None = None,
    quadrant_map: dict[str, object] | None = None,
    quadrant_semantics: dict[str, object] | None = None,
    quadrant_boundary_rule: str | None = None,
    target_pages: list[str] | None = None,
    input_stage_status: str | None = None,
    block_context_package: dict[str, object] | None = None,
    context_max_bytes: int = DEFAULT_CONTEXT_MAX_BYTES,
    request_max_bytes: int = DEFAULT_REQUEST_MAX_BYTES,
    source_authorization: dict | None = None,
    repository_context: dict | None = None,
    cache_root: Path | None = None,
) -> dict[str, object]:
    """Assemble the packet that the repo agent executes. Includes the chunk text,
    the versioned prompt, the output schema and the per-chunk cache status.

    ``block_context_package`` (v2, read-only) carries the resolved block stack of
    the ingestion center — the combined lenses (quadrants + any perspective
    bundle), each with its local label, canonical operational test and referenced
    perspective page, plus the write policy and target obligations. The agent is
    asked to honor it; nothing is written outside the PR gate."""
    quadrants = quadrants or DEFAULT_QUADRANTS
    perspectives_required = perspectives_required or []
    perspectives_optional = perspectives_optional or []
    target_pages = target_pages or []
    source_hash = _source_hash(manifest)  # packet metadata (not part of the cache_key)
    approved = ((block_context_package or {}).get("schema_version") == "wiki.task-context/v1"
                or source_authorization is not None)
    if approved:
        if prompt_name != "context_deep_read":
            raise ContextRequestBlocked("approved_prompt_migration_required", "Approved ingestion requires the installed deep-read prompt for the selected route.")
        if (block_context_package or {}).get('authority_format') == 'folder':
            require_approved_prompt_version(prompt_version, folder=True)
        else:
            require_approved_prompt_version(prompt_version)
    prompt_text = load_prompt(prompt_name, prompt_version, allow_fallback=not approved)
    result_required_keys = [*RESULT_REQUIRED_KEYS, "context_sha256", "chunk_hash_sha256"]
    if perspectives_required:
        result_required_keys.append("perspectives")
    request = {
        "kind": "llm_context_request",
        "context_binding_version": 1,
        "request_limits": request_limits(context_max_bytes, request_max_bytes),
        "source_context": manifest.get("context", ""),
        "schema_version": schema_version,
        "context_pass_schema_version": CONTEXT_PASS_SCHEMA_VERSION,
        "source_id": manifest.get("source_id"),
        "source_hash_sha256": source_hash,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "model_profile": model_profile,
        "quadrants_required": quadrants,
        "quadrant_map": quadrant_map or {},
        "quadrant_semantics": quadrant_semantics or {},
        "quadrant_boundary_rule": quadrant_boundary_rule or "",
        "root_entity": root_entity or {},
        "input_channel": input_channel or {},
        "input_stage_status": input_stage_status or "",
        "target_pages": target_pages,
        "perspectives_required": perspectives_required,
        "perspectives_optional": perspectives_optional,
        "block_context_package": block_context_package or {},
        "result_required_keys": result_required_keys,
        "prompt": prompt_text,
        "chunks": [],
        "pending_llm_calls": 0,
        "cached_calls": 0,
        "instructions": (
            "The agent running the repo performs the deep read of each chunk with "
            "result_exists=false and produces an object matching result_required_keys "
            "(cache_key = the chunk's). "
            + ("Record with the same explicit authorized source, approved revision, "
               "policy context and byte limits using the approved command in the prompt. "
               if approved else
               "Record via the working-tree compatibility command in the prompt. ")
            + ("Use the selected repository_context as explicit interpretation evidence; "
               "do not infer that any unselected repository files were read. "
               if repository_context is not None else "")
            + "Never write canonical memory directly."
        ),
    }

    if source_authorization is not None:
        request["source_authorization"] = source_authorization
    if repository_context is not None:
        request["repository_context"] = repository_context

    for chunk in chunks:
        source_id = chunk.get("source_id", manifest.get("source_id"))
        origin = chunk.get("source_origin") or manifest.get("source_origin") or {}
        origin_id = origin.get("id") if isinstance(origin, dict) else None
        # Missing origin is not guessed from a basename, URL or account.
        provenance = {"origin_id": origin_id} if origin_id else {"source_id": source_id}
        for field in ("account_id", "provider_account_id"):
            if chunk.get(field, manifest.get(field)) is not None:
                provenance[field] = chunk.get(field, manifest.get(field))
        if chunk.get("context") is not None:
            provenance["context"] = chunk["context"]
        bound = context_fingerprint(request, provenance)
        chunk_hash = str(chunk["hash_sha256"])
        if not isinstance(chunk.get("text"), str) or sha256_text(chunk["text"]) != chunk_hash:
            raise ValueError("context_chunk_hash_mismatch: text must match its digest")
        row = {
            "chunk_id": chunk["chunk_id"], "source_id": source_id,
            "chunk_hash_sha256": chunk_hash, "context_sha256": bound,
            "provenance": provenance,
            "cache_key": cache_key(chunk_hash, prompt_version, schema_version,
                                   model_profile, context_sha256=bound),
            "token_estimate": chunk.get("token_estimate"), "text": chunk.get("text", ""),
        }
        if cache_root is not None:
            from wiki_core.traversal import require_wiki_path
            selected_cache = result_cache_for_request(cache_dir, request)
            require_wiki_path(cache_root, (selected_cache / f"{row['cache_key']}.json").relative_to(cache_root).as_posix())
        existing = read_matching_result(cache_dir, request, row, root=context_root)
        row["result_exists"] = existing is not None
        if existing is not None:
            row["result_source_id"] = existing.get("source_id")
            row["result_chunk_id"] = existing.get("chunk_id")
        request["chunks"].append(row)
        request["cached_calls" if existing is not None else "pending_llm_calls"] += 1
    request["instructions"] += " Copy context_sha256 and chunk_hash_sha256 from the chunk; retain its exact source_id and chunk_id."
    enforce_request_budget(request, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)
    if is_local_folder_request(request):
        request['folder_request_id'] = local_request_identity(request)
    return enforce_request_budget(request, context_max_bytes=context_max_bytes, request_max_bytes=request_max_bytes)


def source_pending(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    **context_inputs,
) -> int:
    """Use the exact same request identity and validation as packet generation."""
    return int(build_context_request(manifest, chunks, cache_dir, prompt_version,
                                    schema_version, model_profile, **context_inputs)["pending_llm_calls"])
