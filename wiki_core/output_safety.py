"""Safety boundary for generated output directories.

Generators may replace their own disposable trees, but they must never infer
that an arbitrary directory is disposable merely because the caller supplied
its path.  This module provides one contract for snapshot, deploy and OKF
outputs:

* the resolved target stays below the repository root (and is never the root);
* symlink targets are rejected;
* a non-empty directory needs a matching ownership marker;
* adopting an older/unmarked directory requires an explicit force flag.

The marker is deterministic and intentionally contains no host-specific path,
so generated outputs remain reproducible and portable inside the repository.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable


OUTPUT_OWNER_FILENAME = ".wiki-viva-output.json"
OUTPUT_OWNER_SCHEMA_VERSION = "wiki_viva_managed_output.v1"


def contained_output_path(root: Path, target: Path) -> Path:
    """Return the resolved target or reject an escaped/destructive path."""

    root_resolved = root.resolve()
    if target.is_symlink():
        raise ValueError(f"generated output cannot be a symlink: {target}")
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"generated output must stay inside repository root: {target}"
        ) from exc
    if target_resolved == root_resolved:
        raise ValueError("generated output cannot replace the repository root")
    return target_resolved


def _owner_payload(*, kind: str, repo_id: str) -> dict[str, str]:
    return {
        "schema_version": OUTPUT_OWNER_SCHEMA_VERSION,
        "kind": kind,
        "repo_id": repo_id,
    }


def read_output_owner(directory: Path) -> dict[str, str] | None:
    marker = directory / OUTPUT_OWNER_FILENAME
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): str(value) for key, value in payload.items()}


def output_is_owned(directory: Path, *, kind: str, repo_id: str) -> bool:
    return read_output_owner(directory) == _owner_payload(kind=kind, repo_id=repo_id)


def validate_managed_output_target(
    root: Path,
    target: Path,
    *,
    kind: str,
    repo_id: str,
    force_unowned: bool = False,
    recognize_legacy: Callable[[Path], bool] | None = None,
) -> Path:
    """Validate ownership without mutating the target.

    ``force_unowned`` is deliberately explicit at every public call site.  It
    may adopt an unmarked directory only after containment has succeeded.
    """

    resolved = contained_output_path(root, target)
    if not resolved.exists():
        return resolved
    if not resolved.is_dir():
        raise ValueError(f"generated output must be a directory: {target}")
    if not any(resolved.iterdir()):
        return resolved
    if output_is_owned(resolved, kind=kind, repo_id=repo_id):
        return resolved
    if recognize_legacy is not None and recognize_legacy(resolved):
        return resolved
    if force_unowned:
        return resolved
    raise ValueError(
        f"refusing unowned non-empty generated output directory: {target}; "
        "use the explicit force-unowned-output option only after reviewing its contents"
    )


def write_output_owner(directory: Path, *, kind: str, repo_id: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / OUTPUT_OWNER_FILENAME
    temporary = marker.with_name(f".{marker.name}.tmp")
    temporary.write_text(
        json.dumps(
            _owner_payload(kind=kind, repo_id=repo_id),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)
    return marker


def prepare_managed_output_directory(
    root: Path,
    target: Path,
    *,
    kind: str,
    repo_id: str,
    clean: bool,
    force_unowned: bool = False,
) -> Path:
    """Validate, optionally clean, create and mark an output directory."""

    resolved = validate_managed_output_target(
        root,
        target,
        kind=kind,
        repo_id=repo_id,
        force_unowned=force_unowned,
    )
    if clean and resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)
    write_output_owner(resolved, kind=kind, repo_id=repo_id)
    return resolved
