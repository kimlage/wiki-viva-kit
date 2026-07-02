from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from wiki_core.config import WikiConfig, load_config
from wiki_core.paths import WikiPaths
from wiki_core.web.briefs import BriefStore, compose_and_save, compose_return_brief
from wiki_core.web.codex_jobs import JobRunner
from wiki_core.web.codex_probe import probe_codex_for
from wiki_core.web.commands import run_action
from wiki_core.web.content import build_page_content
from wiki_core.web.git_workflows import run_git_workflow
from wiki_core.web.ingestion_plan import build_ingestion_plan, run_ingestion_step
from wiki_core.web.schemas import SCHEMA_CAPABILITIES, WEB_SERVER_VERSION
from wiki_core.web.snapshot import build_snapshot, write_snapshot
from wiki_core.web.source_triage import triage_source


class CockpitServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], root: Path, config: WikiConfig) -> None:
        super().__init__(server_address, CockpitRequestHandler)
        self.root = root
        self.config = config
        self.snapshot_dir = WikiPaths(root, config).derived_root / "web-snapshot"
        self._snapshot_lock = threading.Lock()
        self._snapshot_cache: tuple[float, dict[str, dict[str, Any]]] | None = None
        # One serialized Codex job stream per operator process.
        self.jobs = JobRunner(root, config)

    def snapshot_payloads(self) -> dict[str, dict[str, Any]]:
        with self._snapshot_lock:
            now = time.monotonic()
            if self._snapshot_cache is not None and now - self._snapshot_cache[0] < 8:
                return self._snapshot_cache[1]
            payloads = build_snapshot(self.root, self.config, mode="local_operator")
            self._snapshot_cache = (now, payloads)
            return payloads


class CockpitRequestHandler(BaseHTTPRequestHandler):
    server: CockpitServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _send_json(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, message: str, *, status: HTTPStatus) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:5173")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
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
                    "codex": probe_codex_for(self.server.config),
                }
            )
            return
        if path == "/api/codex/capability":
            self._send_json(probe_codex_for(self.server.config))
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
                self._send_json({"ok": True, "job_id": job_id, "log": self.server.jobs.read_log(job_id)})
                return
            record = self.server.jobs.get(rest)
            if record is None:
                self._send_error("unknown job", status=HTTPStatus.NOT_FOUND)
                return
            self._send_json({"ok": True, **record})
            return
        if path == "/api/snapshot":
            self._send_json(self.server.snapshot_payloads())
            return
        if path == "/api/snapshot/write":
            written = write_snapshot(
                self.server.root,
                self.server.snapshot_dir,
                self.server.config,
                clean=True,
                mode="local_operator",
            )
            self._send_json({"ok": True, "files": sorted(written)})
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
        parsed = urlparse(self.path)
        length = int(self.headers.get("content-length") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_error("invalid JSON", status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/briefs" or parsed.path.startswith("/api/briefs/"):
            self._handle_briefs_post(parsed.path, payload)
            return
        if parsed.path == "/api/codex/jobs" or parsed.path.startswith("/api/codex/jobs/"):
            self._handle_codex_post(parsed.path, payload)
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
    serve(Path(args.root).resolve(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
