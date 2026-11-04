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


class ContextRequestBlocked(ValueError):
    """A bounded preparation refused; callers can report it without raw inputs."""
    def __init__(self, code: str, reason: str):
        self.code = code
        super().__init__(reason)


def canonical_request_text(request: dict) -> str:
    """The exact UTF-8 representation delivered and persisted by the callers."""
    return json.dumps(request, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n"


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
    if "independent_repo_content" in request:
        context_bytes += len(canonical_request_text(request["independent_repo_content"]).encode("utf-8"))
    if "independent_repo_additional_content" in request:
        context_bytes += len(canonical_request_text(request["independent_repo_additional_content"]).encode("utf-8"))
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
    return request


def preparation_blocker(exc: Exception, source_id: str, owner: str) -> dict:
    """Do not echo denied paths, source text, credentials or parser diagnostics."""
    from wiki_core.context_packet import blocker
    if not isinstance(exc, ContextRequestBlocked) and "byte budget" in str(exc).casefold():
        exc = ContextRequestBlocked("context_budget_exceeded", "Required context cannot fit its explicit byte budget; choose an authorized narrower stage or revise the budget.")
    if isinstance(exc, ContextRequestBlocked):
        code, reason, status = exc.code, str(exc), "denied" if exc.code.endswith("_denied") else "pending"
        required = ("Install and configure the approved v4 deep-read prompt, then re-emit and read the bound request."
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
        ("The v4 deep-read prompt is installed and configured for approved requests."
         if code == "approved_prompt_migration_required" else
         "Current approved context is readable and the complete untruncated request fits both explicit byte budgets."),
        status=status, interface="Calling harness task interface and coordinator task record")}


def authorize_ingestion_source(root: Path, source: str, approved_revision: str | None,
                               policy_context: str | None) -> dict:
    """Authorize a literal staged source before any stat, extraction or catalog."""
    import hashlib
    from urllib.parse import urlsplit
    from wiki_core.context_policy import load_policy
    from wiki_core.repository_reader import RepositoryReader, canonical_path
    if not approved_revision or not policy_context:
        raise ContextRequestBlocked("approved_source_context_required", "Approved ingestion requires a current approved revision and explicit policy context.")
    root = Path(root).resolve()
    policy = load_policy(root, approved_revision)
    policy.lineage(policy_context)
    candidate = Path(source).expanduser()
    if urlsplit(source).scheme and not candidate.is_absolute():
        raise ContextRequestBlocked("source_staging_required", "External sources require authorized adapter/staging evidence; this caller accepts only an explicitly staged repository-local source.")
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        ref = canonical_path(candidate.relative_to(root).as_posix())
    except ValueError as exc:
        raise ContextRequestBlocked("source_staging_required", "Stage the source inside an explicitly approved repository read scope before ingestion.") from exc
    producer = policy.owner_of(ref)
    if policy.connection(producer, policy_context, ref, "interpretation", "source") != "approved":
        raise ContextRequestBlocked("source_read_denied", "The requested source has no current exact read authorization; no source content or catalog was read.")
    cursor = root
    for part in Path(ref).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ContextRequestBlocked("unsafe_source_path", "A staged source must be a literal regular file without symlink traversal.")
    if not candidate.is_file():
        raise ContextRequestBlocked("source_staging_required", "The authorized staged source is unavailable; restore or stage it through the coordinator's supported interface.")
    def source_hash():
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    return {"root": root, "path": candidate, "ref": ref, "policy": policy,
        "context": policy_context, "hash_sha256": source_hash(),
        "reader": RepositoryReader(root, "HEAD"),
        "authorization": {"ref": ref, "producer": producer, "context_id": policy_context,
            "policy_revision": policy.policy_revision, "use": "interpretation", "classification": "source"}}


