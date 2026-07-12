from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import stat
import subprocess
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from wiki_core.action_transition import (
    ActionTransitionError,
    transition_action_page,
)
from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.briefs import BriefStore, compose_and_save, compose_return_brief
from wiki_core.web.codex_jobs import JobRunner
from wiki_core.web.codex_probe import probe_codex_for
from wiki_core.web.commands import run_action
from wiki_core.web.content import build_page_content
from wiki_core.web.diff import file_diff
from wiki_core.web.gates import run_gate
from wiki_core.web.intake import intake_copy
from wiki_core.web.git_workflows import run_git_workflow
from wiki_core.web.ingestion_plan import build_ingestion_plan, run_ingestion_step
from wiki_core.web.schemas import (
    SCHEMA_CAPABILITIES,
    WEB_OPERATOR_SECURITY_VERSION,
    WEB_SERVER_VERSION,
)
from wiki_core.web.snapshot import (
    build_snapshot,
    snapshot_publication_status,
    write_snapshot,
)
from wiki_core.web.source_triage import triage_source


OPERATOR_NONCE_HEADER = "X-Wiki-Operator-Nonce"
ATTEMPT_KEY_HEADER = "X-Wiki-Attempt-Key"
MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_ATTEMPT_RECEIPTS = 512
ATTEMPT_RECEIPT_TTL_S = 3_600
ATTEMPT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SNAPSHOT_EXTERNAL_FRESHNESS_VERSION = "wiki_snapshot_external_freshness.v1"


@dataclass(frozen=True)
class _SnapshotSourceRevision:
    """Opaque repository revision used only to validate the live cache.

    The digest is deliberately never returned by the HTTP API.  Its inputs can
    contain private repository-relative names; health exposes the algorithm and
    outcome, not those names or the resulting fingerprint.
    """

    digest: str
    complete: bool
    write_in_progress: bool
    unsafe_input: bool


@dataclass(frozen=True)
class _SnapshotCacheEntry:
    built_monotonic: float
    revision: str
    payloads: dict[str, dict[str, Any]]


class SnapshotSourceUnstableError(RuntimeError):
    """No coherent live snapshot can be served for the current source write."""


class SnapshotConfigurationChangedError(RuntimeError):
    """The startup-pinned operator config changed and requires a restart."""


class SnapshotSourceUnsafeError(RuntimeError):
    """A snapshot-readable input uses an unsupported symlink boundary."""


def _discover_git_dirs(root: Path) -> tuple[Path | None, Path | None]:
    """Resolve per-worktree and common Git directories without invoking Git."""

    marker = root / ".git"
    if marker.is_dir():
        git_dir = marker
    else:
        try:
            value = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return None, None
        prefix = "gitdir:"
        if not value.lower().startswith(prefix):
            return None, None
        candidate = Path(value[len(prefix) :].strip())
        if not candidate.is_absolute():
            candidate = marker.parent / candidate
        try:
            git_dir = candidate.resolve(strict=True)
        except OSError:
            return None, None
        if not git_dir.is_dir():
            return None, None

    common_dir = git_dir
    commondir_file = git_dir / "commondir"
    try:
        value = commondir_file.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = git_dir / candidate
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return git_dir, None
        if not resolved.is_dir():
            return git_dir, None
        common_dir = resolved
    return git_dir, common_dir


def _validated_cors_origin(origin: str) -> str:
    """Return one exact, browser-serializable loopback origin or fail closed."""
    if "*" in origin:
        raise ValueError("wildcards are not allowed")
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("origin must use http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials are not allowed")
    if parsed.path or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("path, params, query and fragment are not allowed")
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("origin has an invalid host or port") from exc
    if not host:
        raise ValueError("origin must include a host")
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("host must be localhost or a loopback IP address") from exc
        if not address.is_loopback:
            raise ValueError("host must be loopback")

    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    serialized_host = f"[{host}]" if ":" in host else host
    canonical = f"{parsed.scheme}://{serialized_host}"
    if port is not None and not default_port:
        canonical += f":{port}"
    if origin != canonical:
        raise ValueError(f"origin must use its exact canonical form: {canonical}")
    return canonical


def _allowed_cors_origins() -> set[str]:
    configured = os.environ.get("WIKI_COCKPIT_CORS_ORIGINS", "")
    origins: set[str] = set()
    for raw_origin in configured.split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        try:
            origins.add(_validated_cors_origin(origin))
        except ValueError as exc:
            raise ValueError(
                f"invalid WIKI_COCKPIT_CORS_ORIGINS entry {origin!r}: {exc}"
            ) from exc
    return origins


class CockpitServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], root: Path, config: WikiConfig) -> None:
        # CORS is a startup trust decision. Invalid or remote origins must fail
        # before the operator opens a listening socket, and environment changes
        # only take effect after an intentional restart.
        self.cors_origins = _allowed_cors_origins()
        super().__init__(server_address, CockpitRequestHandler)
        self.root = root
        self.config = config
        self.snapshot_dir = WikiPaths(root, config).derived_root / "web-snapshot"
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache: _SnapshotCacheEntry | None = None
        self._git_dir, self._git_common_dir = _discover_git_dirs(root)
        self._snapshot_health_lock = threading.Lock()
        self._snapshot_last_result = "not_checked"
        self._snapshot_last_observation_finished_ns = 0
        self._mutation_lock = threading.Lock()
        self._active_mutations = 0
        self._mutation_local = threading.local()
        self.operator_nonce = secrets.token_urlsafe(32)
        self._attempt_lock = threading.Lock()
        self._attempt_receipts: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # One serialized Codex job stream per operator process.
        self.jobs = JobRunner(root, config, on_change=self.invalidate_snapshot_cache)

    def claim_attempt(self, key: str, path: str, payload_sha256: str) -> tuple[str, dict[str, Any] | None]:
        """Claim a mutating request or return its prior deterministic receipt.

        The key is scoped to the operator process. Reusing it with different
        input fails closed; retrying the same request replays the stored result
        instead of running the mutation twice.
        """
        now = time.monotonic()
        with self._attempt_lock:
            for old_key, receipt in list(self._attempt_receipts.items()):
                # An in-process mutation owns its key until it explicitly
                # finishes. Long gates, ingestion and Git operations must not
                # become claimable again just because wall time passed.
                if receipt["state"] != "complete":
                    continue
                completed_at = float(
                    receipt.get("completed_monotonic", receipt["created_monotonic"])
                )
                if now - completed_at > ATTEMPT_RECEIPT_TTL_S:
                    del self._attempt_receipts[old_key]
            prior = self._attempt_receipts.get(key)
            if prior is not None:
                self._attempt_receipts.move_to_end(key)
                if prior["path"] != path or prior["payload_sha256"] != payload_sha256:
                    return "conflict", None
                if prior["state"] == "in_flight":
                    return "in_flight", None
                return "replay", dict(prior)
            # Capacity pressure may discard replayable completed receipts, but
            # never a live owner. If every slot is active, fail closed and let
            # the caller retry after an operation completes.
            for old_key, receipt in list(self._attempt_receipts.items()):
                if len(self._attempt_receipts) < MAX_ATTEMPT_RECEIPTS:
                    break
                if receipt["state"] == "complete":
                    del self._attempt_receipts[old_key]
            if len(self._attempt_receipts) >= MAX_ATTEMPT_RECEIPTS:
                return "capacity", None

            self._attempt_receipts[key] = {
                "state": "in_flight",
                "path": path,
                "payload_sha256": payload_sha256,
                "created_monotonic": now,
            }
            return "claimed", None

    def finish_attempt(self, key: str, status: int, payload: Any) -> None:
        with self._attempt_lock:
            receipt = self._attempt_receipts.get(key)
            if receipt is None or receipt.get("state") != "in_flight":
                return
            receipt.update(
                {
                    "state": "complete",
                    "status": status,
                    "payload": payload,
                    "completed_monotonic": time.monotonic(),
                }
            )
            self._attempt_receipts.move_to_end(key)

    def fail_attempt_if_in_flight(self, key: str, status: int, payload: Any) -> bool:
        """Close an unexpectedly failed claim without rewriting a sent receipt."""

        with self._attempt_lock:
            receipt = self._attempt_receipts.get(key)
            if receipt is None or receipt.get("state") != "in_flight":
                return False
            receipt.update(
                {
                    "state": "complete",
                    "status": status,
                    "payload": payload,
                    "completed_monotonic": time.monotonic(),
                }
            )
            self._attempt_receipts.move_to_end(key)
            return True

    def begin_mutation(self) -> None:
        with self._mutation_lock:
            self._active_mutations += 1
        self._mutation_local.active = True

    def end_mutation(self) -> None:
        if not bool(getattr(self._mutation_local, "active", False)):
            return
        self._mutation_local.active = False
        with self._mutation_lock:
            self._active_mutations = max(self._active_mutations - 1, 0)

    def mutation_in_progress_elsewhere(self) -> bool:
        owns_mutation = bool(getattr(self._mutation_local, "active", False))
        with self._mutation_lock:
            own_count = 1 if owns_mutation else 0
            return self._active_mutations > own_count

    # Snapshot cache TTL: a live rebuild walks the whole wiki (minutes on a
    # multi-hundred-page repo), so the cache must outlive a browsing session.
    # Correctness does not depend on the TTL. Every read first compares an
    # opaque source revision, and every in-process mutation invalidates after
    # its commit boundary. The TTL is only an upper bound on reuse when a
    # source revision remains unchanged.
    SNAPSHOT_CACHE_TTL_S = 600
    SNAPSHOT_STABLE_BUILD_ATTEMPTS = 5

    @staticmethod
    def _hash_identity(
        digest: Any,
        label: bytes,
        path: Path,
    ) -> tuple[bool, bool, bool]:
        """Hash one lstat identity; return (observed, complete, symlink).

        Device/inode plus ctime make same-size atomic editor replacements and
        mtime restoration visible. We intentionally exclude atime because the
        snapshot builder itself reads these files.
        """

        digest.update(label)
        digest.update(b"\0")
        try:
            info = path.lstat()
        except FileNotFoundError:
            digest.update(b"missing\0")
            return False, True, False
        except OSError:
            digest.update(b"unreadable\0")
            return False, False, False
        identity = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        digest.update(repr(identity).encode("ascii"))
        digest.update(b"\0")
        if stat.S_ISLNK(info.st_mode):
            try:
                digest.update(os.fsencode(os.readlink(path)))
            except OSError:
                return True, False, True
            digest.update(b"\0")
            return True, True, True
        return True, True, False

    def _hash_tree(
        self,
        digest: Any,
        path: Path,
        label: bytes,
        *,
        detect_git_locks: bool = False,
    ) -> tuple[bool, bool, bool]:
        """Hash a non-following metadata inventory.

        Returns (complete, write_in_progress, unsafe_input). Missing optional
        roots are valid; unreadable directories or symlinks make the revision
        ineligible to bless a newly built cache.
        """

        observed, complete, unsafe_input = self._hash_identity(
            digest, label, path
        )
        if not observed:
            return complete, False, unsafe_input
        if unsafe_input:
            # Snapshot builders follow Markdown/config symlinks in several
            # places. Hashing only link text would miss changes to an external
            # target, so the live operator rejects this boundary entirely.
            return False, False, True
        try:
            info = path.lstat()
        except OSError:
            return False, False, False
        if not stat.S_ISDIR(info.st_mode):
            return complete, False, False
        try:
            with os.scandir(path) as iterator:
                entries = sorted(
                    iterator,
                    key=lambda entry: os.fsencode(entry.name),
                )
        except OSError:
            digest.update(b"scan-error\0")
            return False, False, False

        write_in_progress = False
        for entry in entries:
            entry_name = os.fsencode(entry.name)
            child_complete, child_lock, child_unsafe = self._hash_tree(
                digest,
                Path(entry.path),
                label + b"/" + entry_name,
                detect_git_locks=detect_git_locks,
            )
            complete = complete and child_complete
            write_in_progress = write_in_progress or child_lock
            unsafe_input = unsafe_input or child_unsafe
            if detect_git_locks and entry.name.endswith(".lock"):
                write_in_progress = True
        return complete, write_in_progress, unsafe_input

    @staticmethod
    def _porcelain_paths(output: bytes) -> list[bytes]:
        """Extract both sides of NUL-delimited porcelain v1 rename records."""

        records = output.split(b"\0")
        paths: list[bytes] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 3 or record[2:3] != b" ":
                # This can only be the second pathname of a malformed/partial
                # rename record. Hashing raw output still detects it, but it is
                # not safe to resolve as a repository path.
                continue
            status = record[:2]
            paths.append(record[3:])
            if b"R" in status or b"C" in status:
                if index < len(records) and records[index]:
                    paths.append(records[index])
                    index += 1
        return paths

    def _hash_git_state(self, digest: Any) -> tuple[bool, bool, bool]:
        git_dir = self._git_dir
        common_dir = self._git_common_dir
        if git_dir is None:
            digest.update(b"git:none\0")
            return True, False, False
        if common_dir is None:
            digest.update(b"git-common:unavailable\0")
            return False, False, False

        complete = True
        write_in_progress = False
        unsafe_input = False
        # Branch/HEAD, refs and the index are enough to observe commits,
        # checkouts, staging and branch switches without the heavyweight Git
        # subject collector used by release proofs.
        for name in (
            "HEAD",
            "ORIG_HEAD",
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "index.lock",
            "HEAD.lock",
            "commondir",
            "config.worktree",
        ):
            observed, item_complete, item_unsafe = self._hash_identity(
                digest,
                b"git/" + name.encode("ascii"),
                git_dir / name,
            )
            complete = complete and item_complete
            unsafe_input = unsafe_input or item_unsafe
            if observed and name.endswith(".lock"):
                write_in_progress = True
        for name in (
            "packed-refs",
            "FETCH_HEAD",
            "config",
            "shallow",
            "packed-refs.lock",
            "config.lock",
            "shallow.lock",
        ):
            observed, item_complete, item_unsafe = self._hash_identity(
                digest,
                b"git-common/" + name.encode("ascii"),
                common_dir / name,
            )
            complete = complete and item_complete
            unsafe_input = unsafe_input or item_unsafe
            if observed and name.endswith(".lock"):
                write_in_progress = True
        for name in ("heads", "remotes"):
            tree_complete, tree_lock, tree_unsafe = self._hash_tree(
                digest,
                common_dir / "refs" / name,
                b"git-common/refs/" + name.encode("ascii"),
                detect_git_locks=True,
            )
            complete = complete and tree_complete
            write_in_progress = write_in_progress or tree_lock
            unsafe_input = unsafe_input or tree_unsafe

        try:
            process = subprocess.run(
                [
                    "git",
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                ],
                cwd=self.root,
                capture_output=True,
                check=False,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            digest.update(b"git-status:unavailable\0")
            return False, write_in_progress, unsafe_input
        digest.update(b"git-status\0")
        digest.update(process.stdout)
        digest.update(b"\0")
        if process.returncode != 0:
            return False, write_in_progress, unsafe_input

        # `git status` may refresh index stat data on older Git versions. Hash
        # the index after that observation so one fingerprint never describes
        # the pre-refresh index alongside the post-refresh porcelain result.
        _observed, index_complete, index_unsafe = self._hash_identity(
            digest,
            b"git/index",
            git_dir / "index",
        )
        complete = complete and index_complete
        unsafe_input = unsafe_input or index_unsafe

        seen: set[bytes] = set()
        for raw_path in self._porcelain_paths(process.stdout):
            if not raw_path or raw_path in seen:
                continue
            seen.add(raw_path)
            decoded = os.fsdecode(raw_path)
            relative = Path(decoded)
            if relative.is_absolute() or ".." in relative.parts:
                digest.update(b"dirty-path:invalid\0")
                complete = False
                continue
            _observed, item_complete, _item_unsafe = self._hash_identity(
                digest,
                b"dirty/" + raw_path,
                self.root / relative,
            )
            complete = complete and item_complete
        return complete, write_in_progress, unsafe_input

    def _snapshot_input_roots(self) -> list[tuple[Path, bytes]]:
        paths = WikiPaths(self.root, self.config)
        inputs: list[tuple[Path, bytes]] = [
            (paths.memory_root, b"wiki/memory"),
            (self.root / ".wiki-viva" / "packs", b"wiki/installed-packs"),
            (paths.chunks, b"wiki/derived/chunks"),
            (paths.llm_cache, b"wiki/derived/llm-cache"),
            (paths.source_state, b"wiki/derived/source-state"),
            (paths.derived_root / "gate-receipts", b"wiki/derived/gate-receipts"),
            (paths.derived_root / "score-events.jsonl", b"wiki/derived/score-events"),
            (
                paths.derived_root / "score-events-mirror.jsonl",
                b"wiki/derived/score-events-mirror",
            ),
        ]
        overlays = str((self.config.templates or {}).get("overlays_root") or "").strip()
        if overlays:
            inputs.append((self.root / overlays, b"wiki/template-overlays"))
        try:
            with os.scandir(self.root) as iterator:
                root_entries = sorted(
                    iterator,
                    key=lambda entry: os.fsencode(entry.name),
                )
        except OSError:
            # A missing root will make every mandatory inventory incomplete;
            # this marker also prevents accidental equality with a valid read.
            return [*inputs, (self.root / "wiki.config.yaml", b"wiki/root-scan-error")]
        for entry in root_entries:
            lower = entry.name.lower()
            if lower.startswith("wiki") and lower.endswith((".yaml", ".yml")):
                inputs.append(
                    (
                        Path(entry.path),
                        b"wiki/config/" + os.fsencode(entry.name),
                    )
                )
        return inputs

    def _snapshot_source_revision(self) -> _SnapshotSourceRevision:
        digest = hashlib.sha256()
        complete, write_in_progress, unsafe_input = self._hash_git_state(digest)
        for path, label in self._snapshot_input_roots():
            item_complete, _item_lock, item_unsafe = self._hash_tree(
                digest, path, label
            )
            complete = complete and item_complete
            unsafe_input = unsafe_input or item_unsafe
        return _SnapshotSourceRevision(
            digest=digest.hexdigest(),
            complete=complete,
            write_in_progress=write_in_progress,
            unsafe_input=unsafe_input,
        )

    def _set_snapshot_last_result(self, value: str) -> None:
        with self._snapshot_health_lock:
            self._snapshot_last_result = value

    def snapshot_cache_health(self) -> dict[str, Any]:
        with self._snapshot_health_lock:
            last_result = self._snapshot_last_result
        return {
            "version": SNAPSHOT_EXTERNAL_FRESHNESS_VERSION,
            "checked_on_every_snapshot_read": True,
            "validation": "optimistic_source_revision_before_and_after_build",
            "revision_inputs": [
                "git_head_branch_and_refs",
                "git_index_identity",
                "git_dirty_set_and_path_identity",
                "wiki_memory_config_pack_and_derived_inputs",
            ],
            "file_identity": [
                "device",
                "inode",
                "mode",
                "size",
                "mtime_ns",
                "ctime_ns",
            ],
            "stable_build_attempts": self.SNAPSHOT_STABLE_BUILD_ATTEMPTS,
            "concurrent_read_coalescing": (
                "one_linearizable_revision_observation_per_overlapping_burst"
            ),
            "operator_boot_transport": "single_aggregate_without_temporal_graph",
            "configuration_policy": (
                "startup_pinned_change_requires_operator_restart"
            ),
            "symlink_policy": "snapshot_readable_inputs_fail_closed",
            "local_mutation_behavior": (
                "serve_prior_stable_or_503_until_commit_invalidation"
            ),
            "unstable_source_behavior": "serve_prior_stable_or_503",
            "fingerprint_or_paths_exposed": False,
            "last_result": last_result,
        }

    def snapshot_payloads(self) -> dict[str, dict[str, Any]]:
        request_started_ns = time.monotonic_ns()
        with self._snapshot_lock:
            now = time.monotonic()
            prior = self._snapshot_cache
            if self.mutation_in_progress_elsewhere():
                if prior is not None:
                    self._set_snapshot_last_result(
                        "served_prior_stable_during_local_mutation"
                    )
                    return prior.payloads
                self._set_snapshot_last_result(
                    "local_mutation_in_progress_no_prior_snapshot"
                )
                raise SnapshotSourceUnstableError
            # A parallel request that started before the previous observation
            # completed can linearize at that same observation. This keeps a
            # 25-file cockpit boot to one inventory instead of 25 serialized
            # Git/tree walks, while a later request always performs a new
            # comparison. Local invalidation clears `prior`, so it can never be
            # hidden by burst coalescing.
            if (
                prior is not None
                and self._snapshot_last_observation_finished_ns
                >= request_started_ns
            ):
                self._set_snapshot_last_result(
                    "cache_hit_coalesced_overlapping_revision"
                )
                return prior.payloads
            observed = self._snapshot_source_revision()
            if observed.unsafe_input:
                self._set_snapshot_last_result("unsafe_symlink_input_blocked")
                raise SnapshotSourceUnsafeError
            if (
                prior is not None
                and observed.complete
                and not observed.write_in_progress
                and observed.digest == prior.revision
                and now - prior.built_monotonic < self.SNAPSHOT_CACHE_TTL_S
            ):
                self._snapshot_last_observation_finished_ns = time.monotonic_ns()
                self._set_snapshot_last_result("cache_hit_stable_revision")
                return prior.payloads

            # CORS, paths, job storage and mutation policy are initialized from
            # one startup config. Reloading only the snapshot builder would
            # create a split-brain operator, while continuing with `self.config`
            # would bless stale semantics. Fail closed until a restart loads
            # the new configuration coherently across every subsystem.
            try:
                current_config = load_config(self.root)
            except Exception:  # noqa: BLE001 - malformed config fails closed
                self._set_snapshot_last_result(
                    "configuration_unreadable_restart_required"
                )
                raise SnapshotConfigurationChangedError from None
            if current_config != self.config:
                self._set_snapshot_last_result(
                    "configuration_changed_restart_required"
                )
                raise SnapshotConfigurationChangedError

            for attempt in range(self.SNAPSHOT_STABLE_BUILD_ATTEMPTS):
                before = observed if attempt == 0 else self._snapshot_source_revision()
                if before.unsafe_input:
                    self._set_snapshot_last_result(
                        "unsafe_symlink_input_blocked"
                    )
                    raise SnapshotSourceUnsafeError
                if not before.complete or before.write_in_progress:
                    continue
                try:
                    payloads = build_snapshot(
                        self.root,
                        self.config,
                        mode="local_operator",
                    )
                except Exception:
                    after_failure = self._snapshot_source_revision()
                    if after_failure.unsafe_input:
                        self._set_snapshot_last_result(
                            "unsafe_symlink_input_blocked"
                        )
                        raise SnapshotSourceUnsafeError from None
                    if (
                        not after_failure.complete
                        or after_failure.write_in_progress
                        or after_failure.digest != before.digest
                    ):
                        observed = after_failure
                        continue
                    raise
                after = self._snapshot_source_revision()
                if after.unsafe_input:
                    self._set_snapshot_last_result(
                        "unsafe_symlink_input_blocked"
                    )
                    raise SnapshotSourceUnsafeError
                if (
                    after.complete
                    and not after.write_in_progress
                    and after.digest == before.digest
                ):
                    self._snapshot_cache = _SnapshotCacheEntry(
                        built_monotonic=now,
                        revision=after.digest,
                        payloads=payloads,
                    )
                    self._snapshot_last_observation_finished_ns = (
                        time.monotonic_ns()
                    )
                    self._set_snapshot_last_result("rebuilt_stable_revision")
                    return payloads
                observed = after

            if prior is not None:
                self._snapshot_last_observation_finished_ns = time.monotonic_ns()
                self._set_snapshot_last_result(
                    "served_prior_stable_during_source_change"
                )
                return prior.payloads
            self._snapshot_last_observation_finished_ns = time.monotonic_ns()
            self._set_snapshot_last_result("source_unstable_no_prior_snapshot")
            raise SnapshotSourceUnstableError

    def cached_snapshot_id(self) -> str | None:
        """Return only the cached envelope id, never its source fingerprint."""

        with self._snapshot_lock:
            if self._snapshot_cache is None:
                return None
            value = self._snapshot_cache.payloads.get("manifest.json", {}).get(
                "snapshot_id"
            )
            return str(value) if value else None

    def invalidate_snapshot_cache(self) -> None:
        """Drop the cached snapshot after a mutating action (e.g. a gate run
        writes a receipt), so the very next refetch reflects reality instead of
        the prior stable revision — the UI must never show green rows under a
        red header."""
        with self._snapshot_lock:
            self._snapshot_cache = None
        self._set_snapshot_last_result("invalidated_after_local_mutation")


class CockpitRequestHandler(BaseHTTPRequestHandler):
    server: CockpitServer

    _attempt_key: str | None = None
    _replaying_attempt = False
    _mutation_owned = False

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _cors_origin(self) -> str | None:
        origin = (self.headers.get("Origin") or "").strip()
        if origin in self.server.cors_origins:
            return origin
        return None

    def _send_cors_headers(self) -> None:
        origin = self._cors_origin()
        if not origin:
            return
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Allow-Headers",
            f"content-type, {OPERATOR_NONCE_HEADER.lower()}, {ATTEMPT_KEY_HEADER.lower()}",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        status_code = int(status)
        if self._attempt_key and not self._replaying_attempt and isinstance(payload, dict):
            payload = {**payload, "attempt_key": self._attempt_key, "replayed": False}
        # Prove the exact response is standards-compliant and replayable before
        # publishing either the mutation commit boundary or attempt receipt.
        # A future endpoint returning a set/Path/NaN must become one safe 500,
        # never a poisoned complete receipt followed by a dropped socket.
        body = json.dumps(
            payload,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        if self._mutation_owned:
            # The operation and its replay receipt are complete. Publish the
            # cache commit boundary before any success/error bytes become
            # observable to the client; otherwise an immediate refetch can
            # race between wfile.write() and do_POST.finally and receive the
            # prior world after the mutation already reported success.
            self.server.invalidate_snapshot_cache()
            self.server.end_mutation()
            self._mutation_owned = False
        if self._attempt_key and not self._replaying_attempt and isinstance(payload, dict):
            # A replayable success is externally observable too. Publish it
            # only after the cache/mutation commit boundary above, otherwise a
            # concurrent retry can receive success while an immediate GET is
            # still forced onto the prior world.
            self.server.finish_attempt(self._attempt_key, status_code, payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors_headers()
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, *, status: HTTPStatus) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _host_is_loopback(self) -> bool:
        raw = (self.headers.get("Host") or "").strip().lower()
        if raw.startswith("["):
            end = raw.find("]")
            host = raw[1:end] if end > 0 else raw
        else:
            host = raw.split(":", 1)[0]
        return host in LOOPBACK_HOSTS

    def _guard_host(self) -> bool:
        if self._host_is_loopback():
            return True
        self._send_error("operator host must be loopback", status=HTTPStatus.FORBIDDEN)
        return False

    def _guard_mutation_origin(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin or origin in self.server.cors_origins:
            return True
        self._send_error("operator origin is not allowlisted", status=HTTPStatus.FORBIDDEN)
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._guard_host():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._do_GET()
        except SnapshotSourceUnsafeError:
            self._send_json(
                {
                    "ok": False,
                    "error": "live snapshot input boundary is unsupported",
                    "error_code": "snapshot_source_symlink_blocked",
                    "retryable": False,
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except SnapshotConfigurationChangedError:
            self._send_json(
                {
                    "ok": False,
                    "error": "wiki configuration changed; restart the local operator",
                    "error_code": "snapshot_configuration_restart_required",
                    "retryable": False,
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except SnapshotSourceUnstableError:
            self._send_json(
                {
                    "ok": False,
                    "error": "live snapshot source is changing; retry",
                    "error_code": "snapshot_source_unstable",
                    "retryable": True,
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _do_GET(self) -> None:
        if not self._guard_host():
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "repo": self.server.config.repo_id,
                    "snapshot_dir": self.server.snapshot_dir.relative_to(self.server.root).as_posix(),
                    "snapshot_publication": snapshot_publication_status(
                        self.server.root,
                        self.server.snapshot_dir,
                        repo_id=self.server.config.repo_id,
                    ),
                    "api_snapshot_serving": {
                        "source": "live_repository_build_cache",
                        "uses_published_snapshot_pointer": False,
                        "cache_ttl_seconds": self.server.SNAPSHOT_CACHE_TTL_S,
                        "external_freshness": self.server.snapshot_cache_health(),
                    },
                    "server_version": WEB_SERVER_VERSION,
                    "schema_capabilities": list(SCHEMA_CAPABILITIES),
                    "operator_security": {
                        "version": WEB_OPERATOR_SECURITY_VERSION,
                        "nonce_header": OPERATOR_NONCE_HEADER,
                        "nonce": self.server.operator_nonce,
                        "attempt_header": ATTEMPT_KEY_HEADER,
                        "max_body_bytes": MAX_REQUEST_BODY_BYTES,
                        "mutations": "post_only",
                        "browser_origin_default": "deny",
                        "cors_opt_in": "exact_loopback_allowlist",
                    },
                    "codex": probe_codex_for(self.server.config),
                }
            )
            return
        if path == "/api/codex/capability":
            self._send_json(probe_codex_for(self.server.config))
            return
        if path == "/api/diff/file":
            file_path = (parse_qs(parsed.query).get("path") or [""])[0]
            result = file_diff(self.server.root, self.server.config, file_path)
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/briefs":
            store = BriefStore(self.server.root, self.server.config)
            self._send_json({"ok": True, "briefs": store.list()})
            return
        if path.startswith("/api/briefs/"):
            brief_id = path[len("/api/briefs/") :].strip("/")
            record = BriefStore(self.server.root, self.server.config).get(brief_id)
            if record is None:
                self._send_error("unknown brief", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, **record})
            return
        if path == "/api/codex/jobs":
            self._send_json({"ok": True, "jobs": self.server.jobs.list()})
            return
        if path.startswith("/api/codex/jobs/"):
            rest = path[len("/api/codex/jobs/") :].strip("/")
            if rest.endswith("/log"):
                job_id = rest[: -len("/log")].strip("/")
                if self.server.jobs.get(job_id) is None:
                    self._send_error("unknown job", status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "job_id": job_id, "log": self.server.jobs.read_log(job_id)})
                return
            record = self.server.jobs.get(rest)
            if record is None:
                self._send_error("unknown job", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, **record})
            return
        if path == "/api/sources":
            # Friendlier alias for the rich source read model (also served raw
            # at /api/snapshot/source_entities.json).
            self._send_json(self.server.snapshot_payloads().get("source_entities.json") or {"sources": []})
            return
        if path == "/api/snapshot":
            self._send_json(self.server.snapshot_payloads())
            return
        if path == "/api/snapshot/boot":
            # One coherent transport for the cockpit's initial world. Temporal
            # history remains lazy because it can be hundreds of kilobytes and
            # has its own revision-bound endpoint/read contract.
            payloads = dict(self.server.snapshot_payloads())
            payloads.pop("temporal_graph.json", None)
            self._send_json(payloads)
            return
        if path == "/api/snapshot/write":
            self._send_error("snapshot writes are POST-only", status=HTTPStatus.METHOD_NOT_ALLOWED)
            return
        if path.startswith("/api/snapshot/"):
            name = path.rsplit("/", 1)[-1]
            payload = self.server.snapshot_payloads().get(name)
            if payload is None:
                self._send_error("unknown snapshot file", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(payload)
            return
        if path.startswith("/api/pages/") and path.endswith("/content"):
            page_id = path[len("/api/pages/") : -len("/content")].strip("/")
            if not page_id:
                self._send_error("missing page id", status=HTTPStatus.BAD_REQUEST)
                return
            expected_snapshot_id = str(
                (parse_qs(parsed.query).get("snapshot_id") or [""])[0]
            ).strip()
            if len(expected_snapshot_id) > 512:
                self._send_error(
                    "snapshot_id query exceeds operator limit",
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            prior_snapshot_id = self.server.cached_snapshot_id()
            snapshot = self.server.snapshot_payloads()
            current_snapshot_id = str(
                snapshot.get("manifest.json", {}).get("snapshot_id") or ""
            )
            if (
                expected_snapshot_id
                and current_snapshot_id != expected_snapshot_id
            ):
                self._send_json(
                    {
                        "ok": False,
                        "error": "page changed since snapshot; refresh required",
                        "error_code": "snapshot_revision_mismatch",
                        "page_id": page_id,
                        "snapshot_id": current_snapshot_id,
                        "expected_snapshot_id": expected_snapshot_id,
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            if (
                prior_snapshot_id
                and current_snapshot_id
                and current_snapshot_id != prior_snapshot_id
            ):
                # The caller may still render revision A. Tell it to refetch
                # the world before content from freshly observed revision B can
                # enter the reader; the stable B cache stays ready for that
                # refetch.
                self._send_json(
                    {
                        "ok": False,
                        "error": "page changed since snapshot; refresh required",
                        "error_code": "snapshot_revision_mismatch",
                        "page_id": page_id,
                        "snapshot_id": prior_snapshot_id,
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            result = build_page_content(
                self.server.root,
                self.server.config,
                page_id,
                snapshot,
            )
            if result.get("error_code") in {
                "snapshot_content_hash_missing",
                "snapshot_revision_mismatch",
            }:
                # The next world fetch must obtain the same revision that the
                # reader will use.  This response remains a conflict so the
                # currently rendered old world can never accept newer content.
                self.server.invalidate_snapshot_cache()
                status = HTTPStatus.CONFLICT
            else:
                status = HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND
            self._send_json(
                result,
                status=status,
            )
            return
        self._send_error("not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """Close every claimed attempt and invalidate only after dispatch.

        Invalidating before the mutation let a concurrent GET rebuild and
        cache the old world while the write was still running. The post-action
        ``finally`` is the commit boundary for every synchronous endpoint. An
        unexpected exception is converted to one sanitized, replayable receipt
        instead of dropping the socket with the attempt stuck ``in_flight``.
        """

        self._attempt_key = None
        self._replaying_attempt = False
        self._mutation_owned = False
        try:
            self._do_POST()
        except Exception:  # noqa: BLE001 - operator boundary must fail closed
            key = self._attempt_key
            safe_payload: dict[str, Any] = {
                "ok": False,
                "error": "operator request failed",
                "error_code": "internal_operator_error",
            }
            if key and self._replaying_attempt:
                # A replay receipt was already complete; never rewrite it.
                self._attempt_key = None
            try:
                self._send_json(
                    safe_payload, status=HTTPStatus.INTERNAL_SERVER_ERROR
                )
            except (BrokenPipeError, ConnectionError, OSError):
                pass
        finally:
            if self._mutation_owned:
                self.server.invalidate_snapshot_cache()
                self.server.end_mutation()
                self._mutation_owned = False

    def _do_POST(self) -> None:
        if not self._guard_host() or not self._guard_mutation_origin():
            return
        parsed = urlparse(self.path)
        supplied_nonce = self.headers.get(OPERATOR_NONCE_HEADER) or ""
        if not supplied_nonce or not secrets.compare_digest(supplied_nonce, self.server.operator_nonce):
            self._send_error("missing or invalid operator nonce", status=HTTPStatus.FORBIDDEN)
            return
        attempt_key = (self.headers.get(ATTEMPT_KEY_HEADER) or "").strip()
        if not ATTEMPT_KEY_RE.fullmatch(attempt_key):
            self._send_error("missing or invalid attempt key", status=HTTPStatus.BAD_REQUEST)
            return
        content_type = (self.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_error("content-type must be application/json", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        try:
            length = int(self.headers.get("content-length") or "0")
        except ValueError:
            self._send_error("invalid content-length", status=HTTPStatus.BAD_REQUEST)
            return
        if length < 0 or length > MAX_REQUEST_BODY_BYTES:
            self._send_error("request body exceeds operator limit", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_error("invalid JSON", status=HTTPStatus.BAD_REQUEST)
            return
        payload_sha256 = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        claim, receipt = self.server.claim_attempt(attempt_key, parsed.path, payload_sha256)
        if claim == "conflict":
            self._send_error("attempt key was already used for different input", status=HTTPStatus.CONFLICT)
            return
        if claim == "in_flight":
            self._send_error("attempt is already in progress", status=HTTPStatus.CONFLICT)
            return
        if claim == "capacity":
            self._send_json(
                {
                    "ok": False,
                    "error": "operator attempt capacity is fully in use",
                    "error_code": "attempt_capacity_exhausted",
                    "retryable": True,
                },
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if claim == "replay" and receipt is not None:
            replay_payload = receipt.get("payload")
            if isinstance(replay_payload, dict):
                replay_payload = {**replay_payload, "attempt_key": attempt_key, "replayed": True}
            self._replaying_attempt = True
            self._send_json(replay_payload, status=HTTPStatus(int(receipt["status"])))
            return
        self._attempt_key = attempt_key
        self.server.begin_mutation()
        self._mutation_owned = True
        if parsed.path == "/api/snapshot/write":
            written = write_snapshot(
                self.server.root,
                self.server.snapshot_dir,
                self.server.config,
                clean=True,
                mode="local_operator",
            )
            recovery_paths = []
            for recovery in getattr(written, "recovery_paths", ()):
                try:
                    recovery_paths.append(
                        Path(recovery).relative_to(self.server.root).as_posix()
                    )
                except ValueError:
                    recovery_paths.append("contained-recovery-path-unavailable")
            self._send_json(
                {
                    "ok": True,
                    "committed": bool(getattr(written, "committed", True)),
                    "publication": (
                        "immutable_revision_pointer"
                        if hasattr(written, "active_revision")
                        else "flat_build"
                    ),
                    "snapshot_id": getattr(written, "snapshot_id", None),
                    "active_revision": getattr(written, "active_revision", None),
                    "cleanup_warnings": list(
                        getattr(written, "cleanup_warnings", ())
                    ),
                    "recovery_paths": recovery_paths,
                    "files": sorted(written),
                }
            )
            return
        if parsed.path == "/api/briefs" or parsed.path.startswith("/api/briefs/"):
            self._handle_briefs_post(parsed.path, payload)
            return
        if parsed.path == "/api/codex/jobs" or parsed.path.startswith("/api/codex/jobs/"):
            self._handle_codex_post(parsed.path, payload)
            return
        if parsed.path == "/api/gates/run":
            gate_id = str(payload.get("gate_id") or "")
            result = run_gate(self.server.root, self.server.config, gate_id)
            # A failing gate still RAN (200); only an unknown gate id is a 400.
            self._send_json(result, status=HTTPStatus.BAD_REQUEST if result.get("error") else HTTPStatus.OK)
            return
        if parsed.path == "/api/actions/transition":
            page_ref = str(payload.get("page_ref") or "").strip()
            next_state = str(payload.get("next_state") or "").strip()
            expected_sha256 = str(payload.get("expected_sha256") or "").strip()
            if not page_ref or not next_state or not expected_sha256:
                self._send_error(
                    "page_ref, next_state and expected_sha256 are required",
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            if Path(page_ref).is_absolute():
                self._send_error(
                    "page_ref must be repository-relative",
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            try:
                receipt = transition_action_page(
                    self.server.root,
                    page_ref,
                    next_state,
                    reason=(
                        str(payload["reason"])
                        if payload.get("reason") is not None
                        else None
                    ),
                    next_action=(
                        str(payload["next_action"])
                        if payload.get("next_action") is not None
                        else None
                    ),
                    blocked_by=(
                        payload["blocked_by"]
                        if payload.get("blocked_by") is not None
                        else None
                    ),
                    blocker_reason=(
                        str(payload["blocker_reason"])
                        if payload.get("blocker_reason") is not None
                        else None
                    ),
                    completion_receipt=(
                        str(payload["completion_receipt"])
                        if payload.get("completion_receipt") is not None
                        else None
                    ),
                    cancellation_receipt=(
                        str(payload["cancellation_receipt"])
                        if payload.get("cancellation_receipt") is not None
                        else None
                    ),
                    expected_sha256=expected_sha256,
                )
            except ActionTransitionError as exc:
                if exc.code in {
                    "invalid_transition",
                    "stale_action_revision",
                    "immutable_receipt_conflict",
                }:
                    status = HTTPStatus.CONFLICT
                elif exc.code == "action_not_found":
                    status = HTTPStatus.NOT_FOUND
                elif exc.code in {
                    "action_lock_backend_unavailable",
                    "action_lock_failed",
                    "action_read_failed",
                    "action_write_failed",
                }:
                    status = HTTPStatus.SERVICE_UNAVAILABLE
                else:
                    status = HTTPStatus.BAD_REQUEST
                self._send_json(exc.to_dict(), status=status)
                return
            self._send_json(receipt.to_dict())
            return
        if parsed.path == "/api/intake/copy":
            result = intake_copy(
                self.server.root,
                self.server.config,
                str(payload.get("source_path") or ""),
                str(payload.get("context") or ""),
            )
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/sources/") and parsed.path.endswith("/brief"):
            # Anchored BEFORE the allowlist so it does not fall through to the
            # /api/sources/triage handler. Composes an ingestion brief spec from
            # the source's recipe + stale streams (no side effects).
            from wiki_core.web.sources import compose_source_brief_spec

            source_id = parsed.path[len("/api/sources/") : -len("/brief")].strip("/")
            try:
                result = compose_source_brief_spec(self.server.root, self.server.config, source_id)
            except Exception:  # a malformed hand-authored recipe must not leak into a response
                self._send_json(
                    {
                        "ok": False,
                        "error": "source_brief_compose_failed",
                        "error_code": "source_brief_compose_failed",
                    },
                    status=HTTPStatus.OK,
                )
                return
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND)
            return
        if parsed.path not in {
            "/api/actions/run",
            "/api/git/workflow",
            "/api/sources/triage",
            "/api/ingestion/plan",
            "/api/ingestion/run",
        }:
            self._send_error("not found", status=HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/actions/run":
            action_id = str(payload.get("action_id") or "")
            if not action_id:
                self._send_error("missing action_id", status=HTTPStatus.BAD_REQUEST)
                return
            dry_run_raw = payload.get("dry_run")
            dry_run = None if dry_run_raw is None else bool(dry_run_raw)
            result = run_action(self.server.root, self.server.config, action_id, dry_run=dry_run)
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/git/workflow":
            operation = str(payload.get("operation") or "")
            if not operation:
                self._send_error("missing operation", status=HTTPStatus.BAD_REQUEST)
                return
            dry_run = bool(payload.get("dry_run", True))
            result = run_git_workflow(self.server.root, self.server.config, operation, payload, dry_run=dry_run)
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path in {"/api/ingestion/plan", "/api/ingestion/run"}:
            source = str(payload.get("source") or "")
            context = None if payload.get("context") is None else str(payload.get("context"))
            if not source:
                self._send_error("missing source", status=HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/ingestion/plan":
                result = build_ingestion_plan(self.server.root, self.server.config, source, context=context)
                self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
                return
            step_id = str(payload.get("step_id") or "")
            if not step_id:
                self._send_error("missing step_id", status=HTTPStatus.BAD_REQUEST)
                return
            dry_run = bool(payload.get("dry_run", True))
            result = run_ingestion_step(
                self.server.root,
                self.server.config,
                source,
                context or self.server.config.default_context,
                step_id,
                dry_run=dry_run,
            )
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        source = str(payload.get("source") or "")
        context = None if payload.get("context") is None else str(payload.get("context"))
        result = triage_source(self.server.root, self.server.config, source, context=context)
        self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)

    def _handle_briefs_post(self, path: str, payload: dict[str, Any]) -> None:
        store = BriefStore(self.server.root, self.server.config)
        if path == "/api/briefs":
            spec = payload.get("spec", payload)
            record = compose_and_save(
                self.server.root, self.server.config, self.server.snapshot_payloads(), spec=spec
            )
            self._send_json({"ok": True, **record})
            return
        rest = path[len("/api/briefs/") :].strip("/")
        if rest.endswith("/discard"):
            brief_id = rest[: -len("/discard")].strip("/")
            record = store.set_status(brief_id, "discarded")
            if record is None:
                self._send_error("unknown brief", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, **record})
            return
        brief_id = rest
        result = store.update_text(brief_id, str(payload.get("text") or ""))
        if result is None:
            self._send_error("unknown brief", status=HTTPStatus.NOT_FOUND)
            return
        if result.get("ok") is False:
            self._send_json(result, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, **result})

    def _handle_codex_post(self, path: str, payload: dict[str, Any]) -> None:
        jobs = self.server.jobs
        if path == "/api/codex/jobs":
            capability = probe_codex_for(self.server.config)
            if not capability.get("usable"):
                self._send_json(
                    {"ok": False, "error": capability.get("reason") or "Codex is not available", "codex": capability},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
            brief_id = str(payload.get("brief_id") or "")
            brief_sha = str(payload.get("brief_sha") or "")
            if not brief_id or not brief_sha:
                self._send_error("missing brief_id or brief_sha", status=HTTPStatus.BAD_REQUEST)
                return
            result = jobs.submit(
                brief_id=brief_id,
                brief_sha=brief_sha,
                dry_run=bool(payload.get("dry_run", True)),
                force=bool(payload.get("force", False)),
                parent_job_id=(str(payload["parent_job_id"]) if payload.get("parent_job_id") else None),
            )
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        rest = path[len("/api/codex/jobs/") :].strip("/")
        if rest.endswith("/cancel"):
            job_id = rest[: -len("/cancel")].strip("/")
            result = jobs.cancel(job_id)
            if result is None:
                self._send_error("unknown job", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(result, status=HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST)
            return
        if rest.endswith("/return"):
            job_id = rest[: -len("/return")].strip("/")
            parent = jobs.get(job_id)
            if parent is None:
                self._send_error("unknown job", status=HTTPStatus.NOT_FOUND)
                return
            brief = compose_return_brief(
                self.server.root,
                self.server.config,
                self.server.snapshot_payloads(),
                parent_job=parent,
                feedback=str(payload.get("feedback") or "").strip(),
            )
            if brief is None:
                self._send_json({"ok": False, "error": "job has no branch to continue"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json({"ok": True, **brief})
            return
        self._send_error("not found", status=HTTPStatus.NOT_FOUND)


def serve(root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            "the local operator may bind only to 127.0.0.1, localhost or ::1"
        )
    config = load_config(root)
    server = CockpitServer((host, port), root, config)
    print(f"wiki web server listening on http://{host}:{port}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Wiki Viva web cockpit operator server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", default=str(Path.cwd()))
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK_HOSTS:
        parser.error(
            "--host must be 127.0.0.1, localhost or ::1; "
            "the operator has no remote-bind authentication"
        )
    serve(Path(args.root).resolve(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
