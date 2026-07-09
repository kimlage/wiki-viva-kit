from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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
from wiki_core.web.schemas import SCHEMA_CAPABILITIES, WEB_SERVER_VERSION
from wiki_core.web.snapshot import build_snapshot, write_snapshot
from wiki_core.web.source_triage import triage_source


DEFAULT_CORS_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
}

OPERATOR_NONCE_HEADER = "X-Wiki-Operator-Nonce"
ATTEMPT_KEY_HEADER = "X-Wiki-Attempt-Key"
MAX_REQUEST_BODY_BYTES = 1_048_576
MAX_ATTEMPT_RECEIPTS = 512
ATTEMPT_RECEIPT_TTL_S = 3_600
ATTEMPT_IN_FLIGHT_TTL_S = 120
ATTEMPT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _allowed_cors_origins() -> set[str]:
    configured = os.environ.get("WIKI_COCKPIT_CORS_ORIGINS", "")
    origins = {origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()}
    return origins or DEFAULT_CORS_ORIGINS


class CockpitServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], root: Path, config: WikiConfig) -> None:
        super().__init__(server_address, CockpitRequestHandler)
        self.root = root
        self.config = config
        self.snapshot_dir = WikiPaths(root, config).derived_root / "web-snapshot"
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        self.operator_nonce = secrets.token_urlsafe(32)
        self._attempt_lock = threading.Lock()
        self._attempt_receipts: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # One serialized Codex job stream per operator process.
        self.jobs = JobRunner(root, config)

    def claim_attempt(self, key: str, path: str, payload_sha256: str) -> tuple[str, dict[str, Any] | None]:
        """Claim a mutating request or return its prior deterministic receipt.

        The key is scoped to the operator process. Reusing it with different
        input fails closed; retrying the same request replays the stored result
        instead of running the mutation twice.
        """
        now = time.monotonic()
        with self._attempt_lock:
            for old_key, receipt in list(self._attempt_receipts.items()):
                age = now - float(receipt["created_monotonic"])
                ttl = ATTEMPT_IN_FLIGHT_TTL_S if receipt["state"] == "in_flight" else ATTEMPT_RECEIPT_TTL_S
                if age > ttl:
                    del self._attempt_receipts[old_key]
            prior = self._attempt_receipts.get(key)
            if prior is not None:
                self._attempt_receipts.move_to_end(key)
                if prior["path"] != path or prior["payload_sha256"] != payload_sha256:
                    return "conflict", None
                if prior["state"] == "in_flight":
                    return "in_flight", None
                return "replay", dict(prior)
            self._attempt_receipts[key] = {
                "state": "in_flight",
                "path": path,
                "payload_sha256": payload_sha256,
                "created_monotonic": now,
            }
            while len(self._attempt_receipts) > MAX_ATTEMPT_RECEIPTS:
                self._attempt_receipts.popitem(last=False)
            return "claimed", None

    def finish_attempt(self, key: str, status: int, payload: Any) -> None:
        with self._attempt_lock:
            receipt = self._attempt_receipts.get(key)
            if receipt is None:
                return
            receipt.update({"state": "complete", "status": status, "payload": payload})
            self._attempt_receipts.move_to_end(key)

    # Snapshot cache TTL: a live rebuild walks the whole wiki (minutes on a
    # multi-hundred-page repo), so the cache must outlive a browsing session.
    # Correctness does not depend on the TTL — every mutating action calls
    # invalidate_snapshot_cache(), so the UI never reads a stale world after
    # its own writes. The TTL only bounds staleness from EXTERNAL edits.
    SNAPSHOT_CACHE_TTL_S = 600

    def snapshot_payloads(self) -> dict[str, dict[str, Any]]:
        with self._snapshot_lock:
            now = time.monotonic()
            if self._snapshot_cache is not None and now - self._snapshot_cache[0] < self.SNAPSHOT_CACHE_TTL_S:
                return self._snapshot_cache[1]
            payloads = build_snapshot(self.root, self.config, mode="local_operator")
            self._snapshot_cache = (now, payloads)
            return payloads

    def invalidate_snapshot_cache(self) -> None:
        """Drop the cached snapshot after a mutating action (e.g. a gate run
        writes a receipt), so the very next refetch reflects reality instead of
        the 8s window — the UI must never show green rows under a red header."""
        with self._snapshot_lock:
            self._snapshot_cache = None


class CockpitRequestHandler(BaseHTTPRequestHandler):
    server: CockpitServer

    _attempt_key: str | None = None
    _replaying_attempt = False

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _cors_origin(self) -> str | None:
        origin = (self.headers.get("Origin") or "").rstrip("/")
        allowed = _allowed_cors_origins()
        if origin in allowed:
            return origin
        if not origin:
            return "http://127.0.0.1:5173"
        return None

    def _send_cors_headers(self) -> None:
        origin = self._cors_origin()
        if origin:
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
            self.server.finish_attempt(self._attempt_key, status_code, payload)
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
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
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin or origin in _allowed_cors_origins():
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
                    "server_version": WEB_SERVER_VERSION,
                    "schema_capabilities": list(SCHEMA_CAPABILITIES),
                    "operator_security": {
                        "version": "wiki_operator_security.v1",
                        "nonce_header": OPERATOR_NONCE_HEADER,
                        "nonce": self.server.operator_nonce,
                        "attempt_header": ATTEMPT_KEY_HEADER,
                        "max_body_bytes": MAX_REQUEST_BODY_BYTES,
                        "mutations": "post_only",
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
            result = build_page_content(
                self.server.root, self.server.config, page_id, self.server.snapshot_payloads()
            )
            self._send_json(
                result,
                status=HTTPStatus.OK if result.get("ok") else HTTPStatus.NOT_FOUND,
            )
            return
        self._send_error("not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
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
        if claim == "replay" and receipt is not None:
            replay_payload = receipt.get("payload")
            if isinstance(replay_payload, dict):
                replay_payload = {**replay_payload, "attempt_key": attempt_key, "replayed": True}
            self._replaying_attempt = True
            self._send_json(replay_payload, status=HTTPStatus(int(receipt["status"])))
            return
        self._attempt_key = attempt_key
        # Every POST below can mutate the world (gate receipts, git moves,
        # intake copies, brief/job state) — the next snapshot fetch must always
        # see reality, whichever endpoint wrote it. Invalidation is cheap; a
        # stale 10-minute cache after a mutation is not.
        self.server.invalidate_snapshot_cache()
        if parsed.path == "/api/snapshot/write":
            written = write_snapshot(
                self.server.root,
                self.server.snapshot_dir,
                self.server.config,
                clean=True,
                mode="local_operator",
            )
            self._send_json({"ok": True, "files": sorted(written)})
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
            # The run wrote a receipt — the next snapshot fetch must see it.
            self.server.invalidate_snapshot_cache()
            # A failing gate still RAN (200); only an unknown gate id is a 400.
            self._send_json(result, status=HTTPStatus.BAD_REQUEST if result.get("error") else HTTPStatus.OK)
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
            except Exception as exc:  # a malformed hand-authored recipe must not 500 with a trace
                self._send_json({"ok": False, "error": f"could not compose brief: {exc}"}, status=HTTPStatus.OK)
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