def revalidate_ingestion_source(guard: dict, *, captured_hash: str | None = None) -> None:
    """Revocation/hash changes stop the next persistence/delivery boundary."""
    if guard.get("folder_selection") is not None:
        from wiki_core.folder_ingestion_v2 import authorize_folder_ingestion_source
        current = authorize_folder_ingestion_source(guard["root"], str(guard["path"]),
            guard["policy"].policy_revision, guard["folder_selection"],
            context_max_bytes=guard["context_max_bytes"])
    else:
        current = authorize_ingestion_source(guard["root"], str(guard["path"]),
            guard["policy"].policy_revision, guard["context"])
    if (current["hash_sha256"] != guard["hash_sha256"]
            or current.get("independent_repo_content") != guard.get("independent_repo_content")
            or current.get("independent_repo_additional_content") != guard.get("independent_repo_additional_content")
            or current["authorization"].get("independent_repo_read") != guard["authorization"].get("independent_repo_read")
            or current["authorization"].get("independent_repo_additional_reads") != guard["authorization"].get("independent_repo_additional_reads")
            or (captured_hash is not None and captured_hash != guard["hash_sha256"])):
        raise ContextRequestBlocked("source_changed", "The staged source changed while preparation was in progress; revalidate and recapture the same task before continuing.")


def approved_ingestion_inputs(root, config, guard, *, root_entity_ref=None, omit_root_entity=False):
    """Task-local root/channel/config metadata from the pinned authorized readset.

    This replaces the global input-stage compiler in approved ingestion; it
    never loads the generated input-stage body as mandatory task context.
    """
    from wiki_core.frontmatter import list_values
    from wiki_core.input_stage import (_root_payload, _channel_payload,
        _resolved_perspectives, _quadrant_semantics, _quadrant_boundary_rule)
    from wiki_core.quadrants import DEFAULT_QUADRANT_MAP
    policy, reader, context = guard["policy"], guard["reader"], guard["context"]
    def allowed(ref, classification="context"):
        return policy.connection(policy.owner_of(ref), context, ref, "interpretation", classification) == "approved"
    def read_page(ref, classification="context"):
        from wiki_core.repository_reader import canonical_path
        ref = canonical_path(ref)
        if not allowed(ref, classification):
            raise ContextRequestBlocked("context_read_denied", "A required context input lacks current exact authorization.")
        if ref not in reader.paths:
            raise ContextRequestBlocked("context_input_unavailable", "An explicit context path is unavailable at the selected revision; no broader lookup was attempted.")
        document = reader.read(ref)
        fm = document["frontmatter"]
        return {"path": ref, "page_id": fm.get("page_id"), "page_type": fm.get("page_type"),
            "title": str(fm.get("title") or fm.get("page_id") or ref), "context": str(fm.get("context") or ""), "values": fm}
    if root_entity_ref is not None and omit_root_entity:
        raise ContextRequestBlocked("invalid_root_selection", "Select a business root or explicitly omit it; both cannot apply.")
    root_ref = None if omit_root_entity else root_entity_ref if root_entity_ref is not None else (config.root_entity or {}).get("page")
    root_page = read_page(root_ref) if root_ref else None
    if root_page and (not root_page["page_id"] or not root_page["page_type"] or
                      (root_entity_ref is None and root_page["page_type"] != "root_entity")):
        raise ContextRequestBlocked("root_context_invalid", "The explicitly configured root entity is invalid; no global fallback was selected.")
    root_config = config
    if root_entity_ref is not None and root_page:
        from dataclasses import replace
        root_config = replace(config, root_entity={"page": root_ref,
            "entity_type": str(root_page["values"].get("root_entity_type") or root_page["page_type"]),
            "perspective_bundle": {"required": [], "optional": []}, "input_stage_page": ""})
    root_entity = _root_payload(root_page, root_config) if root_page else None
    source_page_ref = guard.get("canonical_source_ref") or guard["ref"]
    source_page = read_page(source_page_ref, "source") if source_page_ref in reader.paths and source_page_ref.endswith(".md") else None
    source_config = None
    config_ref = (source_page or {}).get("values", {}).get("config_ref")
    if config_ref:
        page = read_page(str(config_ref)); fm = page["values"]
        if fm.get("page_type") != "source_config":
            raise ContextRequestBlocked("source_config_invalid", "The explicitly selected source configuration is invalid.")
        source_config = {"path": page["path"], "page_id": page["page_id"],
            **{key: list_values(fm.get(key)) for key in ("perspectives_required", "perspectives_optional", "perspectives_skip_with_reason", "process_refs", "target_pages", "quadrants")},
            "input_channel_ref": str(fm.get("input_channel_ref") or "")}
    channel_ref = (source_config or {}).get("input_channel_ref") or (source_page or {}).get("values", {}).get("input_channel_ref")
    channel = None
    if channel_ref:
        if channel_ref in reader.paths:
            page = read_page(channel_ref)
            if page["page_type"] != "input_channel":
                raise ContextRequestBlocked("input_channel_invalid", "The explicitly selected input channel is invalid.")
            channel = _channel_payload(page)
        else:
            paths = [path for path in reader.paths if policy.permits(context, "read", path) and policy.owner_of(path) == context]
            matches = [row["path"] for row in reader.catalogue(allowed_paths=paths, filters={"page_type": "input_channel"}) if row["page_id"] == channel_ref]
            if len(matches) != 1:
                raise ContextRequestBlocked("input_channel_unavailable", "The selected input channel is missing or ambiguous within the authorized context.")
            channel = _channel_payload(read_page(matches[0]))
    resolved = _resolved_perspectives(root_entity, channel, source_config)
    targets = list(dict.fromkeys([ref for ref in [(root_entity or {}).get("path"), *(channel or {}).get("target_pages", []), *(source_config or {}).get("target_pages", [])] if ref]))
    if any(not allowed(ref) for ref in targets):
        raise ContextRequestBlocked("context_read_denied", "A required target reference lacks current exact authorization.")
    return source_config, {"root_entity": root_entity, "input_channel": channel, "source_config": source_config,
        "quadrant_map": DEFAULT_QUADRANT_MAP, "quadrant_semantics": _quadrant_semantics(config),
        "quadrant_boundary_rule": _quadrant_boundary_rule(config), "target_pages": targets,
        "perspectives_required": resolved["required"], "perspectives_optional": resolved["optional"],
        "input_stage_status": "explicit_authorized_refs_only",
        "context_omissions": ["Business root intentionally omitted; if the task requires it, block substantive interpretation until an authorized root is supplied."] if omit_root_entity else []}


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


