"""Codex job runner — the execute exit for work briefs.

A job takes a persisted work brief (by id + sha), runs Codex headlessly and
sandboxed on the wiki working tree, and hands the result to the EXISTING
``git_workflows`` so it lands as a ``wiki/<theme>`` branch + commit + (optionally)
a draft PR. Codex proposes; the human disposes — the runner never pushes to the
default branch, never opens a non-draft PR, never merges. Those are physically
unavailable: every git step goes through the prefix-gated, always-draft
``run_git_workflow`` verbatim.

Integrity: the exact brief text the operator saw is what runs. ``submit`` rejects
a sha mismatch and blocks a brief whose target files changed since it was
composed (the staleness guard), so a job never silently runs stale evidence.

Safety model: one serialized job stream (a single worker draining a queue of
one), a per-job subprocess timeout, cooperative cancel, and JSONL output scrubbed
by the same secret redaction the rest of the toolkit uses. No LLM client enters
Python — Codex is an external subprocess, exactly like the other allowlisted
commands. If Codex is not usable the job fails honestly with a reason.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths
from wiki_core.web.briefs import BriefStore, hash_targets
from wiki_core.web.commands import SECRET_VALUE_RE
from wiki_core.web.git_workflows import run_git_workflow

CODEX_JOB_SCHEMA_VERSION = "wiki_web_codex_job.v1"

_DEFAULT_JOB_TIMEOUT = 600  # seconds; a per-job wall clock on the Codex subprocess

_STEP_TEMPLATE = [
    ("ground", "Ground the brief"),
    ("branch", "Create proposal branch"),
    ("codex", "Run Codex"),
    ("commit", "Stage + commit"),
    ("publish", "Publish + open draft PR"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def build_codex_argv(binary: str, root: Path, final_path: Path) -> list[str]:
    """The headless, sandboxed, streamed Codex invocation. Never ``--yolo`` /
    ``--dangerously-bypass-*``; network stays off under ``workspace-write``."""
    return [
        binary,
        "exec",
        "-",  # read the whole brief from stdin
        "--cd",
        str(root),
        "--sandbox",
        "workspace-write",
        "-a",
        "on-request",
        "--json",
        "-o",
        str(final_path),
    ]


class JobRunner:
    """Single-worker, queue-of-one Codex job runner with an on-disk job store."""

    def __init__(
        self,
        root: Path,
        config: WikiConfig,
        *,
        codex_cmd: list[str] | None = None,
        timeout_seconds: int = _DEFAULT_JOB_TIMEOUT,
        autostart: bool = True,
    ) -> None:
        self.root = root
        self.config = config
        codex_cfg = getattr(config, "codex", {}) or {}
        binary = str(codex_cfg.get("binary") or "codex")
        # codex_cmd lets tests point at a shim; production uses [binary].
        self.codex_cmd = list(codex_cmd) if codex_cmd else [binary]
        self.timeout_seconds = timeout_seconds
        self.dir = WikiPaths(root, config).derived_root / "codex-jobs"
        self.briefs = BriefStore(root, config)
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancelled: set[str] = set()
        self._running_id: str | None = None  # the job the worker has claimed
        self._worker: threading.Thread | None = None
        if autostart:
            self.start()

    # -- lifecycle ---------------------------------------------------------- #
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()

    def _drain(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self.run_job(job_id)
            except Exception as exc:  # noqa: BLE001 - a job never crashes the worker
                self._fail(job_id, f"runner error: {exc}")
            finally:
                with self._lock:
                    if self._running_id == job_id:
                        self._running_id = None
                self._queue.task_done()

    # -- store helpers ------------------------------------------------------ #
    def _record_path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def _job_dir(self, job_id: str) -> Path:
        return self.dir / job_id

    def _write(self, record: dict[str, Any]) -> dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        record["updated_at"] = _now_iso()
        self._record_path(record["job_id"]).write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
        )
        return record

    def get(self, job_id: str) -> dict[str, Any] | None:
        path = self._record_path(job_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def list(self) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in self.dir.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        records.sort(key=lambda r: str(r.get("created_at")), reverse=True)
        return records

    def read_log(self, job_id: str) -> str:
        log = self._job_dir(job_id) / "log.jsonl"
        if not log.is_file():
            return ""
        return log.read_text(encoding="utf-8")

    def _set_status(self, record: dict[str, Any], status: str, *, reason: str = "") -> dict[str, Any]:
        record["status"] = status
        if reason:
            record["reason"] = reason
        # Wall-clock milestones so the monitoring surface can show honest
        # elapsed/turnaround times (updated_at moves on every write, so it
        # cannot serve as either).
        if status == "running" and not record.get("started_at"):
            record["started_at"] = _now_iso()
        if status in {"delivered", "failed", "cancelled"} and not record.get("finished_at"):
            record["finished_at"] = _now_iso()
        return self._write(record)

    def _set_step(self, record: dict[str, Any], step_id: str, status: str) -> dict[str, Any]:
        for step in record["steps"]:
            if step["id"] == step_id:
                step["status"] = status
        return self._write(record)

    def _fail(self, job_id: str, reason: str) -> None:
        record = self.get(job_id)
        if record and record["status"] not in {"done", "cancelled"}:
            self._set_status(record, "failed", reason=reason)

    def _dirty_hashes(self) -> dict[str, str]:
        """Content fingerprint of every uncommitted path. This is the baseline
        that lets an in-place job commit ONLY what Codex changed — the owner's
        in-progress edits must never be swept into a job commit."""
        from wiki_core.web.git_ops import build_git_state

        fingerprints: dict[str, str] = {}
        for entry in build_git_state(self.root, self.config)["worktree"]["changed_files"]:
            path = str(entry.get("path") or "")
            if not path:
                continue
            file = self.root / path
            if file.is_file():
                proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                    ["git", "hash-object", "--", path],
                    cwd=self.root, capture_output=True, text=True, check=False,
                )
                fingerprints[path] = proc.stdout.strip() or "unhashable"
            else:
                fingerprints[path] = "deleted"
        return fingerprints

    # -- submit ------------------------------------------------------------- #
    def submit(
        self, *, brief_id: str, brief_sha: str, dry_run: bool = True, force: bool = False,
        parent_job_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate + enqueue. Returns the queued record, or an ``ok:False``
        rejection (sha mismatch / stale targets / unknown brief / codex unusable)."""
        brief = self.briefs.get(brief_id)
        if brief is None:
            return {"ok": False, "error": "unknown brief", "brief_id": brief_id}
        if brief.get("brief_sha") != brief_sha:
            return {
                "ok": False,
                "error": "brief changed since you saw it — recompose before running",
                "brief_id": brief_id,
                "reason": "sha_mismatch",
            }
        # Staleness guard: the page targets must not have moved under the brief.
        # Resume/return briefs have no page targets (target_paths is empty) — that
        # is not a hole: their branch is validated at run time by switch_proposal,
        # which fails honestly if the branch was merged or deleted.
        current = hash_targets(self.root, brief.get("target_paths", []))
        if not force and current != brief.get("target_hashes", {}):
            return {
                "ok": False,
                "error": "targets changed since this brief was composed — recompose or confirm",
                "brief_id": brief_id,
                "reason": "targets_stale",
            }
        # A return brief continues an existing proposal branch instead of forking.
        resume = (brief.get("spec", {}).get("grounding") or {}).get("resume")
        resume_branch = resume.get("branch") if resume else None
        if resume and not parent_job_id:
            parent_job_id = resume.get("parent_job_id")
        job_id = "j" + uuid.uuid4().hex[:12]
        record = {
            "job_id": job_id,
            "schema_version": CODEX_JOB_SCHEMA_VERSION,
            "brief_id": brief_id,
            "brief_sha": brief_sha,
            "parent_job_id": parent_job_id,
            "resume_branch": resume_branch,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "status": "queued",
            "reason": "",
            "dry_run": bool(dry_run),
            "mission_kind": brief.get("spec", {}).get("mission_kind"),
            "intent": brief.get("spec", {}).get("intent", ""),
            "theme": brief.get("spec", {}).get("theme", "update"),
            "steps": [{"id": sid, "label": label, "status": "pending"} for sid, label in _STEP_TEMPLATE],
            "codex": {"final_message_path": None, "session_started": False},
            "branch": None,
            "branch_mode": None,
            "draft_pr_url": None,
            "log_path": f"codex-jobs/{job_id}/log.jsonl",
            "human_gate_state": None,
        }
        self._write(record)
        self.briefs.set_status(brief_id, "executed", job_id=job_id)
        self._queue.put(job_id)
        return {"ok": True, **record}

    # -- run ---------------------------------------------------------------- #
    def run_job(self, job_id: str) -> dict[str, Any]:
        record = self.get(job_id)
        if record is None:
            return {"ok": False, "error": "unknown job"}
        # Claim the job atomically with the cancel path: if a cancel landed while
        # this was still queued, honor it; otherwise mark it claimed so a
        # concurrent cancel knows the worker already owns it (no false "cancelled"
        # on a job that actually runs).
        with self._lock:
            if job_id in self._cancelled:
                return self._set_status(record, "cancelled", reason="cancelled before start")
            self._running_id = job_id
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        brief = self.briefs.get(record["brief_id"])
        if brief is None:
            return self._set_status(record, "failed", reason="brief disappeared")
        # Integrity re-check (TOCTOU): the sha was verified at submit, but the
        # brief file could have changed on disk since. Execute ONLY text that
        # still matches the job's recorded sha.
        import hashlib

        if hashlib.sha256(brief["text"].encode("utf-8")).hexdigest() != record.get("brief_sha"):
            return self._set_status(record, "failed", reason="brief changed on disk since submit — recompose")

        self._set_status(record, "running")
        self._set_step(record, "ground", "complete")
        theme = record["theme"]
        resume_branch = record.get("resume_branch")

        if job_id in self._cancelled:  # cancel landed after the claim
            return self._set_status(record, "cancelled", reason="cancelled")

        # 1) Get onto a proposal branch. Three modes:
        #    - resume: a return CONTINUES the parent's branch (switch, needs clean tree);
        #    - continue_current: the repo is ALREADY on a proposal branch — the
        #      operator's normal mid-work state. Work in place: no switch, no
        #      clean-tree requirement; the commit step scopes to Codex's delta so
        #      the owner's uncommitted work is never swept into the job commit;
        #    - fresh: create a new branch (needs a clean tree).
        from wiki_core.web.git_ops import build_git_state

        prefix = str(self.config.approval.get("branch_prefix") or "wiki/")
        git_state = build_git_state(self.root, self.config)
        current_branch = str(git_state.get("current_branch") or "")
        default_branch = str(git_state.get("default_branch") or "main")
        branch_mode = "fresh"
        if resume_branch:
            branch_mode = "resume"
            start = run_git_workflow(self.root, self.config, "switch_proposal", {"branch": resume_branch}, dry_run=False)
            branch = resume_branch
        elif current_branch.startswith(prefix) and current_branch != default_branch:
            branch_mode = "continue_current"
            start = {"ok": True}
            branch = current_branch
        else:
            start = run_git_workflow(self.root, self.config, "start_proposal", {"theme": theme}, dry_run=False)
            branch = start.get("data", {}).get("branch")
        if not start.get("ok"):
            self._set_step(record, "branch", "failed")
            return self._set_status(record, "failed", reason=f"branch: {start.get('error') or start.get('summary')}")
        record["branch"] = branch
        record["branch_mode"] = branch_mode
        self._set_step(self._write(record), "branch", "complete")

        # Baseline BEFORE Codex runs: in continue_current mode these paths (and
        # these exact contents) belong to the owner, not to this job.
        baseline = self._dirty_hashes() if branch_mode == "continue_current" else {}

        def unwind() -> None:
            # Failure/cancel cleanup. NEVER reset --hard over the owner's
            # in-progress edits: in continue_current we only unstage and stay on
            # the branch (Codex's edits stay visible, uncommitted, for review).
            if branch_mode == "continue_current":
                subprocess.run(["git", "reset"], cwd=self.root, capture_output=True, check=False)  # noqa: S603
            else:
                self._abort_branch(branch, delete=branch_mode == "fresh")

        # 2) Run Codex on the branch, streaming redacted JSONL to the log.
        self._set_step(record, "codex", "running")
        final_path = job_dir / "final.md"
        brief_path = job_dir / "brief.md"
        brief_path.write_text(brief["text"], encoding="utf-8")
        # codex_cmd is [binary] in prod, or [python3, shim] in tests; either way
        # the exec flags follow the command prefix.
        argv = [*self.codex_cmd, *build_codex_argv(self.codex_cmd[0], self.root, final_path)[1:]]
        rc, cancelled = self._run_codex(job_id, argv, brief["text"], job_dir / "log.jsonl")
        if cancelled:
            unwind()
            return self._set_status(self.get(job_id) or record, "cancelled", reason="cancelled during Codex run")
        record = self.get(job_id) or record
        if rc != 0:
            self._set_step(record, "codex", "failed")
            unwind()
            return self._set_status(record, "failed", reason=f"codex exited {rc}")
        if final_path.is_file():
            record["codex"]["final_message_path"] = str(final_path.relative_to(self.root)) if final_path.is_relative_to(self.root) else str(final_path)
        self._set_step(self._write(record), "codex", "complete")

        # 3) Stage Codex's delta + commit (single-line message). In
        #    continue_current mode the delta is computed against the baseline:
        #    NEW dirty paths are Codex's; a path that was already dirty and whose
        #    content changed is MIXED (owner + Codex edits, inseparable) — it is
        #    left uncommitted for the owner's review, never committed silently.
        after = self._dirty_hashes()
        codex_paths = sorted(path for path in after if path not in baseline)
        mixed_paths = sorted(path for path in after if path in baseline and after[path] != baseline[path])
        if not codex_paths:
            self._set_step(record, "commit", "failed")
            unwind()
            reason = (
                "Codex only touched file(s) that already had your uncommitted edits "
                f"({', '.join(mixed_paths[:5])}) — commit or stash your work and run it again"
                if mixed_paths
                else "Codex made no file changes"
            )
            return self._set_status(record, "failed", reason=reason)
        stage = run_git_workflow(self.root, self.config, "stage_paths", {"paths": codex_paths}, dry_run=False)
        if not stage.get("ok"):
            self._set_step(record, "commit", "failed")
            unwind()
            return self._set_status(record, "failed", reason=f"stage: {stage.get('error') or stage.get('summary')}")
        message = self._commit_message(record)
        commit = run_git_workflow(self.root, self.config, "commit_proposal", {"message": message}, dry_run=False)
        if not commit.get("ok"):
            self._set_step(record, "commit", "failed")
            # A rejecting commit hook leaves staged edits on the branch — unwind
            # like every other failure so the checkout is never stranded.
            unwind()
            return self._set_status(record, "failed", reason=f"commit: {commit.get('error') or commit.get('summary')}")
        # Honest note appended to the delivery reason: edits Codex made to
        # already-dirty files could NOT be attributed cleanly and stayed
        # uncommitted for the owner's review.
        mixed_note = (
            f" · left {len(mixed_paths)} mixed-edit file(s) uncommitted for your review: " + ", ".join(mixed_paths[:5])
            if mixed_paths
            else ""
        )
        self._set_step(self._write(record), "commit", "complete")

        # 4) Publish + open a draft PR (only when not a dry run).
        record = self.get(job_id) or record
        if record["dry_run"]:
            self._set_step(record, "publish", "skipped")
            record["human_gate_state"] = "local_only"
            return self._set_status(
                record, "delivered", reason="local branch only (dry run) — confirm to publish" + mixed_note
            )
        publish = run_git_workflow(self.root, self.config, "publish_proposal", {}, dry_run=False)
        if not publish.get("ok"):
            self._set_step(record, "publish", "failed")
            return self._set_status(record, "failed", reason=f"publish: {publish.get('error') or publish.get('summary')}")
        body = self._pr_body(final_path)
        # A return updates the existing draft PR; a fresh job opens one. An
        # in-place job updates when the current branch already has a draft PR.
        existing_pr = str(build_git_state(self.root, self.config).get("proposal", {}).get("draft_pr_url") or "")
        pr_op = "update_draft_pr" if (resume_branch or (branch_mode == "continue_current" and existing_pr)) else "open_draft_pr"
        pr = run_git_workflow(
            self.root, self.config, pr_op,
            {"title": f"Codex: {theme}", "body": body}, dry_run=False,
        )
        if not pr.get("ok"):
            self._set_step(record, "publish", "failed")
            return self._set_status(record, "failed", reason=f"draft PR: {pr.get('error') or pr.get('summary')}")
        record["draft_pr_url"] = self._extract_pr_url(pr)
        record["human_gate_state"] = "awaiting_review"
        self._set_step(self._write(record), "publish", "complete")
        return self._set_status(record, "delivered", reason="draft PR opened — the human gate owns it now" + mixed_note)

    # -- codex subprocess --------------------------------------------------- #
    def _run_codex(self, job_id: str, argv: list[str], brief_text: str, log_path: Path) -> tuple[int, bool]:
        try:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                argv,
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except (OSError, ValueError) as exc:
            log_path.write_text(json.dumps({"type": "error", "message": _redact(str(exc))}) + "\n", encoding="utf-8")
            return 127, False
        with self._lock:
            self._procs[job_id] = proc

        # Feed the whole brief on a SEPARATE thread: a large brief can exceed the
        # OS pipe buffer, and writing it to completion before reading stdout would
        # deadlock (the child blocks writing stdout while we block writing stdin).
        def _feed() -> None:
            try:
                if proc.stdin:
                    proc.stdin.write(brief_text)
                    proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        threading.Thread(target=_feed, daemon=True).start()

        # Independent watchdog: kill the process after the timeout even if it
        # produces NO output and never closes stdout (a silent hang would
        # otherwise block the read loop — and the single worker — forever).
        finished = threading.Event()

        def _watchdog() -> None:
            if not finished.wait(self.timeout_seconds):
                proc.kill()

        threading.Thread(target=_watchdog, daemon=True).start()

        with log_path.open("w", encoding="utf-8") as log:
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(_redact(line))
                log.flush()
                if job_id in self._cancelled:
                    proc.terminate()
                    break
        rc = proc.wait()  # stdout is drained/closed (exit, terminate or watchdog kill)
        finished.set()
        with self._lock:
            self._procs.pop(job_id, None)
        return rc, job_id in self._cancelled

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        record = self.get(job_id)
        if record is None:
            return None
        if record["status"] in {"done", "delivered", "failed", "cancelled"}:
            return {"ok": False, "error": f"job already {record['status']}", **record}
        # Set the flag and read the claim atomically w.r.t. run_job's claim.
        with self._lock:
            self._cancelled.add(job_id)
            claimed = self._running_id == job_id
            proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()
        if not claimed:
            # The worker has not claimed it yet (still queued). Finalize now;
            # run_job's own locked check bails if it dequeues this later.
            return {"ok": True, **self._set_status(record, "cancelled", reason="cancelled while queued")}
        # Claimed & running: the read loop / watchdog winds it down and run_job
        # writes the terminal 'cancelled' status itself.
        return {"ok": True, **(self.get(job_id) or record)}

    # -- helpers ------------------------------------------------------------ #
    def _commit_message(self, record: dict[str, Any]) -> str:
        kind = record.get("mission_kind") or "update"
        theme = record.get("theme") or "update"
        msg = f"codex: {kind} {theme}".strip()
        return msg if len(msg) >= 8 else f"codex proposal: {theme}"

    def _pr_body(self, final_path: Path) -> str:
        if final_path.is_file():
            text = final_path.read_text(encoding="utf-8").strip()
            if text:
                return _redact(text)[:4000]
        return "Drafted by Codex from a cockpit work brief. Review before merging."

    def _extract_pr_url(self, pr: dict[str, Any]) -> str | None:
        for result in pr.get("results", []):
            out = str(result.get("stdout") or "")
            for token in out.split():
                if token.startswith("http"):
                    return token
        return None

    def _abort_branch(self, branch: str | None, *, delete: bool = True) -> None:
        """Best-effort return to the default branch after a failed/cancelled run so
        the operator's checkout is not left stranded on a half-built proposal. A
        RETURN keeps the branch (``delete=False``) — it belongs to the parent
        proposal — and only discards this run's uncommitted edits."""
        if not branch:
            return
        default = "main"
        try:
            from wiki_core.web.git_ops import build_git_state

            default = str(build_git_state(self.root, self.config).get("default_branch") or "main")
        except Exception:  # noqa: BLE001
            pass
        # reset --hard clears BOTH staged and unstaged edits back to the branch
        # tip (there are no commits yet on a fresh proposal; on a resume it keeps
        # the parent's commits and only drops this run's uncommitted edits).
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=self.root, capture_output=True, check=False)
        subprocess.run(["git", "switch", default], cwd=self.root, capture_output=True, check=False)
        if delete:
            subprocess.run(["git", "branch", "-D", branch], cwd=self.root, capture_output=True, check=False)
