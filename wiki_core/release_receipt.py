"""Exact-subject release receipts for public and downstream Wiki Viva gates.

The receipt is deliberately small and strict. It does not run tests; it binds
normalized gate-result files and release artifacts to one Git subject and
decides whether that evidence may be promoted to E5. Dirty or incomplete
evidence remains useful as closure evidence, but can never claim E5.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import zlib
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from scripts._git_subject import (
    FINGERPRINT_VERSION,
    GitSubjectError,
    collect_git_subject as _collect_exact_git_subject,
)

from .config import load_config
from .adapter_manifest import (
    ADAPTER_MANIFEST_SCHEMA_VERSION,
    AdapterManifestError,
    DEFAULT_ADAPTER_MANIFEST,
    load_and_verify_adapter_manifest,
)
from .detectors import scan_text
from .upgrade import _canonical_portable_path, _portable_path_has_sensitive_name
from .web.schemas import (
    ACTION_STATE_TRANSITION_CAPABILITY,
    CORS_DEFAULT_DENY_CAPABILITY,
    OPERATOR_SECURITY_CAPABILITY,
    WEB_OPERATOR_SECURITY_VERSION,
    WEB_SERVER_VERSION,
)

RECEIPT_SCHEMA_VERSION = "wiki_release_receipt.v1"
GATE_RESULT_SCHEMA_VERSION = "wiki_test_gate_result.v1"
REQUIRED_SCOPES = ("public_required", "downstream_required")
REQUIRED_SCOPE_BY_RECEIPT_KIND = {
    "public_release": "public_required",
    "private_adoption": "downstream_required",
}
E5_SCOPE = "e5_release"
SEMANTIC_VALIDATOR_VERSION = "wiki_release_receipt_semantic_validator.v1"
GATE_POLICY_VERSION = "wiki_release_gate_policy.v1"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{7,127}$")
ARTIFACT_KIND_SCHEMAS = {
    "release_note": "wiki_release_note.markdown.v1",
    "visual_evidence_manifest": "wiki_visual_evidence_manifest.v1",
}
MAX_VISUAL_EVIDENCE_ENTRIES = 256
MAX_DECOMPRESSED_VISUAL_BYTES = 128 * 1024 * 1024
MAX_GATE_TO_RECEIPT_SECONDS = 24 * 60 * 60
MAX_REQUIRED_RUN_SECONDS = 6 * 60 * 60
CANONICAL_RELEASE_MATRIX_PATH = (
    "apps/wiki-cockpit/scripts/release-matrix-contract.json"
)

GATE_POLICY = {
    "public_required": {
        "playwright-public": "playwright_public_release_v1",
    },
    "downstream_required": {
        "playwright-downstream": "playwright_downstream_release_v1",
    },
}


class ReleaseReceiptError(ValueError):
    """Raised when input evidence is malformed or unsafe to bind."""


def collect_git_subject(root: Path, *, base_sha: str | None = None) -> dict[str, Any]:
    """Collect a stable exact Git subject without exposing dirty paths/content."""

    try:
        return _collect_exact_git_subject(root, base_sha=base_sha)
    except GitSubjectError as exc:
        raise ReleaseReceiptError(str(exc)) from exc


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _safe_evidence_file(
    root: Path, raw_path: object, *, label: str
) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ReleaseReceiptError(
            f"{label} path must be a non-empty repo-relative string"
        )
    normalized, _path_error = _canonical_portable_path(raw_path)
    if normalized is None:
        raise ReleaseReceiptError(
            f"{label} path must be one canonical repo-relative POSIX path"
        )
    if _portable_path_has_sensitive_name(normalized):
        raise ReleaseReceiptError(
            f"{label} path is blocked by the case-insensitive sensitive-name policy"
        )
    relative = Path(normalized)
    root = root.resolve()
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseReceiptError(f"{label} path must not traverse a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise ReleaseReceiptError(
            f"{label} file is missing or outside the repository"
        ) from exc
    if not resolved.is_file():
        raise ReleaseReceiptError(f"{label} must resolve to a regular file")
    return resolved, normalized


def _read_safe_evidence_file(
    root: Path, raw_path: object, *, label: str
) -> tuple[str, bytes]:
    """Read one repo file once through a no-symlink descriptor chain.

    Parsing, hashing and sizing all use the returned bytes, avoiding the old
    read/hash TOCTOU split.  The fallback branch retains the resolved-path
    guard for platforms without ``dir_fd``/``O_NOFOLLOW`` support.
    """

    if os.name == "nt":
        raise ReleaseReceiptError(
            "release evidence operations are unsupported on Windows until "
            "handle-pinned reparse-point traversal is available"
        )
    resolved, relative = _safe_evidence_file(root, raw_path, label=label)
    root = root.resolve()
    parts = Path(relative).parts
    descriptor: int | None = None
    opened: list[int] = []
    try:
        if os.name != "nt" and hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            opened.append(descriptor)
            for part in parts[:-1]:
                descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                opened.append(descriptor)
            descriptor = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            opened.append(descriptor)
        else:
            descriptor = os.open(resolved, os.O_RDONLY)
            opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ReleaseReceiptError(f"{label} must be a regular file")
        if before.st_nlink != 1:
            raise ReleaseReceiptError(f"{label} must not be hard-linked")
        if before.st_size > MAX_EVIDENCE_BYTES:
            raise ReleaseReceiptError(
                f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte evidence limit"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor, min(1024 * 1024, MAX_EVIDENCE_BYTES + 1 - total)
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_EVIDENCE_BYTES:
                raise ReleaseReceiptError(
                    f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte evidence limit"
                )
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise ReleaseReceiptError(f"{label} changed while it was read")
        return relative, b"".join(chunks)
    except ReleaseReceiptError:
        raise
    except OSError as exc:
        raise ReleaseReceiptError(
            f"{label} could not be opened safely without symlink traversal"
        ) from exc
    finally:
        for handle in reversed(opened):
            try:
                os.close(handle)
            except OSError:
                pass


def _assert_exact_tracked_path(root: Path, relative: str, *, label: str) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ReleaseReceiptError(f"{label} must be the exact tracked repository file")


def _nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReleaseReceiptError(f"{label} must be a non-negative integer")
    return value


def _assert_evidence_safe(text: str, *, label: str, public: bool = False) -> None:
    # Gate/support JSON is intentionally hash-dense.  Mask only whole exact
    # SHA-1/SHA-256 tokens so numeric runs inside a digest cannot become a
    # credit-card false positive; ordinary emails/CPF/card text remains visible.
    scan_target = re.sub(
        r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{64}|[0-9A-Fa-f]{40})(?![0-9A-Fa-f])",
        "<cryptographic-digest>",
        text,
    )
    findings = [
        finding
        for finding in scan_text(scan_target)
        if finding.category == "secret"
        or (public and finding.category in {"pii", "entity"})
    ]
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        boundary = "access-secret/PII" if public else "access-secret"
        raise ReleaseReceiptError(
            f"{label} contains blocked {boundary} material: {kinds}"
        )


def _assert_no_access_secret(text: str, *, label: str) -> None:
    _assert_evidence_safe(text, label=label)


def _assert_scannable_artifact_text(
    raw: bytes,
    *,
    label: str,
    public: bool,
) -> str:
    """Reject opaque artifacts and scan every byte that a receipt binds.

    v1 intentionally accepts only UTF-8 text without binary control bytes. A
    screenshot or other opaque file belongs in a textual evidence manifest
    carrying its path, byte count and digest; hashing the binary directly would
    let secrets or public-boundary PII bypass the deterministic detectors.
    """

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseReceiptError(
            f"{label} must be UTF-8 text; record binary/screenshot hashes in a textual evidence manifest"
        ) from exc
    if any(ord(character) < 32 and character not in "\t\n\r" for character in text):
        raise ReleaseReceiptError(
            f"{label} contains binary control bytes; use a textual evidence manifest"
        )
    findings = [
        finding
        for finding in scan_text(text)
        if finding.category == "secret"
        or (public and finding.category in {"pii", "entity"})
    ]
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        boundary = "secret/PII" if public else "secret"
        raise ReleaseReceiptError(f"{label} is not {boundary}-safe: {kinds}")
    return text


def _image_dimensions(raw: bytes, *, suffix: str) -> tuple[int, int]:
    if suffix != ".png" or len(raw) < 45 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ReleaseReceiptError("visual evidence v1 accepts strict PNG images only")
    allowed_chunks = {b"IHDR", b"IDAT", b"IEND"}
    blocked_metadata = {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}
    offset = 8
    dimensions: tuple[int, int] | None = None
    idat_parts: list[bytes] = []
    saw_iend = False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ReleaseReceiptError("visual evidence PNG chunk framing is invalid")
        size = int.from_bytes(raw[offset : offset + 4], "big")
        kind = raw[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + size
        crc_end = data_end + 4
        if crc_end > len(raw):
            raise ReleaseReceiptError("visual evidence PNG chunk is truncated")
        expected_crc = int.from_bytes(raw[data_end:crc_end], "big")
        actual_crc = zlib.crc32(kind + raw[data_start:data_end]) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ReleaseReceiptError("visual evidence PNG chunk checksum is invalid")
        if kind in blocked_metadata:
            raise ReleaseReceiptError(
                "visual evidence PNG textual/EXIF metadata is forbidden"
            )
        if kind not in allowed_chunks:
            raise ReleaseReceiptError(
                "visual evidence PNG contains a non-allowlisted metadata/chunk type"
            )
        if kind == b"IHDR":
            if offset != 8 or size != 13 or dimensions is not None:
                raise ReleaseReceiptError("visual evidence PNG IHDR is invalid")
            header = raw[data_start:data_end]
            if (
                header[8] != 8
                or header[9] not in {2, 6}
                or header[10:] != b"\x00\x00\x00"
            ):
                raise ReleaseReceiptError(
                    "visual evidence PNG encoding is outside the v1 screenshot profile"
                )
            dimensions = (
                int.from_bytes(header[0:4], "big"),
                int.from_bytes(header[4:8], "big"),
            )
        elif kind == b"IDAT":
            if dimensions is None or saw_iend or size < 1:
                raise ReleaseReceiptError("visual evidence PNG IDAT ordering is invalid")
            idat_parts.append(raw[data_start:data_end])
        else:
            if dimensions is None or not idat_parts or size != 0:
                raise ReleaseReceiptError("visual evidence PNG IEND ordering is invalid")
            saw_iend = True
            offset = crc_end
            break
        offset = crc_end
    if dimensions is None or not idat_parts or not saw_iend or offset != len(raw):
        raise ReleaseReceiptError("visual evidence PNG structure is incomplete")
    width, height = dimensions
    if (
        not 1 <= width <= 16_384
        or not 1 <= height <= 16_384
        or width * height > 100_000_000
    ):
        raise ReleaseReceiptError("visual evidence image dimensions are out of bounds")
    color_type = raw[25]
    bytes_per_pixel = 3 if color_type == 2 else 4
    expected_bytes = height * (1 + width * bytes_per_pixel)
    if expected_bytes > MAX_DECOMPRESSED_VISUAL_BYTES:
        raise ReleaseReceiptError(
            "visual evidence PNG decompressed image exceeds the v1 limit"
        )
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(b"".join(idat_parts), expected_bytes + 1)
        if len(pixels) > expected_bytes or decoder.unconsumed_tail:
            raise ReleaseReceiptError(
                "visual evidence PNG decompressed size/stream is invalid"
            )
        pixels += decoder.flush(expected_bytes + 1 - len(pixels))
    except zlib.error as exc:
        raise ReleaseReceiptError("visual evidence PNG image data is invalid") from exc
    if (
        len(pixels) != expected_bytes
        or decoder.unconsumed_tail
        or decoder.unused_data
        or not decoder.eof
    ):
        raise ReleaseReceiptError(
            "visual evidence PNG decompressed size/stream is invalid"
        )
    stride = 1 + width * bytes_per_pixel
    if any(pixels[row] > 4 for row in range(0, expected_bytes, stride)):
        raise ReleaseReceiptError("visual evidence PNG row filter is invalid")
    return dimensions


def visual_evidence_file_metadata(
    root: Path, raw_path: object, *, label: str = "visual evidence image"
) -> dict[str, Any]:
    """Read one repository screenshot safely and return content-bound metadata.

    The same descriptor-pinned, no-symlink/no-hardlink and strict-PNG contract
    used by release receipts is shared with downstream migration reports.  A
    caller therefore cannot make a missing or substituted screenshot look
    valid by recording only a path string.
    """

    relative, raw = _read_safe_evidence_file(root, raw_path, label=label)
    width, height = _image_dimensions(raw, suffix=Path(relative).suffix.lower())
    return {
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "dimensions": {"width": width, "height": height},
    }


def _validate_visual_evidence_manifest(
    root: Path,
    payload: object,
    *,
    public: bool,
) -> None:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "entries",
    }:
        raise ReleaseReceiptError("visual evidence manifest fields are invalid")
    if payload.get("schema_version") != "wiki_visual_evidence_manifest.v1":
        raise ReleaseReceiptError("visual evidence manifest schema is invalid")
    entries = payload.get("entries")
    required = {
        "id",
        "path",
        "sha256",
        "bytes",
        "route",
        "browser",
        "viewport",
        "capture_dimensions",
        "state",
        "public_synthetic",
    }
    if (
        not isinstance(entries, list)
        or not entries
        or len(entries) > MAX_VISUAL_EVIDENCE_ENTRIES
    ):
        raise ReleaseReceiptError("visual evidence manifest entry count is invalid")
    ids: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != required:
            raise ReleaseReceiptError(
                f"visual evidence entry {index} fields are invalid"
            )
        entry_id = str(entry.get("id") or "")
        ids.append(entry_id)
        visual_path = entry.get("path")
        viewport = entry.get("viewport")
        capture_dimensions = entry.get("capture_dimensions")
        suffix = Path(str(visual_path)).suffix.lower()
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", entry_id)
            or not _portable_metadata_path(visual_path)
            or suffix != ".png"
            or not SHA256_RE.fullmatch(str(entry.get("sha256") or ""))
            or not _valid_count(entry.get("bytes"))
            or entry.get("bytes") < 1
            or entry.get("bytes") > MAX_EVIDENCE_BYTES
            or not isinstance(entry.get("route"), str)
            or not str(entry.get("route")).startswith("/")
            or len(str(entry.get("route"))) > 512
            or entry.get("browser") not in {"chromium", "firefox", "webkit"}
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or any(
                isinstance(viewport.get(axis), bool)
                or not isinstance(viewport.get(axis), int)
                or not 240 <= viewport.get(axis) <= 7680
                for axis in ("width", "height")
            )
            or not isinstance(capture_dimensions, Mapping)
            or set(capture_dimensions) != {"width", "height"}
            or any(
                isinstance(capture_dimensions.get(axis), bool)
                or not isinstance(capture_dimensions.get(axis), int)
                or not 1 <= capture_dimensions.get(axis) <= 16_384
                for axis in ("width", "height")
            )
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9._-]{0,127}", str(entry.get("state") or "")
            )
            or not isinstance(entry.get("public_synthetic"), bool)
        ):
            raise ReleaseReceiptError(f"visual evidence entry {index} is invalid")
        if public and entry.get("public_synthetic") is not True:
            raise ReleaseReceiptError(
                f"visual evidence entry {index} is not public-synthetic"
            )
        image_relative, image_raw = _read_safe_evidence_file(
            root,
            visual_path,
            label=f"visual evidence image {entry_id}",
        )
        width, height = _image_dimensions(image_raw, suffix=suffix)
        if (
            image_relative != visual_path
            or hashlib.sha256(image_raw).hexdigest() != entry.get("sha256")
            or len(image_raw) != entry.get("bytes")
            or capture_dimensions != {"width": width, "height": height}
        ):
            raise ReleaseReceiptError(
                f"visual evidence image {entry_id} hash/bytes/dimensions do not match"
            )
    if ids != sorted(set(ids)):
        raise ReleaseReceiptError(
            "visual evidence manifest IDs must be sorted and unique"
        )


def _validate_artifact_kind(
    *,
    root: Path,
    kind: str,
    relative: str,
    text: str,
    public: bool,
) -> str:
    schema = ARTIFACT_KIND_SCHEMAS.get(kind)
    if schema is None:
        raise ReleaseReceiptError(
            f"artifact kind is not registered: {kind or 'missing'}"
        )
    suffix = Path(relative).suffix.lower()
    if kind == "release_note":
        if (
            suffix != ".md"
            or not text.strip()
            or not any(line.lstrip().startswith("#") for line in text.splitlines())
        ):
            raise ReleaseReceiptError(
                "release_note artifact must be non-empty Markdown with a heading"
            )
        return schema
    if suffix != ".json":
        raise ReleaseReceiptError(f"{kind} artifact must be a JSON file")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReleaseReceiptError(f"{kind} artifact must be valid JSON") from exc
    if kind == "visual_evidence_manifest":
        _validate_visual_evidence_manifest(root, payload, public=public)
    elif (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != "wiki_web_snapshot.v2"
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}", str(payload.get("snapshot_id") or "")
        )
        or not SHA256_RE.fullmatch(str(payload.get("bundle_hash") or ""))
        or not isinstance(payload.get("contract_errors"), list)
        or payload.get("contract_errors")
        or not isinstance(payload.get("versions"), Mapping)
        or payload["versions"].get("snapshot") != "wiki_web_snapshot.v2"
    ):
        raise ReleaseReceiptError("snapshot_manifest artifact contract is invalid")
    return schema


def _portable_report_file(raw: object, *, root_dir: str, scope: str) -> str:
    value = str(raw or "").replace("\\", "/")
    marker = value.rfind("/e2e/")
    if marker >= 0:
        value = value[marker + 1 :]
    elif root_dir and not value.startswith("e2e/"):
        value = f"{root_dir.rstrip('/')}/{value}"
        marker = value.rfind("/e2e/")
        if marker >= 0:
            value = value[marker + 1 :]
    value = value.removeprefix("./")
    if not value.startswith("e2e/"):
        prefix = "e2e/downstream/" if scope == "downstream_required" else "e2e/"
        value = f"{prefix}{value}"
    normalized, _error = _canonical_portable_path(value)
    if normalized != value or not value.endswith(".spec.ts"):
        raise ReleaseReceiptError(
            "Playwright raw evidence contains an unsafe spec path"
        )
    return value


def _playwright_report_cells(
    payload: Mapping[str, Any], *, scope: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ReleaseReceiptError("Playwright raw evidence config is missing")
    root_dir = str(config.get("rootDir") or "").replace("\\", "/")
    records: list[dict[str, Any]] = []

    def visit(suite: object, ancestors: tuple[str, ...] = ()) -> None:
        if not isinstance(suite, Mapping):
            raise ReleaseReceiptError("Playwright raw evidence suite is invalid")
        suite_title = str(suite.get("title") or "").strip()
        titles = ancestors + ((suite_title,) if suite_title else ())
        specs = suite.get("specs", [])
        children = suite.get("suites", [])
        if not isinstance(specs, list) or not isinstance(children, list):
            raise ReleaseReceiptError(
                "Playwright raw evidence suite collections are invalid"
            )
        for spec in specs:
            if not isinstance(spec, Mapping):
                raise ReleaseReceiptError("Playwright raw evidence spec is invalid")
            file = _portable_report_file(
                spec.get("file"), root_dir=root_dir, scope=scope
            )
            spec_title = str(spec.get("title") or "").strip()
            title = " › ".join((*titles, spec_title) if spec_title else titles)
            tests = spec.get("tests", [])
            if not isinstance(tests, list):
                raise ReleaseReceiptError("Playwright raw evidence tests are invalid")
            for test in tests:
                if not isinstance(test, Mapping):
                    raise ReleaseReceiptError("Playwright raw evidence test is invalid")
                project = str(
                    test.get("projectName") or test.get("projectId") or ""
                ).strip()
                records.append(
                    {
                        "id": f"{project}::{file}::{title}",
                        "file": file,
                        "project": project,
                        "title": title,
                        "test": test,
                    }
                )
        for child in children:
            visit(child, titles)

    suites = payload.get("suites", [])
    if not isinstance(suites, list):
        raise ReleaseReceiptError("Playwright raw evidence suites are invalid")
    for suite in suites:
        visit(suite)
    cells = [
        {name: str(record[name]) for name in ("id", "file", "project", "title")}
        for record in records
    ]
    return records, sorted(cells, key=lambda item: item["id"])


def _validate_playwright_raw_evidence(
    payload: Mapping[str, Any],
    *,
    scope: str,
    matrix_scope: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> None:
    """Independently derive counts/config/cells from the Playwright JSON."""

    config = payload.get("config")
    if not isinstance(config, Mapping):
        raise ReleaseReceiptError("Playwright raw evidence config is missing")
    projects = config.get("projects")
    if (
        config.get("forbidOnly") is not True
        or config.get("fullyParallel") is not False
        or config.get("workers") != 1
        or not isinstance(projects, list)
        or not projects
        or any(
            not isinstance(project, Mapping)
            or project.get("retries") != 0
            or project.get("repeatEach") != 1
            for project in projects
        )
    ):
        raise ReleaseReceiptError(
            "Playwright raw evidence uses an unsafe runner config"
        )
    if Path(str(config.get("configFile") or "")).name != matrix_scope["config_file"]:
        raise ReleaseReceiptError(
            "Playwright raw evidence config file contradicts the matrix"
        )
    root_dir = str(config.get("rootDir") or "").replace("\\", "/").rstrip("/")
    if not root_dir.endswith(f"/{matrix_scope['test_dir']}"):
        raise ReleaseReceiptError(
            "Playwright raw evidence testDir contradicts the matrix"
        )

    records, cells = _playwright_report_cells(payload, scope=scope)
    expected_cells = list(matrix_scope["cells"])
    if cells != expected_cells or not records:
        raise ReleaseReceiptError(
            "Playwright raw evidence cells contradict the exact matrix"
        )
    configured_projects = sorted(
        {
            str(project.get("name") or "")
            for project in projects
            if isinstance(project, Mapping)
        }
    )
    if configured_projects != list(matrix_scope["required_projects"]):
        raise ReleaseReceiptError(
            "Playwright raw evidence projects contradict the exact matrix"
        )

    counts = {name: 0 for name in ("passed", "failed", "skipped", "flaky", "retries")}
    test_failures = 0
    for record in records:
        test = record["test"]
        results = test.get("results", [])
        if not isinstance(results, list):
            raise ReleaseReceiptError(
                "Playwright raw evidence test results are invalid"
            )
        retry_values: list[int] = []
        for result in results:
            if not isinstance(result, Mapping):
                raise ReleaseReceiptError("Playwright raw evidence result is invalid")
            retry = result.get("retry")
            if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
                raise ReleaseReceiptError(
                    "Playwright raw evidence retry value is invalid"
                )
            retry_values.append(retry)
        retries = max(retry_values, default=0)
        counts["retries"] += retries
        status = str(test.get("status") or "")
        final_status = str(results[-1].get("status") or "") if results else ""
        expected_status = str(test.get("expectedStatus") or "passed")
        skipped = (
            status == "skipped"
            or final_status == "skipped"
            or expected_status == "skipped"
        )
        flaky = status == "flaky" or retries > 0 or len(results) > 1
        passed = (
            expected_status == "passed"
            and final_status == "passed"
            and status == "expected"
        )
        if skipped:
            counts["skipped"] += 1
        elif flaky:
            counts["flaky"] += 1
        elif passed:
            counts["passed"] += 1
        else:
            counts["failed"] += 1
            test_failures += 1
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        raise ReleaseReceiptError("Playwright raw evidence errors are invalid")
    counts["failed"] += len(errors)
    stats = payload.get("stats")
    expected_stats = {
        "expected": counts["passed"],
        "unexpected": test_failures,
        "skipped": counts["skipped"],
        "flaky": counts["flaky"],
    }
    if not isinstance(stats, Mapping) or any(
        isinstance(stats.get(name), bool)
        or not isinstance(stats.get(name), int)
        or stats.get(name) != value
        for name, value in expected_stats.items()
    ):
        raise ReleaseReceiptError(
            "Playwright raw evidence stats contradict parsed tests"
        )
    if any(counts[name] for name in ("failed", "skipped", "flaky", "retries")):
        raise ReleaseReceiptError(
            "Playwright raw evidence is not a first-attempt clean pass"
        )
    if any(gate.get(name) != counts[name] for name in counts):
        raise ReleaseReceiptError(
            "gate counts contradict independently parsed raw evidence"
        )


def _validate_release_matrix_contract(payload: Mapping[str, Any]) -> None:
    top_keys = {
        "schema_version",
        "contract_version",
        "playwright_version",
        "public_required",
        "downstream_required",
    }
    if set(payload) != top_keys:
        raise ReleaseReceiptError("release matrix contract fields are incomplete")
    if (
        payload.get("schema_version") != "wiki_playwright_release_matrix.v1"
        or payload.get("contract_version") != 2
        or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?",
            str(payload.get("playwright_version") or ""),
        )
    ):
        raise ReleaseReceiptError("release matrix contract version is invalid")
    record_keys = {
        "config_file",
        "test_dir",
        "expected_tests",
        "required_specs",
        "required_projects",
        "cells",
    }
    cell_keys = {"id", "file", "project", "title"}
    for scope in REQUIRED_SCOPES:
        record = payload.get(scope)
        if not isinstance(record, Mapping) or set(record) != record_keys:
            raise ReleaseReceiptError(f"release matrix {scope} fields are incomplete")
        expected_config = (
            "playwright.config.ts"
            if scope == "public_required"
            else "playwright.downstream.config.ts"
        )
        expected_dir = "e2e" if scope == "public_required" else "e2e/downstream"
        if (
            record.get("config_file") != expected_config
            or record.get("test_dir") != expected_dir
        ):
            raise ReleaseReceiptError(
                f"release matrix {scope} config identity is invalid"
            )
        expected_tests = _nonnegative_int(
            record.get("expected_tests"), label=f"release matrix {scope} expected_tests"
        )
        specs = record.get("required_specs")
        projects = record.get("required_projects")
        cells = record.get("cells")
        if (
            expected_tests < 1
            or not isinstance(specs, list)
            or not isinstance(projects, list)
            or not isinstance(cells, list)
            or len(cells) != expected_tests
        ):
            raise ReleaseReceiptError(f"release matrix {scope} has no exact cell set")
        if specs != sorted(set(specs)) or projects != sorted(set(projects)):
            raise ReleaseReceiptError(
                f"release matrix {scope} specs/projects are not canonical"
            )
        normalized_cells: list[dict[str, str]] = []
        for index, cell in enumerate(cells):
            if not isinstance(cell, Mapping) or set(cell) != cell_keys:
                raise ReleaseReceiptError(
                    f"release matrix {scope} cell {index} is invalid"
                )
            file = str(cell.get("file") or "")
            project = str(cell.get("project") or "")
            title = str(cell.get("title") or "")
            cell_id = str(cell.get("id") or "")
            normalized, _error = _canonical_portable_path(file)
            if (
                normalized != file
                or _portable_path_has_sensitive_name(file)
                or not file.endswith(".spec.ts")
                or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", project)
                or not title
                or cell_id != f"{project}::{file}::{title}"
            ):
                raise ReleaseReceiptError(
                    f"release matrix {scope} cell {index} metadata is invalid"
                )
            is_downstream = file.startswith("e2e/downstream/")
            if (scope == "public_required" and is_downstream) or (
                scope == "downstream_required" and not is_downstream
            ):
                raise ReleaseReceiptError(
                    f"release matrix {scope} crosses its boundary"
                )
            normalized_cells.append(
                {"id": cell_id, "file": file, "project": project, "title": title}
            )
        if normalized_cells != sorted(normalized_cells, key=lambda item: item["id"]):
            raise ReleaseReceiptError(f"release matrix {scope} cells are not canonical")
        if len({cell["id"] for cell in normalized_cells}) != expected_tests:
            raise ReleaseReceiptError(f"release matrix {scope} cell IDs are not unique")
        if sorted({cell["file"] for cell in normalized_cells}) != specs:
            raise ReleaseReceiptError(
                f"release matrix {scope} spec set contradicts cells"
            )
        if sorted({cell["project"] for cell in normalized_cells}) != projects:
            raise ReleaseReceiptError(
                f"release matrix {scope} project set contradicts cells"
            )


def _validate_downstream_preflight(
    root: Path, payload: Mapping[str, Any], *, expected_subject_sha: str
) -> None:
    required = {
        "schema_version",
        "scope",
        "status",
        "repository",
        "snapshot_revision",
        "snapshot_hash",
        "consumer_head",
        "snapshot_source_commit",
        "snapshot_source_sha",
        "public_release_sha",
        "adapter_hash",
        "adapter_manifest",
        "adapter_manifest_schema_version",
        "adapter_file_count",
        "snapshot_version",
        "runtime_version",
        "operator_server_version",
        "operator_security",
        "temporal_graph_version",
        "temporal_event_version",
        "temporal_event_count",
        "experience_pack_composition_version",
        "composition_sha256",
        "active_packs",
        "contract_errors",
        "page_count",
        "minimum_pages",
        "capabilities",
        "snapshot_capabilities",
        "endpoint_origins",
    }
    if set(payload) != required:
        raise ReleaseReceiptError("downstream preflight fields are incomplete")
    if (
        payload.get("schema_version") != "wiki_downstream_preflight.v2"
        or payload.get("scope") != "downstream_required"
        or payload.get("status") != "passed"
    ):
        raise ReleaseReceiptError("downstream preflight status/schema is invalid")
    repository = str(payload.get("repository") or "")
    snapshot_hash = str(payload.get("snapshot_hash") or "").lower()
    snapshot_revision = str(payload.get("snapshot_revision") or "")
    consumer = str(payload.get("consumer_head") or "").lower()
    public_release_sha = str(payload.get("public_release_sha") or "").lower()
    adapter_hash = str(payload.get("adapter_hash") or "").lower()
    adapter_manifest = str(payload.get("adapter_manifest") or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", repository)
        or not SHA256_RE.fullmatch(snapshot_hash)
        or snapshot_revision != f"{repository}-{snapshot_hash[:16]}"
        or not SHA1_RE.fullmatch(consumer)
        or str(payload.get("snapshot_source_commit") or "").lower() != consumer
        or str(payload.get("snapshot_source_sha") or "").lower() != consumer
        or not SHA1_RE.fullmatch(public_release_sha)
        or not SHA256_RE.fullmatch(adapter_hash)
    ):
        raise ReleaseReceiptError("downstream preflight source identity is invalid")
    if (
        adapter_manifest != DEFAULT_ADAPTER_MANIFEST
        or payload.get("adapter_manifest_schema_version")
        != ADAPTER_MANIFEST_SCHEMA_VERSION
    ):
        raise ReleaseReceiptError("downstream adapter manifest identity is invalid")
    adapter_file_count = _nonnegative_int(
        payload.get("adapter_file_count"), label="preflight adapter_file_count"
    )
    if adapter_file_count < 1:
        raise ReleaseReceiptError("downstream adapter manifest is empty")
    try:
        adapter_evidence = load_and_verify_adapter_manifest(
            root,
            manifest_path=adapter_manifest,
            expected_hash=adapter_hash,
            require_tracked=True,
        )
    except (OSError, AdapterManifestError) as exc:
        raise ReleaseReceiptError(
            "downstream adapter manifest could not be independently reverified"
        ) from exc
    if adapter_evidence["file_count"] != adapter_file_count:
        raise ReleaseReceiptError("downstream adapter manifest file count is stale")
    if consumer != expected_subject_sha:
        raise ReleaseReceiptError(
            "downstream preflight consumer/source identity does not match the gate subject"
        )
    if (
        payload.get("snapshot_version") != "wiki_web_snapshot.v2"
        or payload.get("runtime_version") != "wiki_world_runtime.v8"
        or payload.get("operator_server_version") != WEB_SERVER_VERSION
        or payload.get("temporal_graph_version") != "wiki_temporal_graph.v1"
        or payload.get("temporal_event_version") != "wiki_temporal_event.v1"
        or payload.get("experience_pack_composition_version")
        != "wiki_experience_pack_composition.v1"
        or payload.get("contract_errors") != []
    ):
        raise ReleaseReceiptError("downstream preflight runtime contract is invalid")
    operator_security = payload.get("operator_security")
    if (
        not isinstance(operator_security, Mapping)
        or set(operator_security)
        != {
            "version",
            "nonce_present",
            "nonce_header",
            "attempt_header",
            "max_body_bytes",
            "mutations",
            "browser_origin_default",
            "cors_opt_in",
        }
        or operator_security.get("version") != WEB_OPERATOR_SECURITY_VERSION
        or operator_security.get("nonce_present") is not True
        or operator_security.get("nonce_header") != "X-Wiki-Operator-Nonce"
        or operator_security.get("attempt_header") != "X-Wiki-Attempt-Key"
        or not isinstance(operator_security.get("max_body_bytes"), int)
        or isinstance(operator_security.get("max_body_bytes"), bool)
        or not 1 <= operator_security["max_body_bytes"] <= 1_048_576
        or operator_security.get("mutations") != "post_only"
        or operator_security.get("browser_origin_default") != "deny"
        or operator_security.get("cors_opt_in") != "exact_loopback_allowlist"
    ):
        raise ReleaseReceiptError(
            "downstream preflight operator security contract is invalid"
        )
    page_count = _nonnegative_int(
        payload.get("page_count"), label="preflight page_count"
    )
    minimum_pages = _nonnegative_int(
        payload.get("minimum_pages"), label="preflight minimum_pages"
    )
    if minimum_pages < 1 or page_count < minimum_pages:
        raise ReleaseReceiptError("downstream preflight page count is invalid")
    temporal_event_count = _nonnegative_int(
        payload.get("temporal_event_count"), label="preflight temporal_event_count"
    )
    if temporal_event_count < 1:
        raise ReleaseReceiptError("downstream preflight temporal event count is invalid")
    if not SHA256_RE.fullmatch(str(payload.get("composition_sha256") or "")):
        raise ReleaseReceiptError("downstream preflight composition hash is invalid")
    active_packs = payload.get("active_packs")
    if not isinstance(active_packs, list):
        raise ReleaseReceiptError("downstream preflight active packs are invalid")
    normalized_packs: list[dict[str, str]] = []
    for pack in active_packs:
        if (
            not isinstance(pack, Mapping)
            or set(pack) != {"id", "version"}
            or not re.fullmatch(
                r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", str(pack.get("id") or "")
            )
            or not re.fullmatch(
                r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
                r"(?:-[0-9A-Za-z.-]+)?",
                str(pack.get("version") or ""),
            )
        ):
            raise ReleaseReceiptError("downstream preflight active packs are invalid")
        normalized_packs.append(
            {"id": str(pack["id"]), "version": str(pack["version"])}
        )
    if normalized_packs != sorted(normalized_packs, key=lambda item: item["id"]) or len(
        {item["id"] for item in normalized_packs}
    ) != len(normalized_packs):
        raise ReleaseReceiptError("downstream preflight active packs are not canonical")
    capabilities = payload.get("capabilities")
    if (
        not isinstance(capabilities, list)
        or any(not isinstance(value, str) or not value for value in capabilities)
        or len(capabilities) != len(set(capabilities))
        or not {
            OPERATOR_SECURITY_CAPABILITY,
            CORS_DEFAULT_DENY_CAPABILITY,
            ACTION_STATE_TRANSITION_CAPABILITY,
        }.issubset(capabilities)
    ):
        raise ReleaseReceiptError("downstream preflight capabilities are invalid")
    snapshot_capabilities = payload.get("snapshot_capabilities")
    if (
        not isinstance(snapshot_capabilities, list)
        or any(not isinstance(value, str) or not value for value in snapshot_capabilities)
        or len(snapshot_capabilities) != len(set(snapshot_capabilities))
        or not {"temporal_graph", "experience_packs"}.issubset(snapshot_capabilities)
    ):
        raise ReleaseReceiptError("downstream preflight snapshot capabilities are invalid")
    origins = payload.get("endpoint_origins")
    if not isinstance(origins, Mapping) or set(origins) != {"snapshot", "ui"}:
        raise ReleaseReceiptError("downstream preflight origins are invalid")
    snapshot_origin = str(origins.get("snapshot") or "")
    ui_origin = str(origins.get("ui") or "")
    parsed = urlparse(snapshot_origin)
    if (
        snapshot_origin != ui_origin
        or parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseReceiptError("downstream preflight origin boundary is invalid")


def _validate_release_build_manifest(
    root: Path,
    payload: Mapping[str, Any],
    *,
    expected_subject_sha: str,
) -> None:
    required = {
        "schema_version",
        "scope",
        "subject_sha",
        "dist_root",
        "build_inputs",
        "builder_runtime",
        "file_count",
        "aggregate_sha256",
        "files",
    }
    if set(payload) != required or (
        payload.get("schema_version") != "wiki_release_build_manifest.v2"
        or payload.get("scope") != "public_required"
        or payload.get("subject_sha") != expected_subject_sha
        or payload.get("dist_root") != "apps/wiki-cockpit/dist"
    ):
        raise ReleaseReceiptError("release build manifest identity is invalid")
    expected_build_inputs = {
        "schema_version": "wiki_release_build_inputs.v1",
        "command_id": "wiki_cockpit_release_build.v1",
        "vite_mode": "production",
        "node_env": "production",
        "vite_env_loading": "disabled",
        "runtime_config_path": "scripts/public-release-runtime-config.json",
        "runtime_config_delivery": "package_owned_static_demo_override.v1",
        "environment_policy": {
            "env_files": "forbidden",
            "parent_launcher": "posix_env_i.v1",
            "inherited_names": [],
            "path_policy": "node_binary_dir_plus_usr_bin_bin.v1",
            "fixed_variables": {
                "LANG": "C",
                "LC_ALL": "C",
                "TZ": "UTC",
                "SOURCE_DATE_EPOCH": "0",
                "NODE_ENV": "production",
                "WIKI_COCKPIT_RELEASE_BUILD_INTERNAL": "1",
            },
            "forbidden_names": [
                "BABEL_ENV",
                "ESBUILD_BINARY_PATH",
                "NODE_ENV",
                "NODE_OPTIONS",
                "NODE_PATH",
                "WIKI_COCKPIT_PROXY_API",
                "WIKI_COCKPIT_RELEASE_BUILD_INTERNAL",
            ],
            "forbidden_prefixes": ["VITE_"],
        },
    }
    if payload.get("build_inputs") != expected_build_inputs:
        raise ReleaseReceiptError("release build manifest inputs are invalid")
    if payload.get("builder_runtime") != _current_node_binary_identity():
        raise ReleaseReceiptError("release build manifest Node runtime is invalid")
    files = payload.get("files")
    file_count = _nonnegative_int(
        payload.get("file_count"), label="release build manifest file_count"
    )
    if not isinstance(files, list) or not files or file_count != len(files):
        raise ReleaseReceiptError("release build manifest inventory is invalid")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(files):
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256", "bytes"}:
            raise ReleaseReceiptError(
                f"release build manifest file {index} fields are invalid"
            )
        relative = str(item.get("path") or "")
        expected_prefix = "dist/"
        if (
            not relative.startswith(expected_prefix)
            or not _portable_metadata_path(relative)
            or not SHA256_RE.fullmatch(str(item.get("sha256") or ""))
        ):
            raise ReleaseReceiptError(
                f"release build manifest file {index} identity is invalid"
            )
        declared_bytes = _nonnegative_int(
            item.get("bytes"), label=f"release build manifest file {index} bytes"
        )
        repo_relative = f"apps/wiki-cockpit/{relative}"
        actual_relative, raw = _read_safe_evidence_file(
            root, repo_relative, label=f"release build file {index}"
        )
        if (
            actual_relative != repo_relative
            or hashlib.sha256(raw).hexdigest() != item.get("sha256")
            or len(raw) != declared_bytes
        ):
            raise ReleaseReceiptError(
                f"release build manifest file {index} hash/size is stale"
            )
        normalized.append(
            {"path": relative, "sha256": item["sha256"], "bytes": declared_bytes}
        )
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        raise ReleaseReceiptError("release build manifest files are not canonical")
    if len({item["path"] for item in normalized}) != len(normalized):
        raise ReleaseReceiptError("release build manifest paths are not unique")
    aggregate = hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if payload.get("aggregate_sha256") != aggregate:
        raise ReleaseReceiptError("release build manifest aggregate is invalid")
    dist_root = root / "apps/wiki-cockpit/dist"
    if dist_root.is_symlink() or not dist_root.is_dir():
        raise ReleaseReceiptError("release dist root is missing or unsafe")
    actual_inventory: list[str] = []
    for candidate in dist_root.rglob("*"):
        if candidate.is_symlink():
            raise ReleaseReceiptError("release dist inventory contains a symlink")
        state = candidate.stat()
        if candidate.is_dir():
            continue
        if not candidate.is_file() or state.st_nlink != 1:
            raise ReleaseReceiptError(
                "release dist inventory contains a non-regular/hard-linked entry"
            )
        actual_inventory.append(f"dist/{candidate.relative_to(dist_root).as_posix()}")
    if sorted(actual_inventory) != [item["path"] for item in normalized]:
        raise ReleaseReceiptError(
            "release build manifest does not cover the exact served dist inventory"
        )
    source_relative = (
        "apps/wiki-cockpit/scripts/public-release-runtime-config.json"
    )
    served_relative = "apps/wiki-cockpit/dist/wiki-cockpit.config.json"
    _, source_runtime_config = _read_safe_evidence_file(
        root, source_relative, label="package-owned public release runtime config"
    )
    _, served_runtime_config = _read_safe_evidence_file(
        root, served_relative, label="served public release runtime config"
    )
    try:
        parsed_runtime_config = json.loads(source_runtime_config.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(
            "package-owned public release runtime config is invalid"
        ) from exc
    if parsed_runtime_config != {
        "api_base": "",
        "snapshot_base": "/sample-snapshot",
        "repo_label": "Wiki Viva Kit demo",
        "mode": "static_demo",
        "codex": {"enabled": False},
    }:
        raise ReleaseReceiptError(
            "package-owned public release runtime config is not the exact synthetic contract"
        )
    if source_runtime_config != served_runtime_config:
        raise ReleaseReceiptError(
            "served public release runtime config is not byte-equal to its package-owned source"
        )


@lru_cache(maxsize=1)
def _current_node_binary_identity() -> dict[str, Any]:
    """Independently identify and hash the native Node release executable."""

    try:
        completed = subprocess.run(
            [
                "node",
                "-p",
                "JSON.stringify({node_version:process.versions.node,exec_path:process.execPath})",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        identity = json.loads(completed.stdout) if completed.returncode == 0 else None
        if not isinstance(identity, Mapping):
            raise ValueError("invalid Node identity")
        node_version = str(identity.get("node_version") or "")
        executable = Path(str(identity.get("exec_path") or "")).resolve(strict=True)
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", node_version):
            raise ValueError("invalid Node version")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(executable, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("Node executable is not a regular single-link file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_nlink,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_nlink,
            ):
                raise ValueError("Node executable changed while read")
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise ReleaseReceiptError(
            "release builder Node executable could not be independently verified"
        ) from exc
    return {
        "node_version": node_version,
        "node_executable_sha256": hashlib.sha256(raw).hexdigest(),
        "node_executable_bytes": len(raw),
    }


@lru_cache(maxsize=2)
def _current_release_runtime(scope: str) -> dict[str, Any]:
    engines = (
        ["chromium", "firefox", "webkit"]
        if scope == "public_required"
        else ["chromium"]
    )
    toolkit_root = Path(__file__).resolve().parents[1]
    playwright_module = (
        toolkit_root / "apps/wiki-cockpit/node_modules/@playwright/test/index.mjs"
    )
    lock_path = toolkit_root / "apps/wiki-cockpit/package-lock.json"
    installed_package_path = (
        toolkit_root
        / "apps/wiki-cockpit/node_modules/@playwright/test/package.json"
    )
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        playwright_version = str(
            lock["packages"]["node_modules/@playwright/test"]["version"]
        )
        installed_playwright_version = str(
            json.loads(installed_package_path.read_text(encoding="utf-8"))["version"]
        )
        if installed_playwright_version != playwright_version:
            raise ReleaseReceiptError(
                "installed Playwright package does not match the package lock"
            )
        engine_json = json.dumps(engines)
        script = (
            f'import {{ chromium, firefox, webkit }} from "{playwright_module.as_uri()}";'
            "const all={chromium,firefox,webkit};const out=[];"
            f"for (const name of {engine_json}) {{"
            "const browser=await all[name].launch({headless:true});"
            "out.push({name,version:browser.version()});await browser.close();}"
            "console.log(JSON.stringify({platform:process.platform,arch:process.arch,node_version:process.versions.node,browser_engines:out}));"
        )
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=toolkit_root / "apps/wiki-cockpit",
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        runtime = json.loads(completed.stdout) if completed.returncode == 0 else None
    except ReleaseReceiptError:
        raise
    except (OSError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise ReleaseReceiptError(
            "installed Playwright/browser runtime could not be independently verified"
        ) from exc
    if not isinstance(runtime, Mapping):
        raise ReleaseReceiptError(
            "installed Playwright/browser runtime could not be independently verified"
        )
    return {
        "platform": str(runtime.get("platform") or ""),
        "arch": str(runtime.get("arch") or ""),
        "node_version": str(runtime.get("node_version") or ""),
        "playwright_version": playwright_version,
        "python_version": platform.python_version(),
        "browser_engines": runtime.get("browser_engines"),
    }


def _validate_toolchain_manifest(
    root: Path,
    payload: Mapping[str, Any],
    *,
    scope: str,
    expected_playwright_version: str,
) -> None:
    if set(payload) != {
        "schema_version",
        "scope",
        "runner_version",
        "runtime",
        "files",
    } or (
        payload.get("schema_version") != "wiki_playwright_toolchain_manifest.v1"
        or payload.get("scope") != scope
        or payload.get("runner_version") != "wiki_playwright_release_runner.v1"
    ):
        raise ReleaseReceiptError("Playwright toolchain manifest identity is invalid")
    runtime = payload.get("runtime")
    if (
        not isinstance(runtime, Mapping)
        or set(runtime)
        != {
            "platform",
            "arch",
            "node_version",
            "playwright_version",
            "python_version",
            "browser_engines",
        }
        or not re.fullmatch(
            r"(?:darwin|linux)", str(runtime.get("platform") or "")
        )
        or not re.fullmatch(
            r"(?:arm64|x64)", str(runtime.get("arch") or "")
        )
        or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){1,2}", str(runtime.get("node_version") or "")
        )
        or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){2}", str(runtime.get("python_version") or "")
        )
        or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+){2}(?:[-+][A-Za-z0-9.-]+)?",
            str(runtime.get("playwright_version") or ""),
        )
    ):
        raise ReleaseReceiptError("Playwright toolchain runtime metadata is invalid")
    expected_runtime = _current_release_runtime(scope)
    _lock_relative, lock_raw = _read_safe_evidence_file(
        root,
        "apps/wiki-cockpit/package-lock.json",
        label="Playwright package lock",
    )
    try:
        target_lock = json.loads(lock_raw.decode("utf-8"))
        target_playwright_version = str(
            target_lock["packages"]["node_modules/@playwright/test"]["version"]
        )
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ReleaseReceiptError("Playwright package lock metadata is invalid") from exc
    if expected_runtime["playwright_version"] != expected_playwright_version:
        raise ReleaseReceiptError(
            "canonical matrix Playwright version does not match the installed lock"
        )
    if target_playwright_version != expected_playwright_version:
        raise ReleaseReceiptError(
            "Playwright package lock version contradicts the canonical matrix"
        )
    if dict(runtime) != expected_runtime:
        raise ReleaseReceiptError(
            "Playwright toolchain runtime does not match the current validator/browser runtime"
        )
    files = payload.get("files")
    expected_paths = {
        "playwright-config": (
            "apps/wiki-cockpit/playwright.config.ts"
            if scope == "public_required"
            else "apps/wiki-cockpit/playwright.downstream.config.ts"
        ),
        "release-matrix-checker": "apps/wiki-cockpit/scripts/check-playwright-release.mjs",
        "release-matrix-library": "apps/wiki-cockpit/scripts/release-matrix-lib.mjs",
        "operator-security-contract": "apps/wiki-cockpit/src/contracts/operatorSecurity.js",
        "release-matrix-generator": "apps/wiki-cockpit/scripts/release-matrix-contract.mjs",
        "release-matrix-contract": CANONICAL_RELEASE_MATRIX_PATH,
        "release-build-manifest": "apps/wiki-cockpit/scripts/release-build-manifest.mjs",
        "release-build-policy": "apps/wiki-cockpit/scripts/release-build-policy.mjs",
        "public-release-runtime-config-policy": "apps/wiki-cockpit/scripts/public-release-runtime-config.mjs",
        "public-release-runtime-config": "apps/wiki-cockpit/scripts/public-release-runtime-config.json",
        "release-build-runner": "apps/wiki-cockpit/scripts/build-production.mjs",
        "release-build-launcher": "apps/wiki-cockpit/scripts/build-production.sh",
        "cockpit-vite-config": "apps/wiki-cockpit/vite.config.ts",
        "release-server-policy": "apps/wiki-cockpit/scripts/release-server-policy.mjs",
        "git-subject-capture": "apps/wiki-cockpit/scripts/capture-git-subject.mjs",
        "release-runner": "apps/wiki-cockpit/scripts/run-playwright-release.mjs",
        "release-runner-launcher": "apps/wiki-cockpit/scripts/run-playwright-release.sh",
        "downstream-preflight-runner": "apps/wiki-cockpit/scripts/preflight-downstream-e2e.mjs",
        "release-path-safety": "apps/wiki-cockpit/scripts/release-path-safety.mjs",
        "git-subject-compiler": "scripts/wiki_git_subject.py",
        "git-subject-helper": "scripts/_git_subject.py",
        "cockpit-package": "apps/wiki-cockpit/package.json",
        "cockpit-lockfile": "apps/wiki-cockpit/package-lock.json",
    }
    if not isinstance(files, list) or len(files) != len(expected_paths):
        raise ReleaseReceiptError(
            "Playwright toolchain manifest file set is incomplete"
        )
    seen: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, Mapping) or set(item) != {
            "id",
            "path",
            "sha256",
            "bytes",
        }:
            raise ReleaseReceiptError(f"toolchain file {index} fields are invalid")
        item_id = str(item.get("id") or "")
        if item_id in seen or item.get("path") != expected_paths.get(item_id):
            raise ReleaseReceiptError(
                f"toolchain file {item_id or index} identity is invalid"
            )
        seen.add(item_id)
        relative, raw = _read_safe_evidence_file(
            root, item.get("path"), label=f"toolchain file {item_id}"
        )
        declared_hash = str(item.get("sha256") or "").lower()
        declared_bytes = _nonnegative_int(
            item.get("bytes"), label=f"toolchain file {item_id} bytes"
        )
        if (
            relative != expected_paths[item_id]
            or declared_hash != hashlib.sha256(raw).hexdigest()
            or declared_bytes != len(raw)
        ):
            raise ReleaseReceiptError(f"toolchain file {item_id} hash/size is stale")
    if seen != set(expected_paths):
        raise ReleaseReceiptError("Playwright toolchain manifest IDs are incomplete")


def _load_gate_result(root: Path, raw_path: object, *, scope: str) -> dict[str, Any]:
    relative, raw = _read_safe_evidence_file(
        root, raw_path, label=f"{scope} gate result"
    )
    try:
        gate_text = raw.decode("utf-8")
        _assert_evidence_safe(
            gate_text,
            label=f"{scope} gate result",
            public=scope == "public_required",
        )
        payload = json.loads(gate_text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(
            f"{scope} gate result must be valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ReleaseReceiptError(f"{scope} gate result must be a JSON object")
    if payload.get("schema_version") != GATE_RESULT_SCHEMA_VERSION:
        raise ReleaseReceiptError(
            f"{scope} gate result must use {GATE_RESULT_SCHEMA_VERSION}"
        )
    gate_id = str(payload.get("id") or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", gate_id):
        raise ReleaseReceiptError(f"{scope} gate result has an invalid id")
    if payload.get("scope") != scope:
        raise ReleaseReceiptError(f"gate {gate_id} scope does not match {scope}")
    command_id = str(payload.get("command_id") or "").strip()
    expected_command_id = GATE_POLICY.get(scope, {}).get(gate_id)
    if expected_command_id is None or command_id != expected_command_id:
        raise ReleaseReceiptError(
            f"gate {gate_id} is not allowlisted by {GATE_POLICY_VERSION} for {scope}"
        )
    if "command" in payload:
        raise ReleaseReceiptError(
            f"gate {gate_id} must use an allowlisted command_id, not free command text"
        )
    status = str(payload.get("status") or "").strip()
    if status not in {"passed", "failed", "blocked"}:
        raise ReleaseReceiptError(
            f"gate {gate_id} status must be passed, failed or blocked"
        )
    counts = {
        name: _nonnegative_int(payload.get(name), label=f"gate {gate_id} {name}")
        for name in ("passed", "failed", "skipped", "flaky", "retries")
    }
    run_id = str(payload.get("run_id") or "").strip()
    started_at = str(payload.get("started_at") or "").strip()
    finished_at = str(payload.get("finished_at") or "").strip()
    if not RUN_ID_RE.fullmatch(run_id):
        raise ReleaseReceiptError(f"gate {gate_id} run_id is invalid")
    if not _valid_created_at(started_at) or not _valid_created_at(finished_at):
        raise ReleaseReceiptError(
            f"gate {gate_id} run timestamps must be timezone-aware ISO-8601"
        )
    started_datetime = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    finished_datetime = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
    if finished_datetime < started_datetime:
        raise ReleaseReceiptError(f"gate {gate_id} run timestamps are reversed")
    if (finished_datetime - started_datetime).total_seconds() > MAX_REQUIRED_RUN_SECONDS:
        raise ReleaseReceiptError(f"gate {gate_id} run duration exceeds the policy")
    source_sha = str(payload.get("subject_sha") or "").lower()
    tree_hash = str(payload.get("tree_hash") or "").lower()
    if not SHA1_RE.fullmatch(source_sha) or not SHA1_RE.fullmatch(tree_hash):
        raise ReleaseReceiptError(
            f"gate {gate_id} must carry exact subject_sha and tree_hash"
        )
    result_hash = hashlib.sha256(raw).hexdigest()
    result_bytes = len(raw)
    fingerprint_fields = {
        "worktree_fingerprint_version": str(
            payload.get("worktree_fingerprint_version") or ""
        ),
        "worktree_fingerprint": str(payload.get("worktree_fingerprint") or "").lower(),
        "dirty": payload.get("dirty"),
        "dirty_entry_count": payload.get("dirty_entry_count"),
        "staged_patch_sha256": str(payload.get("staged_patch_sha256") or "").lower(),
        "unstaged_patch_sha256": str(
            payload.get("unstaged_patch_sha256") or ""
        ).lower(),
        "untracked_state_sha256": str(
            payload.get("untracked_state_sha256") or ""
        ).lower(),
        "untracked_entry_count": payload.get("untracked_entry_count"),
        "submodule_state_sha256": str(
            payload.get("submodule_state_sha256") or ""
        ).lower(),
    }
    if fingerprint_fields["worktree_fingerprint_version"] != FINGERPRINT_VERSION:
        raise ReleaseReceiptError(f"gate {gate_id} must use {FINGERPRINT_VERSION}")
    for name in (
        "worktree_fingerprint",
        "staged_patch_sha256",
        "unstaged_patch_sha256",
        "untracked_state_sha256",
        "submodule_state_sha256",
    ):
        if not SHA256_RE.fullmatch(str(fingerprint_fields[name])):
            raise ReleaseReceiptError(f"gate {gate_id} {name} is invalid")
    if not isinstance(fingerprint_fields["dirty"], bool):
        raise ReleaseReceiptError(f"gate {gate_id} dirty must be boolean")
    for name in ("dirty_entry_count", "untracked_entry_count"):
        _nonnegative_int(fingerprint_fields[name], label=f"gate {gate_id} {name}")
    result: dict[str, Any] = {
        "id": gate_id,
        "scope": scope,
        "command_id": command_id,
        "gate_policy_version": GATE_POLICY_VERSION,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        **counts,
        "subject_sha": source_sha,
        "tree_hash": tree_hash,
        **fingerprint_fields,
        "result_path": relative,
        "result_sha256": result_hash,
        "result_bytes": result_bytes,
    }
    run_result_path = payload.get("run_result_path")
    if run_result_path is None:
        raise ReleaseReceiptError(f"gate {gate_id} terminal run result is required")
    evidence_hash = str(payload.get("evidence_sha256") or "").lower()
    if evidence_hash:
        if not SHA256_RE.fullmatch(evidence_hash):
            raise ReleaseReceiptError(
                f"gate {gate_id} evidence_sha256 is not a SHA-256"
            )
        result["evidence_sha256"] = evidence_hash
    evidence_path = payload.get("evidence_path")
    if evidence_path is None:
        raise ReleaseReceiptError(f"gate {gate_id} raw evidence is required")
    evidence_relative, evidence_raw = _read_safe_evidence_file(
        root, evidence_path, label=f"gate {gate_id} raw evidence"
    )
    try:
        evidence_text = evidence_raw.decode("utf-8")
        _assert_evidence_safe(
            evidence_text,
            label=f"gate {gate_id} raw evidence",
            public=scope == "public_required",
        )
        evidence_payload = json.loads(evidence_text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(
            f"gate {gate_id} raw evidence must be UTF-8 JSON"
        ) from exc
    if not isinstance(evidence_payload, Mapping):
        raise ReleaseReceiptError(f"gate {gate_id} raw evidence must be a JSON object")
    raw_hash = hashlib.sha256(evidence_raw).hexdigest()
    raw_bytes = len(evidence_raw)
    if not evidence_hash:
        raise ReleaseReceiptError(
            f"gate {gate_id} evidence_path requires evidence_sha256"
        )
    if raw_hash != evidence_hash:
        raise ReleaseReceiptError(f"gate {gate_id} raw evidence hash does not match")
    declared_bytes = _nonnegative_int(
        payload.get("evidence_bytes"), label=f"gate {gate_id} evidence_bytes"
    )
    if declared_bytes != raw_bytes:
        raise ReleaseReceiptError(f"gate {gate_id} raw evidence size does not match")
    result.update(
        {
            "evidence_path": evidence_relative,
            "evidence_sha256": raw_hash,
            "evidence_bytes": raw_bytes,
        }
    )
    result_parent = Path(relative).parent.as_posix()
    if (
        Path(evidence_relative).parent.as_posix() != result_parent
        or run_id not in Path(relative).parts
    ):
        raise ReleaseReceiptError(
            f"gate {gate_id} report/result must share its unique run_id directory"
        )
    raw_supporting = payload.get("supporting_evidence", [])
    if not isinstance(raw_supporting, list):
        raise ReleaseReceiptError(f"gate {gate_id} supporting_evidence must be a list")
    supporting: list[dict[str, Any]] = []
    supporting_ids: set[str] = set()
    matrix_scope_record: Mapping[str, Any] | None = None
    matrix_contract_payload: Mapping[str, Any] | None = None
    toolchain_payload: Mapping[str, Any] | None = None
    for index, item in enumerate(raw_supporting):
        if not isinstance(item, Mapping):
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {index} must be an object"
            )
        support_id = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", support_id):
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {index} has an invalid id"
            )
        if support_id in supporting_ids:
            raise ReleaseReceiptError(
                f"gate {gate_id} has duplicate supporting evidence {support_id}"
            )
        supporting_ids.add(support_id)
        support_relative, support_raw = _read_safe_evidence_file(
            root,
            item.get("path"),
            label=f"gate {gate_id} supporting evidence {support_id}",
        )
        if support_id == "release-matrix-contract":
            if support_relative != CANONICAL_RELEASE_MATRIX_PATH:
                raise ReleaseReceiptError(
                    "release matrix contract must use the canonical repository path"
                )
            _assert_exact_tracked_path(
                root, support_relative, label="release matrix contract"
            )
        support_hash = hashlib.sha256(support_raw).hexdigest()
        support_bytes = len(support_raw)
        try:
            support_text = support_raw.decode("utf-8")
            _assert_evidence_safe(
                support_text,
                label=f"gate {gate_id} supporting evidence {support_id}",
                public=scope == "public_required",
            )
            support_payload = json.loads(support_text)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {support_id} must be UTF-8 JSON"
            ) from exc
        if not isinstance(support_payload, Mapping):
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {support_id} must be a JSON object"
            )
        declared_hash = str(item.get("sha256") or "").lower()
        declared_bytes = _nonnegative_int(
            item.get("bytes"),
            label=f"gate {gate_id} supporting evidence {support_id} bytes",
        )
        if support_hash != declared_hash or support_bytes != declared_bytes:
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {support_id} hash/size does not match"
            )
        support_record: dict[str, Any] = {
            "id": support_id,
            "path": support_relative,
            "sha256": support_hash,
            "bytes": support_bytes,
        }
        if (
            support_id != "release-matrix-contract"
            and Path(support_relative).parent.as_posix() != result_parent
        ):
            raise ReleaseReceiptError(
                f"gate {gate_id} supporting evidence {support_id} must share its unique run directory"
            )
        if support_id == "git-subject-before":
            for field in (
                "source_sha",
                "tree_hash",
                "dirty",
                "dirty_entry_count",
                "worktree_fingerprint_version",
                "worktree_fingerprint",
                "staged_patch_sha256",
                "unstaged_patch_sha256",
                "untracked_state_sha256",
                "untracked_entry_count",
                "submodule_state_sha256",
            ):
                result_field = "subject_sha" if field == "source_sha" else field
                if support_payload.get(field) != result.get(result_field):
                    raise ReleaseReceiptError(
                        f"gate {gate_id} pre-run Git subject contradicts {field}"
                    )
        if support_id in {
            "release-matrix-contract",
            "release-toolchain-manifest",
            "release-build-manifest",
            "downstream-preflight",
        }:
            expected_schema = {
                "release-matrix-contract": "wiki_playwright_release_matrix.v1",
                "release-toolchain-manifest": "wiki_playwright_toolchain_manifest.v1",
                "release-build-manifest": "wiki_release_build_manifest.v2",
                "downstream-preflight": "wiki_downstream_preflight.v2",
            }[support_id]
            if (
                not isinstance(support_payload, Mapping)
                or support_payload.get("schema_version") != expected_schema
            ):
                raise ReleaseReceiptError(
                    f"gate {gate_id} supporting evidence {support_id} must use {expected_schema}"
                )
            if support_id == "release-matrix-contract":
                _validate_release_matrix_contract(support_payload)
                matrix_scope_record = support_payload[scope]
                matrix_contract_payload = support_payload
            elif support_id == "release-toolchain-manifest":
                toolchain_payload = support_payload
            elif support_id == "release-build-manifest":
                if scope != "public_required":
                    raise ReleaseReceiptError(
                        "release build manifest belongs only to public_required"
                    )
                _validate_release_build_manifest(
                    root,
                    support_payload,
                    expected_subject_sha=source_sha,
                )
            else:
                _validate_downstream_preflight(
                    root,
                    support_payload,
                    expected_subject_sha=source_sha,
                )
            support_record["schema_version"] = expected_schema
        supporting.append(support_record)
    if toolchain_payload is not None:
        if matrix_contract_payload is None:
            raise ReleaseReceiptError(
                "release toolchain manifest requires the canonical matrix contract"
            )
        _validate_toolchain_manifest(
            root,
            toolchain_payload,
            scope=scope,
            expected_playwright_version=str(
                matrix_contract_payload.get("playwright_version") or ""
            ),
        )
    if supporting:
        result["supporting_evidence"] = supporting
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ReleaseReceiptError(f"gate {gate_id} files must be a non-empty list")
    files: list[str] = []
    for index, raw_file in enumerate(raw_files):
        if not isinstance(raw_file, str):
            raise ReleaseReceiptError(f"gate {gate_id} file {index} must be a string")
        normalized, _path_error = _canonical_portable_path(raw_file)
        is_downstream_file = bool(
            normalized and normalized.startswith("e2e/downstream/")
        )
        if (
            normalized is None
            or _portable_path_has_sensitive_name(normalized)
            or not normalized.startswith("e2e/")
            or not normalized.endswith(".spec.ts")
            or (scope == "public_required" and is_downstream_file)
            or (scope == "downstream_required" and not is_downstream_file)
        ):
            raise ReleaseReceiptError(
                f"gate {gate_id} file {index} must be a canonical in-scope spec path"
            )
        files.append(normalized)
    if len(files) != len(set(files)):
        raise ReleaseReceiptError(f"gate {gate_id} files must be duplicate-free")
    raw_cells = payload.get("test_cells")
    if (
        not isinstance(raw_cells, list)
        or not raw_cells
        or any(not isinstance(value, str) or not value for value in raw_cells)
        or len(raw_cells) != len(set(raw_cells))
    ):
        raise ReleaseReceiptError(
            f"gate {gate_id} test_cells must be a non-empty duplicate-free list"
        )
    if matrix_scope_record is None:
        raise ReleaseReceiptError(
            f"gate {gate_id} release matrix cells are unavailable"
        )
    _validate_playwright_raw_evidence(
        evidence_payload,
        scope=scope,
        matrix_scope=matrix_scope_record,
        gate=result,
    )
    expected_files = sorted(
        str(value) for value in matrix_scope_record["required_specs"]
    )
    expected_cells = sorted(str(item["id"]) for item in matrix_scope_record["cells"])
    if sorted(files) != expected_files or sorted(raw_cells) != expected_cells:
        raise ReleaseReceiptError(
            f"gate {gate_id} files/test_cells do not match the exact release matrix"
        )
    blocking_counts = any(
        counts[name] for name in ("failed", "skipped", "flaky", "retries")
    )
    if (
        status == "passed"
        and not blocking_counts
        and counts["passed"] != len(expected_cells)
    ):
        raise ReleaseReceiptError(
            f"gate {gate_id} passed counts contradict the exact release matrix"
        )
    cell_bytes = json.dumps(
        expected_cells, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    result["files"] = sorted(files)
    result["test_cell_count"] = len(expected_cells)
    result["test_cells_sha256"] = hashlib.sha256(cell_bytes).hexdigest()
    run_relative, run_raw = _read_safe_evidence_file(
        root,
        run_result_path,
        label=f"gate {gate_id} terminal run result",
    )
    if Path(run_relative).parent.as_posix() != result_parent:
        raise ReleaseReceiptError(
            f"gate {gate_id} terminal run result must share its unique run directory"
        )
    try:
        run_text = run_raw.decode("utf-8")
        _assert_evidence_safe(
            run_text,
            label=f"gate {gate_id} terminal run result",
            public=scope == "public_required",
        )
        run_payload = json.loads(run_text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(
            f"gate {gate_id} terminal run result must be UTF-8 JSON"
        ) from exc
    required_run_fields = {
        "schema_version",
        "runner_version",
        "run_id",
        "scope",
        "command_id",
        "status",
        "failure_stage",
        "exit_code",
        "started_at",
        "finished_at",
        "subject_before",
        "subject_after",
        "paths",
    }
    if not isinstance(run_payload, Mapping) or set(run_payload) != required_run_fields:
        raise ReleaseReceiptError(
            f"gate {gate_id} terminal run result fields are invalid"
        )
    run_paths = run_payload.get("paths")
    run_gate = run_paths.get("gate_result") if isinstance(run_paths, Mapping) else None
    preflight_paths = [
        str(item.get("path") or "")
        for item in supporting
        if item.get("id") == "downstream-preflight"
    ]
    expected_preflight_path: str | None = None
    if scope == "downstream_required" and len(preflight_paths) == 1:
        expected_preflight_path = preflight_paths[0]
    build_manifest_paths = [
        str(item.get("path") or "")
        for item in supporting
        if item.get("id") == "release-build-manifest"
    ]
    expected_build_manifest_path: str | None = None
    if scope == "public_required" and len(build_manifest_paths) == 1:
        expected_build_manifest_path = build_manifest_paths[0]
    expected_command = GATE_POLICY[scope][gate_id]
    if (
        run_payload.get("schema_version") != "wiki_playwright_release_run.v1"
        or run_payload.get("runner_version") != "wiki_playwright_release_runner.v1"
        or run_payload.get("run_id") != run_id
        or run_payload.get("scope") != scope
        or run_payload.get("command_id") != expected_command
        or run_payload.get("status") != "passed"
        or run_payload.get("failure_stage") is not None
        or run_payload.get("exit_code") != 0
        or run_payload.get("started_at") != started_at
        or not _valid_created_at(run_payload.get("finished_at"))
        or datetime.fromisoformat(
            str(run_payload.get("finished_at")).replace("Z", "+00:00")
        )
        < datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        or not isinstance(run_paths, Mapping)
        or set(run_paths)
        != {"report", "preflight", "build_manifest", "gate_result"}
        or run_paths.get("report") != evidence_relative
        or run_paths.get("preflight") != expected_preflight_path
        or run_paths.get("build_manifest") != expected_build_manifest_path
        or not isinstance(run_gate, Mapping)
        or set(run_gate) != {"path", "sha256", "bytes"}
        or run_gate.get("path") != relative
        or run_gate.get("sha256") != result_hash
        or run_gate.get("bytes") != result_bytes
    ):
        raise ReleaseReceiptError(
            f"gate {gate_id} terminal run result does not attest the passing gate"
        )
    terminal_finished = datetime.fromisoformat(
        str(run_payload.get("finished_at")).replace("Z", "+00:00")
    )
    if (terminal_finished - started_datetime).total_seconds() > MAX_REQUIRED_RUN_SECONDS:
        raise ReleaseReceiptError(
            f"gate {gate_id} terminal run duration exceeds the policy"
        )
    subject_before = run_payload.get("subject_before")
    subject_after = run_payload.get("subject_after")
    if not isinstance(subject_before, Mapping) or dict(subject_before) != subject_after:
        raise ReleaseReceiptError(f"gate {gate_id} terminal run subjects do not match")
    for field in (
        "source_sha",
        "tree_hash",
        "dirty",
        "dirty_entry_count",
        "worktree_fingerprint_version",
        "worktree_fingerprint",
        "staged_patch_sha256",
        "unstaged_patch_sha256",
        "untracked_state_sha256",
        "untracked_entry_count",
        "submodule_state_sha256",
    ):
        result_field = "subject_sha" if field == "source_sha" else field
        if subject_before.get(field) != result.get(result_field):
            raise ReleaseReceiptError(
                f"gate {gate_id} terminal run subject contradicts {field}"
            )
    result.update(
        {
            "run_result_path": run_relative,
            "run_result_sha256": hashlib.sha256(run_raw).hexdigest(),
            "run_result_bytes": len(run_raw),
            "_terminal_finished_at": str(run_payload.get("finished_at")),
        }
    )
    return result


def _collect_artifacts(
    root: Path,
    raw_artifacts: object,
    *,
    public: bool,
) -> list[dict[str, Any]]:
    if raw_artifacts is None:
        return []
    if not isinstance(raw_artifacts, list):
        raise ReleaseReceiptError("artifacts must be a list")
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_artifacts):
        if not isinstance(item, Mapping):
            raise ReleaseReceiptError(f"artifact {index} must be an object")
        artifact_id = str(item.get("id") or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", artifact_id):
            raise ReleaseReceiptError(f"artifact {index} has an invalid id")
        if artifact_id in seen:
            raise ReleaseReceiptError(f"duplicate artifact id: {artifact_id}")
        seen.add(artifact_id)
        relative, raw = _read_safe_evidence_file(
            root, item.get("path"), label=f"artifact {artifact_id}"
        )
        text = _assert_scannable_artifact_text(
            raw,
            label=f"artifact {artifact_id}",
            public=public,
        )
        digest = hashlib.sha256(raw).hexdigest()
        size = len(raw)
        kind = str(item.get("kind") or "").strip()
        artifact_schema = _validate_artifact_kind(
            root=root,
            kind=kind,
            relative=relative,
            text=text,
            public=public,
        )
        artifacts.append(
            {
                "id": artifact_id,
                "kind": kind,
                "artifact_schema": artifact_schema,
                "path": relative,
                "sha256": digest,
                "bytes": size,
                "content_encoding": "utf-8",
                "safety_scan": "secret_and_pii" if public else "secret",
            }
        )
    return artifacts


def _scope_blockers(
    scope: str, gates: Sequence[Mapping[str, Any]], subject: Mapping[str, Any]
) -> list[str]:
    if not gates:
        return [f"{scope}_missing"]
    blockers: list[str] = []
    expected_gate_ids = set(GATE_POLICY.get(scope, {}))
    actual_gate_ids = {
        str(gate.get("id")) for gate in gates if isinstance(gate, Mapping)
    }
    if actual_gate_ids != expected_gate_ids or len(gates) != len(expected_gate_ids):
        blockers.append(f"{scope}_gate_policy_mismatch")
    if not any(
        any(
            isinstance(item, Mapping)
            and item.get("id") == "release-matrix-contract"
            and item.get("schema_version") == "wiki_playwright_release_matrix.v1"
            for item in gate.get("supporting_evidence", [])
        )
        for gate in gates
        if isinstance(gate, Mapping)
    ):
        blockers.append(f"{scope}_release_matrix_contract_missing")
    if not any(
        any(
            isinstance(item, Mapping)
            and item.get("id") == "release-toolchain-manifest"
            and item.get("schema_version") == "wiki_playwright_toolchain_manifest.v1"
            for item in gate.get("supporting_evidence", [])
        )
        for gate in gates
        if isinstance(gate, Mapping)
    ):
        blockers.append(f"{scope}_release_toolchain_manifest_missing")
    if scope == "public_required" and not any(
        any(
            isinstance(item, Mapping)
            and item.get("id") == "release-build-manifest"
            and item.get("schema_version") == "wiki_release_build_manifest.v2"
            for item in gate.get("supporting_evidence", [])
        )
        for gate in gates
        if isinstance(gate, Mapping)
    ):
        blockers.append("public_required_release_build_manifest_missing")
    if not any(
        any(
            isinstance(item, Mapping) and item.get("id") == "git-subject-before"
            for item in gate.get("supporting_evidence", [])
        )
        for gate in gates
        if isinstance(gate, Mapping)
    ):
        blockers.append(f"{scope}_git_subject_before_missing")
    if scope == "downstream_required" and not any(
        any(
            isinstance(item, Mapping)
            and item.get("id") == "downstream-preflight"
            and item.get("schema_version") == "wiki_downstream_preflight.v2"
            for item in gate.get("supporting_evidence", [])
        )
        for gate in gates
        if isinstance(gate, Mapping)
    ):
        blockers.append("downstream_required_preflight_missing")
    for index, gate in enumerate(gates):
        required = {
            "id",
            "status",
            "passed",
            "failed",
            "skipped",
            "flaky",
            "retries",
            "subject_sha",
            "tree_hash",
            "worktree_fingerprint_version",
            "worktree_fingerprint",
            "dirty",
            "dirty_entry_count",
            "staged_patch_sha256",
            "unstaged_patch_sha256",
            "untracked_state_sha256",
            "untracked_entry_count",
            "submodule_state_sha256",
        }
        if not isinstance(gate, Mapping) or not required.issubset(gate):
            blockers.append(f"{scope}_gate_{index}_invalid")
            continue
        count_fields = ("passed", "failed", "skipped", "flaky", "retries")
        if any(
            isinstance(gate[name], bool)
            or not isinstance(gate[name], int)
            or gate[name] < 0
            for name in count_fields
        ):
            blockers.append(f"{scope}_gate_{index}_invalid")
            continue
        gate_id = re.sub(r"[^a-z0-9_-]+", "-", str(gate["id"]).lower()).strip(
            "-"
        ) or str(index)
        if gate["status"] != "passed" or gate["failed"]:
            blockers.append(f"{scope}_{gate_id}_failed")
        if gate["passed"] < 1:
            blockers.append(f"{scope}_{gate_id}_zero_passes")
        if gate["skipped"]:
            blockers.append(f"{scope}_{gate_id}_skipped")
        if gate["flaky"]:
            blockers.append(f"{scope}_{gate_id}_flaky")
        if gate["retries"]:
            blockers.append(f"{scope}_{gate_id}_retried")
        if gate["subject_sha"] != subject["source_sha"]:
            blockers.append(f"{scope}_{gate_id}_subject_mismatch")
        if gate["tree_hash"] != subject["tree_hash"]:
            blockers.append(f"{scope}_{gate_id}_tree_mismatch")
        for field in (
            "worktree_fingerprint_version",
            "worktree_fingerprint",
            "dirty",
            "dirty_entry_count",
            "staged_patch_sha256",
            "unstaged_patch_sha256",
            "untracked_state_sha256",
            "untracked_entry_count",
            "submodule_state_sha256",
        ):
            if gate.get(field) != subject.get(field):
                blockers.append(f"{scope}_{gate_id}_worktree_mismatch")
                break
    return blockers


def _scope_summary(
    scope: str, gates: list[dict[str, Any]], subject: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    blockers = _scope_blockers(scope, gates, subject)
    totals = {
        name: sum(int(gate[name]) for gate in gates)
        for name in ("passed", "failed", "skipped", "flaky", "retries")
    }
    return {
        "status": "passed" if not blockers else "blocked",
        **totals,
        "gates": gates,
    }, blockers


def _normalize_waivers(raw_waivers: object) -> list[dict[str, str]]:
    """Project waivers into a bounded, non-narrative receipt shape."""

    if raw_waivers is None:
        return []
    if not isinstance(raw_waivers, list):
        raise ReleaseReceiptError("waivers must be a list")
    allowed = {"id", "reason_code", "issue_ref", "owner_role", "expires_on"}
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_waivers):
        if not isinstance(raw, Mapping) or set(raw) != allowed:
            raise ReleaseReceiptError(
                f"waiver {index} must contain exactly {', '.join(sorted(allowed))}"
            )
        record = {key: str(raw[key]).strip() for key in sorted(allowed)}
        for key in ("id", "reason_code", "issue_ref", "owner_role"):
            if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,127}", record[key]):
                raise ReleaseReceiptError(f"waiver {index} {key} is not public-safe")
        try:
            datetime.strptime(record["expires_on"], "%Y-%m-%d")
        except ValueError as exc:
            raise ReleaseReceiptError(
                f"waiver {index} expires_on must be YYYY-MM-DD"
            ) from exc
        if record["id"] in seen:
            raise ReleaseReceiptError(f"duplicate waiver id: {record['id']}")
        seen.add(record["id"])
        normalized.append(record)
    return sorted(normalized, key=lambda item: item["id"])


def _semantic_validator_record() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    implementation_paths = (
        "scripts/_git_subject.py",
        "wiki_core/config.py",
        "wiki_core/detectors/__init__.py",
        "wiki_core/detectors/entities.py",
        "wiki_core/detectors/secrets.py",
        "wiki_core/detectors/sensitive_terms.py",
        "wiki_core/release_receipt.py",
        "wiki_core/upgrade.py",
    )
    files: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    aggregate.update(b"wiki_release_receipt_semantic_validator.bundle.v1\0")
    for relative in implementation_paths:
        digest, size = sha256_file(repo_root / relative)
        files.append({"path": relative, "sha256": digest, "bytes": size})
        encoded_path = relative.encode("utf-8")
        aggregate.update(len(encoded_path).to_bytes(4, "big"))
        aggregate.update(encoded_path)
        aggregate.update(bytes.fromhex(digest))
    try:
        pyyaml_version = package_version("PyYAML")
    except PackageNotFoundError:  # pragma: no cover - config import already needs it.
        pyyaml_version = "unavailable"
    return {
        "id": SEMANTIC_VALIDATOR_VERSION,
        "implementation_sha256": aggregate.hexdigest(),
        "implementation_files": files,
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "pyyaml_version": pyyaml_version,
        },
        "promotion_policy": "closure_only_external_authority_required",
        "gate_policy": GATE_POLICY_VERSION,
    }


def _assert_publication_safe(receipt: Mapping[str, Any]) -> None:
    digest_fields = {
        "base_sha",
        "base_tree_hash",
        "source_sha",
        "tree_hash",
        "worktree_fingerprint",
    }

    def scan_projection(value: Any, *, field: str | None = None) -> Any:
        """Keep human metadata visible while masking opaque cryptographic values.

        SHA-1/SHA-256 values are deterministic technical identifiers.  Scanning
        their random digit runs as if they were prose can occasionally satisfy
        Luhn and create a non-deterministic credit-card false positive.  Paths,
        labels, IDs, waiver metadata and every other human-controlled string
        remain in the publication scan.
        """

        if isinstance(value, Mapping):
            return {
                str(key): scan_projection(item, field=str(key))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scan_projection(item, field=field) for item in value]
        is_digest_field = bool(
            field in digest_fields
            or field == "sha"
            or field == "sha256"
            or (field and field.endswith("_sha"))
            or (field and field.endswith("_sha256"))
        )
        if (
            isinstance(value, str)
            and is_digest_field
            and (SHA1_RE.fullmatch(value.lower()) or SHA256_RE.fullmatch(value.lower()))
        ):
            return "<cryptographic-digest>"
        return value

    serialized = json.dumps(
        scan_projection(receipt), sort_keys=True, ensure_ascii=False
    )
    public = receipt.get("publication_boundary") == "public_safe"
    findings = [
        finding
        for finding in scan_text(serialized)
        if finding.category == "secret"
        or (public and finding.category in {"pii", "entity"})
    ]
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        raise ReleaseReceiptError(
            f"release receipt projection blocked by secret/PII detector: {kinds}"
        )


def build_release_receipt(
    root: Path,
    evidence: Mapping[str, Any],
    *,
    base_sha: str | None = None,
    promote_e5: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Bind normalized evidence to HEAD and decide E5 eligibility."""

    if os.name == "nt":
        raise ReleaseReceiptError(
            "release receipt compilation is unsupported on Windows until "
            "handle-pinned reparse-point traversal is available"
        )
    root = root.resolve()
    if not isinstance(evidence, Mapping):
        raise ReleaseReceiptError("evidence must be a JSON object")
    _assert_no_access_secret(
        json.dumps(evidence, sort_keys=True, ensure_ascii=False),
        label="release evidence manifest",
    )
    release_id = str(evidence.get("release_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_id):
        raise ReleaseReceiptError(
            "release_id is required and must be a safe identifier"
        )
    receipt_kind = str(evidence.get("receipt_kind") or "").strip()
    if receipt_kind not in {"public_release", "private_adoption"}:
        raise ReleaseReceiptError(
            "receipt_kind must be public_release or private_adoption"
        )
    _assert_evidence_safe(
        json.dumps(evidence, sort_keys=True, ensure_ascii=False),
        label="release evidence manifest",
        public=receipt_kind == "public_release",
    )
    timestamp = created_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    if not _valid_created_at(timestamp):
        raise ReleaseReceiptError(
            "created_at must be a timezone-aware ISO-8601 timestamp"
        )
    receipt_datetime = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    config = load_config(root)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", config.repo_id):
        raise ReleaseReceiptError("repo_id is not safe for release-receipt metadata")
    subject = collect_git_subject(root, base_sha=base_sha)
    required_scope = REQUIRED_SCOPE_BY_RECEIPT_KIND[receipt_kind]
    raw_scopes = evidence.get("test_scopes")
    if raw_scopes is None:
        raw_scopes = {}
    if not isinstance(raw_scopes, Mapping):
        raise ReleaseReceiptError("test_scopes must be an object")
    unknown_scopes = set(raw_scopes) - set(REQUIRED_SCOPES)
    if unknown_scopes:
        raise ReleaseReceiptError(
            f"unknown test scope(s): {', '.join(sorted(unknown_scopes))}"
        )

    scopes: dict[str, Any] = {}
    reason_codes: list[str] = []
    for scope in REQUIRED_SCOPES:
        raw_scope = raw_scopes.get(scope, {})
        if not isinstance(raw_scope, Mapping):
            raise ReleaseReceiptError(f"{scope} must be an object")
        raw_results = raw_scope.get("gate_results", [])
        if not isinstance(raw_results, list):
            raise ReleaseReceiptError(f"{scope}.gate_results must be a list")
        if scope != required_scope:
            if raw_results:
                raise ReleaseReceiptError(
                    f"{scope} is not applicable to {receipt_kind}; attest it in its separate repository receipt"
                )
            scopes[scope] = {
                "status": "not_applicable",
                "attestation": "separate_receipt_required",
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "flaky": 0,
                "retries": 0,
                "gates": [],
            }
            continue
        gates = [_load_gate_result(root, path, scope=scope) for path in raw_results]
        freshness_blockers: list[str] = []
        for gate in gates:
            terminal_finished_at = str(gate.pop("_terminal_finished_at"))
            terminal_finished = datetime.fromisoformat(
                terminal_finished_at.replace("Z", "+00:00")
            )
            gate_finished = datetime.fromisoformat(
                str(gate["finished_at"]).replace("Z", "+00:00")
            )
            if receipt_datetime < terminal_finished:
                raise ReleaseReceiptError(
                    f"receipt timestamp precedes terminal gate {gate['id']} completion"
                )
            if (
                receipt_datetime - gate_finished
            ).total_seconds() > MAX_GATE_TO_RECEIPT_SECONDS:
                freshness_blockers.append(f"{scope}_gate_evidence_stale")
        ids = [gate["id"] for gate in gates]
        if len(ids) != len(set(ids)):
            raise ReleaseReceiptError(f"{scope} contains duplicate gate ids")
        scopes[scope], blockers = _scope_summary(scope, gates, subject)
        if freshness_blockers:
            scopes[scope]["status"] = "blocked"
            blockers.extend(freshness_blockers)
        scopes[scope]["attestation"] = "subject_bound"
        reason_codes.extend(blockers)

    artifacts = _collect_artifacts(
        root,
        evidence.get("artifacts", []),
        public=receipt_kind == "public_release",
    )
    if not artifacts:
        reason_codes.append("release_artifacts_missing")
    review = evidence.get("review")
    if review is None:
        review = {}
    if not isinstance(review, Mapping):
        raise ReleaseReceiptError("review must be an object")
    review_record = {
        "human_product_gate": str(review.get("human_product_gate") or "pending"),
        "human_privacy_gate": str(review.get("human_privacy_gate") or "pending"),
    }
    for key, value in review_record.items():
        if value not in {"passed", "pending", "rejected"}:
            raise ReleaseReceiptError(
                f"review.{key} must be passed, pending or rejected"
            )
        if value != "passed":
            reason_codes.append(f"{key}_{value}")

    waivers = _normalize_waivers(evidence.get("waivers", []))
    if waivers:
        reason_codes.append("waivers_present")
    if subject["dirty"]:
        reason_codes.append("dirty_worktree")
    if not subject["base_sha"]:
        reason_codes.append("base_sha_missing")
    if subject["base_sha"] and not subject["base_is_ancestor"]:
        reason_codes.append("base_sha_not_ancestor")
    if promote_e5:
        # v1 deliberately binds only the browser release gate.
        # Repository-authored JSON cannot
        # prove an external human/CI authority; claiming E5 here would turn a
        # self-attestation into a signed-release claim.
        reason_codes.append("e5_external_authority_required")

    reason_codes = sorted(set(reason_codes))
    closure_passed = not reason_codes
    if subject["dirty"]:
        evidence_scope = "local_uncommitted_closure"
        promotion_status = "blocked" if promote_e5 else "not_requested"
    elif not subject["base_sha"] or not subject["base_is_ancestor"]:
        evidence_scope = "local_evidence"
        promotion_status = "blocked" if promote_e5 else "not_requested"
    else:
        evidence_scope = "browser_closure"
        promotion_status = "blocked" if promote_e5 else "not_requested"

    subject_after = collect_git_subject(root, base_sha=base_sha)
    if subject_after != subject:
        raise ReleaseReceiptError(
            "repository subject changed while release evidence was normalized"
        )
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_kind": receipt_kind,
        "publication_boundary": (
            "public_safe" if receipt_kind == "public_release" else "private_internal"
        ),
        "release_id": release_id,
        "created_at": timestamp,
        "evidence_scope": evidence_scope,
        "overall_status": "passed" if closure_passed else "blocked",
        "reason_codes": reason_codes,
        "semantic_validator": _semantic_validator_record(),
        "subject": {
            "repository": config.repo_id,
            **subject_after,
        },
        "artifacts": artifacts,
        "test_scopes": scopes,
        "waivers": waivers,
        "review": review_record,
        "promotion": {
            "requested": "E5" if promote_e5 else "evidence_only",
            "eligible": False,
            "status": promotion_status,
        },
    }
    _assert_publication_safe(receipt)
    return receipt


def _mapping_keys_error(
    value: object,
    *,
    label: str,
    required: set[str],
    optional: set[str] | None = None,
) -> str | None:
    if not isinstance(value, Mapping):
        return f"{label} must be an object"
    keys = set(value)
    allowed = required | (optional or set())
    missing = required - keys
    extra = keys - allowed
    if missing or extra:
        detail: list[str] = []
        if missing:
            detail.append(f"missing {', '.join(sorted(missing))}")
        if extra:
            detail.append(f"unexpected {', '.join(sorted(extra))}")
        return f"{label} fields are invalid ({'; '.join(detail)})"
    return None


def _portable_metadata_path(value: object, *, sensitive: bool = True) -> bool:
    if not isinstance(value, str):
        return False
    normalized, _error = _canonical_portable_path(value)
    if normalized is None or normalized != value:
        return False
    return not sensitive or not _portable_path_has_sensitive_name(normalized)


def _valid_created_at(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _structural_errors(receipt: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    top_required = {
        "schema_version",
        "receipt_kind",
        "publication_boundary",
        "release_id",
        "created_at",
        "evidence_scope",
        "overall_status",
        "reason_codes",
        "semantic_validator",
        "subject",
        "artifacts",
        "test_scopes",
        "waivers",
        "review",
        "promotion",
    }
    top_error = _mapping_keys_error(receipt, label="receipt", required=top_required)
    if top_error:
        errors.append(top_error)
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {RECEIPT_SCHEMA_VERSION}")
    if receipt.get("receipt_kind") not in {"public_release", "private_adoption"}:
        errors.append("receipt_kind is invalid")
    expected_boundary = {
        "public_release": "public_safe",
        "private_adoption": "private_internal",
    }.get(receipt.get("receipt_kind"))
    if receipt.get("publication_boundary") != expected_boundary:
        errors.append("publication_boundary contradicts receipt_kind")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(receipt.get("release_id") or "")
    ):
        errors.append("release_id is invalid")
    if not _valid_created_at(receipt.get("created_at")):
        errors.append("created_at must be a timezone-aware ISO-8601 timestamp")
    if receipt.get("evidence_scope") not in {
        "local_uncommitted_closure",
        "local_evidence",
        "browser_closure",
    }:
        errors.append("evidence_scope is invalid; v1 is browser-evidence-only")
    if receipt.get("overall_status") not in {"passed", "blocked"}:
        errors.append("overall_status is invalid")
    reason_codes = receipt.get("reason_codes")
    if (
        not isinstance(reason_codes, list)
        or any(
            not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_-]+", code)
            for code in reason_codes
        )
        or reason_codes != sorted(set(reason_codes))
    ):
        errors.append("reason_codes must be sorted, unique, lowercase safe identifiers")

    semantic = receipt.get("semantic_validator")
    semantic_error = _mapping_keys_error(
        semantic,
        label="semantic_validator",
        required={
            "id",
            "implementation_sha256",
            "implementation_files",
            "runtime",
            "promotion_policy",
            "gate_policy",
        },
    )
    if semantic_error:
        errors.append(semantic_error)
    elif (
        semantic.get("id") != SEMANTIC_VALIDATOR_VERSION
        or semantic.get("promotion_policy")
        != "closure_only_external_authority_required"
        or semantic.get("gate_policy") != GATE_POLICY_VERSION
        or not SHA256_RE.fullmatch(str(semantic.get("implementation_sha256") or ""))
    ):
        errors.append("semantic_validator metadata is invalid")
    elif (
        not isinstance(semantic.get("implementation_files"), list)
        or not semantic["implementation_files"]
        or any(
            not isinstance(item, Mapping) for item in semantic["implementation_files"]
        )
        or any(
            _mapping_keys_error(
                item,
                label="semantic validator implementation file",
                required={"path", "sha256", "bytes"},
            )
            or not _portable_metadata_path(item.get("path"), sensitive=False)
            or not SHA256_RE.fullmatch(str(item.get("sha256") or ""))
            or not _valid_count(item.get("bytes"))
            for item in semantic["implementation_files"]
            if isinstance(item, Mapping)
        )
        or not isinstance(semantic.get("runtime"), Mapping)
        or set(semantic["runtime"])
        != {"python_implementation", "python_version", "pyyaml_version"}
        or any(
            not isinstance(value, str) or not value
            for value in semantic["runtime"].values()
        )
    ):
        errors.append("semantic_validator implementation bundle is invalid")

    subject = receipt.get("subject")
    subject_required = {
        "repository",
        "source_sha",
        "tree_hash",
        "dirty",
        "dirty_entry_count",
        "worktree_fingerprint_version",
        "worktree_fingerprint",
        "staged_patch_sha256",
        "unstaged_patch_sha256",
        "untracked_state_sha256",
        "untracked_entry_count",
        "submodule_state_sha256",
        "base_sha",
        "base_tree_hash",
        "base_is_ancestor",
    }
    subject_error = _mapping_keys_error(
        subject, label="subject", required=subject_required
    )
    if subject_error:
        errors.append(subject_error)
    if isinstance(subject, Mapping):
        repository = subject.get("repository")
        if (
            not isinstance(repository, str)
            or not repository.strip()
            or repository != repository.strip()
        ):
            errors.append("subject.repository must be a non-empty canonical string")
        if not SHA1_RE.fullmatch(str(subject.get("source_sha") or "")):
            errors.append("subject.source_sha is invalid")
        if not SHA1_RE.fullmatch(str(subject.get("tree_hash") or "")):
            errors.append("subject.tree_hash is invalid")
        if not isinstance(subject.get("dirty"), bool):
            errors.append("subject.dirty must be boolean")
        if not _valid_count(subject.get("dirty_entry_count")):
            errors.append("subject.dirty_entry_count must be a non-negative integer")
        if subject.get("worktree_fingerprint_version") != FINGERPRINT_VERSION:
            errors.append("subject.worktree_fingerprint_version is invalid")
        for field in (
            "worktree_fingerprint",
            "staged_patch_sha256",
            "unstaged_patch_sha256",
            "untracked_state_sha256",
            "submodule_state_sha256",
        ):
            if not SHA256_RE.fullmatch(str(subject.get(field) or "")):
                errors.append(f"subject.{field} is invalid")
        if not _valid_count(subject.get("untracked_entry_count")):
            errors.append(
                "subject.untracked_entry_count must be a non-negative integer"
            )
        base_sha = subject.get("base_sha")
        base_tree = subject.get("base_tree_hash")
        base_ancestor = subject.get("base_is_ancestor")
        if base_sha is None:
            if base_tree is not None or base_ancestor is not None:
                errors.append(
                    "subject base fields must all be null when base_sha is null"
                )
        elif (
            not SHA1_RE.fullmatch(str(base_sha))
            or not SHA1_RE.fullmatch(str(base_tree or ""))
            or not isinstance(base_ancestor, bool)
        ):
            errors.append(
                "subject base fields must carry an exact SHA/tree/ancestor attestation"
            )

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        artifact_ids: list[str] = []
        artifact_required = {
            "id",
            "kind",
            "artifact_schema",
            "path",
            "sha256",
            "bytes",
            "content_encoding",
            "safety_scan",
        }
        for index, artifact in enumerate(artifacts):
            artifact_error = _mapping_keys_error(
                artifact, label=f"artifact {index}", required=artifact_required
            )
            if artifact_error:
                errors.append(artifact_error)
                continue
            artifact_id = str(artifact.get("id") or "")
            artifact_ids.append(artifact_id)
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", artifact_id):
                errors.append(f"artifact {index} id is invalid")
            if not isinstance(artifact.get("kind"), str) or not artifact["kind"]:
                errors.append(f"artifact {artifact_id or index} kind is invalid")
            elif artifact.get("artifact_schema") != ARTIFACT_KIND_SCHEMAS.get(
                artifact["kind"]
            ):
                errors.append(f"artifact {artifact_id or index} schema is invalid")
            if not _portable_metadata_path(artifact.get("path")):
                errors.append(
                    f"artifact {artifact_id or index} path is not portable/safe"
                )
            if not SHA256_RE.fullmatch(str(artifact.get("sha256") or "")):
                errors.append(f"artifact {artifact_id or index} sha256 is invalid")
            if not _valid_count(artifact.get("bytes")):
                errors.append(f"artifact {artifact_id or index} bytes is invalid")
            if artifact.get("content_encoding") != "utf-8":
                errors.append(f"artifact {artifact_id or index} encoding is invalid")
            expected_scan = (
                "secret_and_pii"
                if receipt.get("receipt_kind") == "public_release"
                else "secret"
            )
            if artifact.get("safety_scan") != expected_scan:
                errors.append(f"artifact {artifact_id or index} safety scan is invalid")
        if len(artifact_ids) != len(set(artifact_ids)):
            errors.append("artifact ids must be unique")

    scopes = receipt.get("test_scopes")
    if not isinstance(scopes, Mapping) or set(scopes) != set(REQUIRED_SCOPES):
        errors.append(
            "test_scopes must contain exactly public_required and downstream_required"
        )
    else:
        scope_required = {
            "status",
            "attestation",
            "passed",
            "failed",
            "skipped",
            "flaky",
            "retries",
            "gates",
        }
        gate_required = {
            "id",
            "scope",
            "command_id",
            "gate_policy_version",
            "run_id",
            "started_at",
            "finished_at",
            "status",
            "passed",
            "failed",
            "skipped",
            "flaky",
            "retries",
            "subject_sha",
            "tree_hash",
            "worktree_fingerprint_version",
            "worktree_fingerprint",
            "dirty",
            "dirty_entry_count",
            "staged_patch_sha256",
            "unstaged_patch_sha256",
            "untracked_state_sha256",
            "untracked_entry_count",
            "submodule_state_sha256",
            "result_path",
            "result_sha256",
            "result_bytes",
            "run_result_path",
            "run_result_sha256",
            "run_result_bytes",
            "evidence_path",
            "evidence_sha256",
            "evidence_bytes",
            "supporting_evidence",
            "files",
            "test_cell_count",
            "test_cells_sha256",
        }
        gate_optional: set[str] = set()
        required_scope = REQUIRED_SCOPE_BY_RECEIPT_KIND.get(
            str(receipt.get("receipt_kind") or "")
        )
        for scope in REQUIRED_SCOPES:
            record = scopes[scope]
            scope_error = _mapping_keys_error(
                record, label=scope, required=scope_required
            )
            if scope_error:
                errors.append(scope_error)
                continue
            expected_statuses = (
                {"passed", "blocked"} if scope == required_scope else {"not_applicable"}
            )
            if record.get("status") not in expected_statuses:
                errors.append(f"{scope}.status is invalid")
            expected_attestation = (
                "subject_bound"
                if scope == required_scope
                else "separate_receipt_required"
            )
            if record.get("attestation") != expected_attestation:
                errors.append(f"{scope}.attestation is invalid")
            for field in ("passed", "failed", "skipped", "flaky", "retries"):
                if not _valid_count(record.get(field)):
                    errors.append(f"{scope}.{field} is invalid")
            gates = record.get("gates")
            if not isinstance(gates, list):
                errors.append(f"{scope}.gates must be a list")
                continue
            if scope != required_scope and (
                gates
                or any(
                    record.get(field) != 0
                    for field in ("passed", "failed", "skipped", "flaky", "retries")
                )
            ):
                errors.append(
                    f"{scope} must be an empty not-applicable separate attestation"
                )
                continue
            gate_ids: list[str] = []
            for index, gate in enumerate(gates):
                gate_error = _mapping_keys_error(
                    gate,
                    label=f"{scope} gate {index}",
                    required=gate_required,
                    optional=gate_optional,
                )
                if gate_error:
                    errors.append(gate_error)
                    continue
                gate_id = str(gate.get("id") or "")
                gate_ids.append(gate_id)
                if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", gate_id):
                    errors.append(f"{scope} gate {index} id is invalid")
                if gate.get("scope") != scope:
                    errors.append(f"gate {gate_id or index} scope is invalid")
                expected_command_id = GATE_POLICY.get(scope, {}).get(gate_id)
                if gate.get("command_id") != expected_command_id:
                    errors.append(
                        f"gate {gate_id or index} command_id is not allowlisted"
                    )
                if gate.get("gate_policy_version") != GATE_POLICY_VERSION:
                    errors.append(
                        f"gate {gate_id or index} gate_policy_version is invalid"
                    )
                if not RUN_ID_RE.fullmatch(str(gate.get("run_id") or "")):
                    errors.append(f"gate {gate_id or index} run_id is invalid")
                if not _valid_created_at(
                    gate.get("started_at")
                ) or not _valid_created_at(gate.get("finished_at")):
                    errors.append(f"gate {gate_id or index} timestamps are invalid")
                else:
                    gate_started = datetime.fromisoformat(
                        str(gate.get("started_at")).replace("Z", "+00:00")
                    )
                    gate_finished = datetime.fromisoformat(
                        str(gate.get("finished_at")).replace("Z", "+00:00")
                    )
                    duration = (gate_finished - gate_started).total_seconds()
                    if duration < 0 or duration > MAX_REQUIRED_RUN_SECONDS:
                        errors.append(
                            f"gate {gate_id or index} timestamp duration is invalid"
                        )
                if gate.get("status") not in {"passed", "failed", "blocked"}:
                    errors.append(f"gate {gate_id or index} status is invalid")
                for field in (
                    "passed",
                    "failed",
                    "skipped",
                    "flaky",
                    "retries",
                    "dirty_entry_count",
                    "untracked_entry_count",
                    "result_bytes",
                    "run_result_bytes",
                    "evidence_bytes",
                    "test_cell_count",
                ):
                    if not _valid_count(gate.get(field)):
                        errors.append(f"gate {gate_id or index} {field} is invalid")
                for field in ("subject_sha", "tree_hash"):
                    if not SHA1_RE.fullmatch(str(gate.get(field) or "")):
                        errors.append(f"gate {gate_id or index} {field} is invalid")
                if gate.get("worktree_fingerprint_version") != FINGERPRINT_VERSION:
                    errors.append(
                        f"gate {gate_id or index} worktree_fingerprint_version is invalid"
                    )
                if not isinstance(gate.get("dirty"), bool):
                    errors.append(f"gate {gate_id or index} dirty is invalid")
                for field in (
                    "worktree_fingerprint",
                    "staged_patch_sha256",
                    "unstaged_patch_sha256",
                    "untracked_state_sha256",
                    "submodule_state_sha256",
                ):
                    if not SHA256_RE.fullmatch(str(gate.get(field) or "")):
                        errors.append(f"gate {gate_id or index} {field} is invalid")
                if not _portable_metadata_path(gate.get("result_path")):
                    errors.append(
                        f"gate {gate_id or index} result_path is not portable/safe"
                    )
                if not SHA256_RE.fullmatch(str(gate.get("result_sha256") or "")):
                    errors.append(f"gate {gate_id or index} result_sha256 is invalid")
                if not _portable_metadata_path(gate.get("run_result_path")):
                    errors.append(
                        f"gate {gate_id or index} run_result_path is not portable/safe"
                    )
                if not SHA256_RE.fullmatch(str(gate.get("run_result_sha256") or "")):
                    errors.append(
                        f"gate {gate_id or index} run_result_sha256 is invalid"
                    )
                if not _portable_metadata_path(gate.get("evidence_path")):
                    errors.append(
                        f"gate {gate_id or index} evidence_path is not portable/safe"
                    )
                if not SHA256_RE.fullmatch(str(gate.get("evidence_sha256") or "")):
                    errors.append(f"gate {gate_id or index} evidence_sha256 is invalid")
                if not SHA256_RE.fullmatch(str(gate.get("test_cells_sha256") or "")):
                    errors.append(
                        f"gate {gate_id or index} test_cells_sha256 is invalid"
                    )
                files = gate.get("files", [])
                if (
                    not isinstance(files, list)
                    or any(not isinstance(value, str) for value in files)
                    or len(files) != len(set(files))
                    or any(
                        not _portable_metadata_path(value, sensitive=True)
                        for value in files
                    )
                ):
                    errors.append(f"gate {gate_id or index} files are invalid")
                supporting = gate.get("supporting_evidence", [])
                if not isinstance(supporting, list):
                    errors.append(
                        f"gate {gate_id or index} supporting_evidence must be a list"
                    )
                else:
                    support_ids: list[str] = []
                    for support_index, item in enumerate(supporting):
                        item_error = _mapping_keys_error(
                            item,
                            label=f"gate {gate_id or index} supporting evidence {support_index}",
                            required={"id", "path", "sha256", "bytes"},
                            optional={"schema_version"},
                        )
                        if item_error:
                            errors.append(item_error)
                            continue
                        support_id = str(item.get("id") or "")
                        support_ids.append(support_id)
                        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", support_id):
                            errors.append(
                                f"gate {gate_id or index} supporting evidence id is invalid"
                            )
                        if not _portable_metadata_path(item.get("path")):
                            errors.append(
                                f"gate {gate_id or index} supporting evidence path is unsafe"
                            )
                        if not SHA256_RE.fullmatch(str(item.get("sha256") or "")):
                            errors.append(
                                f"gate {gate_id or index} supporting evidence sha256 is invalid"
                            )
                        if not _valid_count(item.get("bytes")):
                            errors.append(
                                f"gate {gate_id or index} supporting evidence bytes is invalid"
                            )
                        expected_support_schema = {
                            "release-matrix-contract": "wiki_playwright_release_matrix.v1",
                            "release-toolchain-manifest": "wiki_playwright_toolchain_manifest.v1",
                            "release-build-manifest": "wiki_release_build_manifest.v2",
                            "downstream-preflight": "wiki_downstream_preflight.v2",
                        }.get(support_id)
                        if (
                            expected_support_schema
                            and item.get("schema_version") != expected_support_schema
                        ):
                            errors.append(
                                f"gate {gate_id or index} supporting evidence {support_id} schema is invalid"
                            )
                    if len(support_ids) != len(set(support_ids)):
                        errors.append(
                            f"gate {gate_id or index} supporting evidence ids must be unique"
                        )
            if len(gate_ids) != len(set(gate_ids)):
                errors.append(f"{scope} gate ids must be unique")

    waivers = receipt.get("waivers")
    if not isinstance(waivers, list):
        errors.append("waivers must be a list")
    else:
        waiver_ids: list[str] = []
        waiver_keys = {"id", "reason_code", "issue_ref", "owner_role", "expires_on"}
        for index, waiver in enumerate(waivers):
            waiver_error = _mapping_keys_error(
                waiver, label=f"waiver {index}", required=waiver_keys
            )
            if waiver_error:
                errors.append(waiver_error)
                continue
            waiver_ids.append(str(waiver.get("id") or ""))
            for field in ("id", "reason_code", "issue_ref", "owner_role"):
                if not re.fullmatch(
                    r"[a-z0-9][a-z0-9._:-]{0,127}", str(waiver.get(field) or "")
                ):
                    errors.append(f"waiver {index} {field} is invalid")
            try:
                datetime.strptime(str(waiver.get("expires_on") or ""), "%Y-%m-%d")
            except ValueError:
                errors.append(f"waiver {index} expires_on is invalid")
        if waiver_ids != sorted(set(waiver_ids)):
            errors.append("waiver ids must be sorted and unique")
    review = receipt.get("review")
    review_error = _mapping_keys_error(
        review,
        label="review",
        required={"human_product_gate", "human_privacy_gate"},
    )
    if review_error:
        errors.append(review_error)
    elif any(review[key] not in {"passed", "pending", "rejected"} for key in review):
        errors.append("review gate values are invalid")
    promotion = receipt.get("promotion")
    promotion_error = _mapping_keys_error(
        promotion,
        label="promotion",
        required={"requested", "eligible", "status"},
    )
    if promotion_error:
        errors.append(promotion_error)
    elif (
        promotion.get("requested") not in {"evidence_only", "E5"}
        or promotion.get("eligible") is not False
        or promotion.get("status") not in {"not_requested", "blocked"}
    ):
        errors.append("promotion values are invalid for browser-evidence-only v1")
    return errors


def validate_release_receipt(
    receipt: Mapping[str, Any],
    *,
    root: Path | None = None,
    require_e5: bool = False,
) -> list[str]:
    """Validate schema, internal truth, evidence hashes and current subject."""

    if root is not None and os.name == "nt":
        return [
            "release receipt evidence validation is unsupported on Windows until "
            "handle-pinned reparse-point traversal is available"
        ]
    if not isinstance(receipt, Mapping):
        return ["receipt must be a JSON object"]
    errors = _structural_errors(receipt)
    if errors:
        return errors
    subject = receipt["subject"]
    scopes = receipt["test_scopes"]
    derived_blockers: list[str] = []
    required_scope = REQUIRED_SCOPE_BY_RECEIPT_KIND[str(receipt["receipt_kind"])]
    receipt_datetime = datetime.fromisoformat(
        str(receipt["created_at"]).replace("Z", "+00:00")
    )
    for scope in REQUIRED_SCOPES:
        record = scopes[scope]
        if not isinstance(record, Mapping) or not isinstance(record.get("gates"), list):
            errors.append(f"{scope} must carry a gates list")
            continue
        gates = record["gates"]
        if scope != required_scope:
            if (
                record.get("status") != "not_applicable"
                or record.get("attestation") != "separate_receipt_required"
                or gates
                or any(
                    record.get(field) != 0
                    for field in ("passed", "failed", "skipped", "flaky", "retries")
                )
            ):
                errors.append(f"{scope} contradicts its separate-receipt boundary")
            continue
        scope_blockers = _scope_blockers(scope, gates, subject)
        for gate in gates:
            gate_finished = datetime.fromisoformat(
                str(gate.get("finished_at")).replace("Z", "+00:00")
            )
            if receipt_datetime < gate_finished:
                errors.append(
                    f"receipt created_at precedes gate {gate.get('id')} completion"
                )
            elif (
                receipt_datetime - gate_finished
            ).total_seconds() > MAX_GATE_TO_RECEIPT_SECONDS:
                scope_blockers.append(f"{scope}_gate_evidence_stale")
        derived_blockers.extend(scope_blockers)
        expected_scope_status = "passed" if not scope_blockers else "blocked"
        if record.get("status") != expected_scope_status:
            errors.append(f"{scope}.status contradicts its gates")
        for field in ("passed", "failed", "skipped", "flaky", "retries"):
            values = [gate.get(field) for gate in gates if isinstance(gate, Mapping)]
            if len(values) != len(gates) or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in values
            ):
                errors.append(f"{scope}.{field} has an invalid gate count")
                continue
            actual = sum(values)
            if record.get(field) != actual:
                errors.append(f"{scope}.{field} does not equal its gate total")
    if not receipt.get("artifacts"):
        derived_blockers.append("release_artifacts_missing")
    review = receipt.get("review") or {}
    for key in ("human_product_gate", "human_privacy_gate"):
        value = review.get(key)
        if value != "passed":
            derived_blockers.append(f"{key}_{value or 'pending'}")
    if receipt.get("waivers"):
        derived_blockers.append("waivers_present")
    if subject.get("dirty"):
        derived_blockers.append("dirty_worktree")
    if not subject.get("base_sha"):
        derived_blockers.append("base_sha_missing")
    elif not subject.get("base_is_ancestor"):
        derived_blockers.append("base_sha_not_ancestor")
    if receipt.get("promotion", {}).get("requested") == "E5":
        derived_blockers.append("e5_external_authority_required")
    derived_blockers = sorted(set(derived_blockers))
    if sorted(set(receipt.get("reason_codes") or [])) != derived_blockers:
        errors.append("reason_codes do not match the receipt evidence")
    closure_passed = not derived_blockers
    if receipt.get("overall_status") != ("passed" if closure_passed else "blocked"):
        errors.append("overall_status contradicts the receipt evidence")
    promotion = receipt.get("promotion") or {}
    if promotion.get("eligible") is not False:
        errors.append("promotion.eligible must remain false in browser-evidence-only v1")
    requested_e5 = promotion.get("requested") == "E5"
    expected_promotion_status = "blocked" if requested_e5 else "not_requested"
    if promotion.get("status") != expected_promotion_status:
        errors.append("promotion.status contradicts requested scope and eligibility")
    if subject.get("dirty"):
        expected_evidence_scope = "local_uncommitted_closure"
    elif not subject.get("base_sha") or not subject.get("base_is_ancestor"):
        expected_evidence_scope = "local_evidence"
    else:
        expected_evidence_scope = "browser_closure"
    if receipt.get("evidence_scope") != expected_evidence_scope:
        errors.append("evidence_scope contradicts promotion and dirty state")
    if receipt.get("evidence_scope") == E5_SCOPE:
        errors.append("wiki_release_receipt.v1 cannot claim E5")
    if require_e5:
        errors.append(
            "E5 requires an external signed authority; v1 receipts bind browser evidence only"
        )

    if root is not None:
        root = root.resolve()
        try:
            current = collect_git_subject(root, base_sha=subject.get("base_sha"))
        except ReleaseReceiptError as exc:
            errors.append(str(exc))
            return errors
        try:
            current_repo_id = load_config(root).repo_id
            if subject.get("repository") != current_repo_id:
                errors.append(
                    "subject.repository does not match the current repository"
                )
        except (OSError, ValueError) as exc:
            errors.append(f"repository config could not be verified: {exc}")
        for key in (
            "source_sha",
            "tree_hash",
            "dirty",
            "dirty_entry_count",
            "worktree_fingerprint_version",
            "worktree_fingerprint",
            "staged_patch_sha256",
            "unstaged_patch_sha256",
            "untracked_state_sha256",
            "untracked_entry_count",
            "submodule_state_sha256",
            "base_sha",
            "base_tree_hash",
            "base_is_ancestor",
        ):
            if subject.get(key) != current.get(key):
                errors.append(f"subject.{key} does not match the current repository")
        expected_semantic = _semantic_validator_record()
        if receipt.get("semantic_validator") != expected_semantic:
            errors.append(
                "semantic_validator implementation does not match this validator"
            )
        artifact_public = receipt.get("receipt_kind") == "public_release"
        for artifact in receipt["artifacts"]:
            try:
                relative, raw = _read_safe_evidence_file(
                    root, artifact.get("path"), label=f"artifact {artifact.get('id')}"
                )
                digest = hashlib.sha256(raw).hexdigest()
                size = len(raw)
                if (
                    artifact.get("path") != relative
                    or artifact.get("sha256") != digest
                    or artifact.get("bytes") != size
                ):
                    errors.append(
                        f"artifact {artifact.get('id')} hash/size does not match its file"
                    )
                text = _assert_scannable_artifact_text(
                    raw,
                    label=f"artifact {artifact.get('id')}",
                    public=artifact_public,
                )
                expected_artifact_schema = _validate_artifact_kind(
                    root=root,
                    kind=str(artifact.get("kind") or ""),
                    relative=relative,
                    text=text,
                    public=artifact_public,
                )
                if artifact.get("artifact_schema") != expected_artifact_schema:
                    errors.append(
                        f"artifact {artifact.get('id')} schema does not match its file"
                    )
            except ReleaseReceiptError as exc:
                errors.append(str(exc))
        for scope in (required_scope,):
            for gate in scopes[scope]["gates"]:
                try:
                    loaded = _load_gate_result(
                        root, gate.get("result_path"), scope=scope
                    )
                    terminal_finished_at = str(
                        loaded.pop("_terminal_finished_at")
                    )
                    terminal_finished = datetime.fromisoformat(
                        terminal_finished_at.replace("Z", "+00:00")
                    )
                    if receipt_datetime < terminal_finished:
                        errors.append(
                            f"receipt created_at precedes terminal gate {gate.get('id')} completion"
                        )
                    if dict(gate) != loaded:
                        errors.append(
                            f"gate {gate.get('id')} does not match its normalized result file"
                        )
                except ReleaseReceiptError as exc:
                    errors.append(str(exc))
        try:
            _assert_publication_safe(receipt)
        except ReleaseReceiptError as exc:
            errors.append(str(exc))
    return errors


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if os.name == "nt":
        raise ReleaseReceiptError(
            "release evidence loading is unsupported on Windows until "
            "handle-pinned reparse-point traversal is available"
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReleaseReceiptError(
                f"{label} must be a regular, non-hard-linked file"
            )
        if before.st_size > MAX_EVIDENCE_BYTES:
            raise ReleaseReceiptError(
                f"{label} exceeds the {MAX_EVIDENCE_BYTES}-byte evidence limit"
            )
        raw = os.read(descriptor, MAX_EVIDENCE_BYTES + 1)
        after = os.fstat(descriptor)
        if len(raw) > MAX_EVIDENCE_BYTES or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise ReleaseReceiptError(f"{label} changed while it was read")
        text = raw.decode("utf-8")
        _assert_no_access_secret(text, label=label)
        payload = json.loads(text)
    except ReleaseReceiptError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseReceiptError(f"{label} must be valid UTF-8 JSON: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise ReleaseReceiptError(f"{label} must be a JSON object")
    return payload