def require_approved_prompt_version(version: str) -> None:
    """Reject legacy or missing prompt guidance before approved source reads."""
    path = PROMPTS_DIR / f"context_deep_read.{version}.md"
    if version != "v4" or path.is_symlink() or not path.is_file():
        raise ContextRequestBlocked(
            "approved_prompt_migration_required",
            "Approved ingestion requires the installed v4 deep-read prompt; migrate the configured prompt version before preparing this request.",
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
        raise ContextRequestBlocked("approved_prompt_migration_required", "Approved ingestion requires the installed v4 deep-read prompt; restore it before preparing this request.") from exc


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


def write_result(cache_dir: Path, result: dict[str, object]) -> Path:
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
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _source_hash(manifest: dict[str, object]) -> str:
    return str(manifest.get("hash_sha256") or manifest.get("source_id"))



# Only semantic inputs delivered to the reader belong in interpretation identity.
# Capture timestamps, source-wide hashes and aggregate counters do not.
_CONTEXT_FIELDS = (
    "prompt_name", "prompt", "source_context", "quadrants_required",
    "quadrant_map", "quadrant_semantics", "quadrant_boundary_rule", "root_entity",
    "input_channel", "input_stage_status", "target_pages", "perspectives_required",
    "perspectives_optional", "block_context_package", "request_limits", "source_authorization", "independent_repo_content", "independent_repo_additional_content",
)


def context_fingerprint(request: dict, provenance: dict) -> str:
    envelope = {key: request.get(key) for key in _CONTEXT_FIELDS}
    for optional in ("request_limits", "source_authorization", "independent_repo_content", "independent_repo_additional_content"):
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
    if not isinstance(request, dict):
        return False
    package = request.get("block_context_package")
    version = request.get("context_binding_version")
    schema = package.get("schema_version") if isinstance(package, dict) else None
    authorization = request.get("source_authorization")
    if version == 2:
        if (schema != "wiki.folder-task-context/v2" or not isinstance(authorization, dict)
                or authorization.get("version") != "folder/v2"
                or authorization.get("folder") != package.get("context_folder")
                or authorization.get("context_id") != package.get("context_id")
                or authorization.get("policy_revision") != package.get("policy_revision")
                or authorization.get("canonical_revision") != package.get("content_revision")
                or authorization.get("source_sha256") != request.get("source_hash_sha256")):
            return False
        kind = authorization.get("source_kind")
        if kind == "git":
            if (authorization.get("source_revision") != package.get("content_revision")
                    or authorization.get("canonical_ref") != authorization.get("ref")
                    or authorization.get("canonical_sha256") != authorization.get("source_sha256")
                    or authorization.get("association") != "git_blob_verified"):
                return False
        elif kind == "staged_raw":
            if (authorization.get("source_revision") is not None
                    or authorization.get("canonical_ref") == authorization.get("ref")
                    or authorization.get("association") != "caller_selected_unverified"
                    or authorization.get("external_origin_verification") != "not_verified"
                    or authorization.get("external_freshness") != "not_verified"):
                return False
        else:
            return False
        repo_read = authorization.get("independent_repo_read")
        repo_content = request.get("independent_repo_content")
        if (repo_read is None) != (repo_content is None):
            return False
        if repo_read is not None:
            if (kind != "git" or not isinstance(repo_read, dict) or not isinstance(repo_content, str)
                    or repo_read.get("schema_version") != "wiki.independent-repo-read/v1"
                    or repo_read.get("section") is not None or repo_read.get("field") is not None
                    or repo_read.get("content_sha256") != sha256_text(repo_content)):
                return False
        extra_reads = authorization.get("independent_repo_additional_reads")
        extra_content = request.get("independent_repo_additional_content")
        if (extra_reads is None) != (extra_content is None):
            return False
        if extra_reads is not None:
            if (repo_read is None or not isinstance(extra_reads, list) or not 1 <= len(extra_reads) <= 15
                    or not isinstance(extra_content, list) or len(extra_content) != len(extra_reads)):
                return False
            seen = {repo_read.get("path")}
            for extra, content in zip(extra_reads, extra_content):
                if (not isinstance(extra, dict) or not isinstance(content, str)
                        or extra.get("schema_version") != "wiki.independent-repo-read/v1"
                        or extra.get("repository") != repo_read.get("repository")
                        or extra.get("revision") != repo_read.get("revision")
                        or extra.get("section") is not None or extra.get("field") is not None
                        or not isinstance(extra.get("path"), str) or extra["path"] in seen
                        or extra.get("content_sha256") != sha256_text(content)):
                    return False
                seen.add(extra["path"])
        inputs = package.get("inputs")
        selected = [item for item in inputs if isinstance(item, dict) and item.get("kind") == "evidence"
                    and item.get("path") == authorization.get("canonical_ref")
                    and item.get("revision") == authorization.get("canonical_revision")
                    and item.get("document_sha256") == authorization.get("canonical_sha256")
                    and item.get("producer_context") == authorization.get("canonical_producer")
                    and item.get("section") is None and item.get("field") is None
                    and item.get("use") == "interpretation" and item.get("classification") == "source"] if isinstance(inputs, list) else []
        origin = authorization.get("source_origin")
        provenance = row.get("provenance") if isinstance(row, dict) else None
        if (len(selected) != 1 or not isinstance(origin, dict) or not isinstance(provenance, dict)
                or origin.get("kind") != "repository_path" or origin.get("locator") != authorization.get("ref")
                or not origin.get("id") or provenance.get("origin_id") != origin.get("id")):
            return False
    elif version not in (None, 1) or schema == "wiki.folder-task-context/v2":
        return False
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
    if (version in (1, 2) or result.get("context_sha256") is not None) and bound is None:
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


def result_cache_for_request(cache_dir: Path, request: dict) -> Path:
    """Keep folder-v2 recordings distinct from legacy/unrequested results."""
    return Path(cache_dir) / 'folder-v2' if request.get('context_binding_version') == 2 else Path(cache_dir)


def read_matching_result(cache_dir: Path, request: dict, row: dict, *, root: Path | None = None) -> dict | None:
    key = row.get("cache_key") if isinstance(row, dict) else None
    if not isinstance(key, str) or not CACHE_KEY_RE.fullmatch(key):
        return None
    selected_cache = result_cache_for_request(cache_dir, request)
    if request.get('context_binding_version') == 2:
        if root is None:
            return None
        try:
            from wiki_core.folder_ingestion_v2 import _check_local_boundaries
            root = Path(root).resolve()
            relative = result_path(selected_cache, key).relative_to(root).as_posix()
            _check_local_boundaries(root, relative)
        except (ValueError, OSError, TypeError, RuntimeError):
            return None
    result = read_result(selected_cache, key)
    return result if result_matches_request(result, request, row) else None


def ingestion_block_context(root: Path, config, input_context: dict,
                            perspectives_required: list[str], *,
                            approved_revision: str | None = None,
                            policy_context: str | None = None,
                            task_id: str = "source-context-pass",
                            context_max_bytes: int = DEFAULT_CONTEXT_MAX_BYTES,
                            content_revision: str = "HEAD") -> dict:
    """Construct the real contextual inputs at both production call sites.

    Without an explicit approved revision this preserves the working-tree
    adapter. It claims no authorization or immutable revision. The approved
    policy adapter is selected only by a trusted local caller, never by finding
    an unapproved context.yaml in the worktree.
    """
    if approved_revision is not None:
        return _approved_ingestion_context(root, config, input_context,
            perspectives_required, approved_revision, policy_context, task_id, context_max_bytes, content_revision)

    if policy_context is not None and approved_revision is None:
        raise ValueError("policy_context requires an explicit approved_revision")
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


def _approved_ingestion_context(root, config, input_context, perspectives_required,
                                approved_revision, policy_context, task_id, context_max_bytes, content_revision):
    from wiki_core.context_policy import load_policy
    from wiki_core.context_packet import build_packet
    from wiki_core.repository_reader import RepositoryReader
    policy = load_policy(root, approved_revision)
    if not policy_context:
        raise ValueError("approved context requires an explicit policy_context")
    policy.lineage(policy_context)  # Validate identity before cataloguing.
    reader = RepositoryReader(root, content_revision)
    allowed = [path for path in reader.paths if policy.permits(policy_context, "read", path)
               and policy.owner_of(path) == policy_context]
    catalogue = reader.catalogue(allowed_paths=allowed)
    by_id = {}
    for row in catalogue:
        by_id.setdefault(row["page_id"], []).append(row["path"])
    refs = []
    for name in ("root_entity", "input_channel", "source_config"):
        info = input_context.get(name) or {}
        if info.get("path"):
            refs.append(info["path"])
    for ref in perspectives_required:
        if ref in allowed:
            path = ref
        else:
            matches = by_id.get(ref, [])
            if len(matches) != 1:
                raise ValueError("required perspective missing or ambiguous within authorized context: " + ref)
            path = matches[0]
        refs.append(path)
    evidence = [{"ref": ref, "producer": policy.owner_of(ref),
        "reason": "Required ingestion interpretation context", "use": "interpretation",
        "classification": "context"} for ref in dict.fromkeys(refs)]
    packet = build_packet(root, policy, policy_context, reader.revision, evidence, context_max_bytes,
        task_id=task_id, goal="Deep contextual reading of the extracted source",
        output="Recorded LLM context-pass results for each extracted chunk",
        integrator="Operating ingestion agent under the repository PR review gate",
        omissions=input_context.get("context_omissions", []))
    return packet


def build_context_request(
    manifest: dict[str, object],
    chunks: list[dict[str, object]],
    cache_dir: Path,
    prompt_version: str,
    schema_version: str,
    model_profile: str,
    *,
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
    independent_repo_content: str | None = None,
    independent_repo_additional_content: list[str] | None = None,
    context_root: Path | None = None,
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
    folder_v2 = (block_context_package or {}).get("schema_version") == "wiki.folder-task-context/v2"
    approved = ((block_context_package or {}).get("schema_version") == "wiki.task-context/v1" or folder_v2
                or source_authorization is not None)
    if approved:
        if prompt_name != "context_deep_read":
            raise ContextRequestBlocked("approved_prompt_migration_required", "Approved ingestion requires the installed v4 deep-read prompt.")
        require_approved_prompt_version(prompt_version)
    prompt_text = load_prompt(prompt_name, prompt_version, allow_fallback=not approved)
    result_required_keys = [*RESULT_REQUIRED_KEYS, "context_sha256", "chunk_hash_sha256"]
    if perspectives_required:
        result_required_keys.append("perspectives")
    request = {
        "kind": "llm_context_request",
        "context_binding_version": 2 if folder_v2 else 1,
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
            + ("Record with the same authorized source, approved revision, folder selection and byte limits; "
               "the caller must rebuild and revalidate the current folder-bound request. "
               if folder_v2 else
               "Record with the same explicit authorized source, approved revision, "
               "policy context and byte limits using the approved command in the prompt. "
               if approved else
               "Record via the working-tree compatibility command in the prompt. ")
            + "Never write canonical memory directly."
        ),
    }

    if source_authorization is not None:
        request["source_authorization"] = source_authorization
        if folder_v2 and source_authorization.get("source_kind") == "staged_raw":
            request["instructions"] += (" The staged RAW bytes are linked to the selected source page by caller declaration; "
                                        "external origin and freshness are not verified.")
    if independent_repo_content is not None:
        if not folder_v2 or not isinstance(source_authorization, dict) or "independent_repo_read" not in source_authorization:
            raise ValueError("independent repository content requires a bound folder authorization")
        request["independent_repo_content"] = independent_repo_content
        request["instructions"] += (" Interpret the selected independent repository text as source evidence alongside the wiki source node. "
            "Apply explicitly selected AGENTS instructions where they govern a selected path, subject to the trusted host and existing policy; "
            "they do not expand access. Inclusion is not proof of execution.")
    if independent_repo_additional_content is not None:
        if (independent_repo_content is None or not isinstance(source_authorization, dict)
                or "independent_repo_additional_reads" not in source_authorization):
            raise ValueError("additional repository content requires a bound folder authorization")
        request["independent_repo_additional_content"] = independent_repo_additional_content

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
        existing = read_matching_result(cache_dir, request, row, root=context_root)
        row["result_exists"] = existing is not None
        if existing is not None:
            row["result_source_id"] = existing.get("source_id")
            row["result_chunk_id"] = existing.get("chunk_id")
        request["chunks"].append(row)
        request["cached_calls" if existing is not None else "pending_llm_calls"] += 1
    request["instructions"] += " Copy context_sha256 and chunk_hash_sha256 from the chunk; retain its exact source_id and chunk_id."
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
