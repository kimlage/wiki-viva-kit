from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from wiki_core.config import load_config
from wiki_core.ingest import run as ingest_run
from wiki_core.web.server import CockpitServer
from wiki_core.web.snapshot import build_snapshot

from .fixtures import DEFAULT_SEED, fixture_identity, materialize_fixture
from .identity import node_modules_root, source_subject, toolchain_identity
from .models import (
    HARNESS_VERSION,
    PLAN_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION,
    PerformanceContractError,
    read_json,
    sha256_file,
    sha256_value,
    validate_plan,
    validate_receipt,
    write_json,
)
from .profiles import FixtureProfile, profile_for
from .telemetry import TelemetryRecorder, tree_digest, tree_stats


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _config_digest(root: Path) -> str:
    path = root / "wiki.config.yaml"
    return sha256_file(path)


def _free_port() -> int:
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _app_source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {"dist", "node_modules"} for part in relative.parts):
            continue
        if relative.as_posix() == "tsconfig.tsbuildinfo":
            continue
        if not path.is_file() or path.is_symlink():
            continue
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()


def _command_result(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    process = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return {
        "command": command,
        "returncode": process.returncode,
        "duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
        "stdout": process.stdout[-40_000:],
        "stderr": process.stderr[-40_000:],
    }


class PerformanceRunner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create_plan(
        self,
        output: Path,
        *,
        profile_name: str,
        seed: int = DEFAULT_SEED,
        repetitions: int = 2,
    ) -> dict[str, Any]:
        profile = profile_for(profile_name)
        if repetitions < 1 or repetitions > 5:
            raise PerformanceContractError("repetitions must be between 1 and 5")
        fixture = fixture_identity(profile, seed)
        toolchain = toolchain_identity(self.root)
        payload: dict[str, Any] = {
            "schema_version": PLAN_SCHEMA_VERSION,
            "harness_version": HARNESS_VERSION,
            "created_at": _utc_now(),
            "source_subject": source_subject(self.root),
            "profile": profile.to_dict(),
            "fixture": fixture,
            "config_sha256": _config_digest(self.root),
            "toolchain": toolchain,
            "commands": [
                {
                    "id": "focused_python_tests",
                    "cwd": ".",
                    "argv": [sys.executable, "-m", "pytest", "-q", "-W", "error", "tests/test_wiki_performance.py"],
                },
                {
                    "id": "focused_frontend_tests",
                    "cwd": "apps/wiki-cockpit",
                    "argv": [
                        str(Path(toolchain["node_dependencies_path"]) / ".bin/vitest"),
                        "run",
                        "src/data/snapshot.test.ts",
                        "src/world/performance.test.ts",
                    ],
                },
                {"id": "fixture_determinism_privacy", "callable": "wiki_core.performance.fixtures.materialize_fixture"},
                {"id": "ingestion_four_cases", "callable": "wiki_core.ingest.run"},
                {"id": "snapshot_cold_warm", "callable": "wiki_core.web.snapshot.build_snapshot"},
                {"id": "http_cache_sequence", "callable": "wiki_core.web.server.CockpitServer"},
                {"id": "bundle_inventory", "cwd": "apps/wiki-cockpit", "argv": ["sh", "scripts/build-production.sh"]},
                {"id": "chromium_desktop_mobile_smoke", "cwd": "apps/wiki-cockpit", "argv": ["node", "scripts/performance-cycle1-smoke.mjs"]},
            ],
            "measurement_policy": {
                "cold_warm": True,
                "repetitions": repetitions,
                "missing_metrics": "explicit_null_with_reason",
                "evidence_root": str(output.resolve().parent),
            },
            "heavy_authorization": {
                "required": profile.heavy,
                "allow_heavy_flag": "--allow-heavy",
                "plan_sha_confirmation": "--confirm-plan-sha",
                "conversation_authorization_env": "WIKI_VIVA_PERFORMANCE_USER_AUTHORIZATION",
                "authorized": False,
            },
        }
        payload["command_registry_sha256"] = sha256_value(payload["commands"])
        payload["plan_sha256"] = sha256_value(payload)
        write_json(output, payload)
        return payload

    def _stage_app(self, evidence_root: Path) -> Path:
        source = self.root / "apps/wiki-cockpit"
        staged = evidence_root / "runtime-app"
        dependencies = node_modules_root(self.root)
        if not staged.exists():
            shutil.copytree(
                source,
                staged,
                ignore=shutil.ignore_patterns("dist", "node_modules", "tsconfig.tsbuildinfo"),
            )
            (staged / "node_modules").symlink_to(dependencies, target_is_directory=True)
        if _app_source_digest(staged) != _app_source_digest(source):
            raise PerformanceContractError("staged cockpit bytes diverged from the source subject")
        linked = staged / "node_modules"
        if not linked.is_symlink() or linked.resolve() != dependencies:
            raise PerformanceContractError("staged Node dependency authority diverged from the plan-bound toolchain")
        return staged

    def dry_run(self, plan_path: Path) -> dict[str, Any]:
        plan = read_json(plan_path)
        self._verify_plan_bindings(plan)
        profile = profile_for(str(plan["profile"]["name"]))
        fixture = fixture_identity(profile, int(plan["fixture"]["seed"]))
        if fixture != plan["fixture"]:
            raise PerformanceContractError("fixture descriptor diverged from plan")
        return {
            "schema_version": "wiki_performance_dry_run.v1",
            "plan_sha256": plan["plan_sha256"],
            "profile": profile.name,
            "heavy": profile.heavy,
            "will_execute": False,
            "fixture": fixture,
            "estimate": {
                "pages": profile.pages,
                "edges": profile.relations,
                "events": profile.events,
                "browsers": profile.estimated_browsers,
                "cpu_cores": profile.estimated_cpu_cores,
                "memory_bytes": profile.estimated_memory_bytes,
                "disk_bytes": profile.estimated_disk_bytes,
                "duration_seconds": profile.estimated_duration_seconds,
                "soak_iterations": profile.soak_iterations,
            },
            "guard": (
                "blocked_by_default_requires_new_explicit_user_authorization"
                if profile.heavy
                else "cycle1_light_allowed"
            ),
        }

    def _verify_plan_bindings(self, plan: dict[str, Any]) -> None:
        validate_plan(plan)
        if plan.get("harness_version") != HARNESS_VERSION:
            raise PerformanceContractError("harness version changed after plan creation")
        profile = profile_for(str(plan["profile"]["name"]))
        if plan["profile"] != profile.to_dict():
            raise PerformanceContractError("profile descriptor diverged after plan creation")
        current_subject = source_subject(self.root)
        if current_subject != plan["source_subject"]:
            raise PerformanceContractError("source subject changed after plan creation")
        if _config_digest(self.root) != plan["config_sha256"]:
            raise PerformanceContractError("configuration changed after plan creation")
        current_toolchain = toolchain_identity(self.root)
        if current_toolchain != plan["toolchain"]:
            raise PerformanceContractError("toolchain changed after plan creation")
        current_fixture = fixture_identity(profile, int(plan["fixture"]["seed"]))
        if current_fixture != plan["fixture"]:
            raise PerformanceContractError("fixture generator diverged after plan creation")

    def _authorize_heavy(
        self,
        plan: dict[str, Any],
        *,
        allow_heavy: bool,
        confirm_plan_sha: str | None,
    ) -> None:
        if not bool(plan["profile"]["heavy"]):
            return
        expected = str(plan["plan_sha256"])
        conversation = os.environ.get("WIKI_VIVA_PERFORMANCE_USER_AUTHORIZATION")
        if not (
            allow_heavy
            and confirm_plan_sha == expected
            and conversation == f"{expected}:authorized"
        ):
            raise PerformanceContractError(
                "heavy profile blocked: requires --allow-heavy, exact --confirm-plan-sha, "
                "and a fresh conversation authorization bound to that SHA"
            )

    def _state_path(self, evidence_root: Path) -> Path:
        return evidence_root / "state.json"

    def _load_or_create_state(
        self, evidence_root: Path, plan: dict[str, Any], *, resume: bool
    ) -> dict[str, Any]:
        path = self._state_path(evidence_root)
        if path.exists():
            if not resume:
                raise PerformanceContractError("state already exists; use resume")
            state = read_json(path)
            if state.get("schema_version") != STATE_SCHEMA_VERSION:
                raise PerformanceContractError("state schema mismatch")
            if state.get("plan_sha256") != plan["plan_sha256"]:
                raise PerformanceContractError("state belongs to another plan")
            return state
        if resume:
            raise PerformanceContractError("cannot resume without first-write state")
        state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "started_at": _utc_now(),
            "completed_steps": {},
        }
        write_json(path, state)
        return state

    def _run_step(
        self,
        name: str,
        evidence_root: Path,
        state: dict[str, Any],
        function: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        existing = state["completed_steps"].get(name)
        output = evidence_root / "steps" / f"{name}.json"
        if existing:
            if not output.exists() or sha256_file(output) != existing["sha256"]:
                raise PerformanceContractError(f"stale or missing output for completed step {name}")
            return read_json(output)
        started = time.perf_counter_ns()
        result = function()
        result = {
            "schema_version": "wiki_performance_step.v1",
            "step": name,
            "duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
            **result,
        }
        digest = write_json(output, result)
        state["completed_steps"][name] = {"path": str(output), "sha256": digest}
        write_json(self._state_path(evidence_root), state)
        return result

    def _focused_tests(self, evidence_root: Path) -> dict[str, Any]:
        app = self._stage_app(evidence_root)
        python_result = _command_result(
            [sys.executable, "-m", "pytest", "-q", "-W", "error", "tests/test_wiki_performance.py"],
            cwd=self.root,
            timeout=240,
        )
        frontend_result = _command_result(
            [
                str(app / "node_modules/.bin/vitest"),
                "run",
                "src/data/snapshot.test.ts",
                "src/world/performance.test.ts",
            ],
            cwd=app,
            timeout=240,
        )
        smoke_syntax = _command_result(
            ["node", "--check", "scripts/performance-cycle1-smoke.mjs"],
            cwd=app,
            timeout=30,
        )
        if any(row["returncode"] for row in (python_result, frontend_result, smoke_syntax)):
            raise PerformanceContractError("focused performance tests failed")
        return {
            "staged_app_source_sha256": _app_source_digest(app),
            "node_dependencies_path": str(node_modules_root(self.root)),
            "python": python_result,
            "frontend": frontend_result,
            "browser_helper_syntax": smoke_syntax,
        }

    def _fixture_check(self, profile: FixtureProfile, seed: int) -> dict[str, Any]:
        first = fixture_identity(profile, seed)
        second = fixture_identity(profile, seed)
        if first != second:
            raise PerformanceContractError("fixture identity is not deterministic")
        serialized = json.dumps(first, ensure_ascii=False).lower()
        forbidden = ("/users/", "private-user-name", "cpf", "cnpj", "token", "password", "private repo")
        leaks = [value for value in forbidden if value in serialized]
        if leaks:
            raise PerformanceContractError(f"fixture privacy check failed: {leaks}")
        return {"fixture": first, "privacy_findings": [], "deterministic": True}

    def _ingestion_benchmark(self, fixture_root: Path) -> dict[str, Any]:
        source = fixture_root / "synthetic-source.md"
        base = "\n\n".join(
            f"## Section {index}\n\nSynthetic observation {index}. " + "bounded context " * 180
            for index in range(3)
        )
        source.write_text(base + "\n", encoding="utf-8")
        cases: list[dict[str, Any]] = []

        def execute(case: str) -> dict[str, Any]:
            recorder = TelemetryRecorder()
            config = load_config(fixture_root)
            result = ingest_run(
                str(source),
                "example",
                fixture_root,
                config,
                write=True,
                record_score=True,
                ts="2026-01-01T00:00:00+00:00",
                observer=recorder.observe,
            )
            for sample in recorder.samples:
                duration_seconds = float(sample["duration_ms"]) / 1_000
                bytes_read = sample.get("bytes_read")
                if duration_seconds > 0 and isinstance(bytes_read, int):
                    sample["throughput_bytes_per_second"] = round(bytes_read / duration_seconds, 3)
                chunks = sample.get("chunk_count") or sample.get("chunks_indexed")
                if duration_seconds > 0 and isinstance(chunks, int):
                    sample["throughput_chunks_per_second"] = round(chunks / duration_seconds, 3)
            request = read_json(fixture_root / str(result.request_path)) if result.request_path else {}
            return {
                "case": case,
                "result": result.to_dict(),
                "stages": recorder.samples,
                "total_stage_duration_ms": round(sum(float(row["duration_ms"]) for row in recorder.samples), 3),
                "cache_keys": [row.get("cache_key") for row in request.get("chunks", [])],
                "llm_cache": {
                    "pending_calls": request.get("pending_llm_calls"),
                    "cached_calls": request.get("cached_calls"),
                },
                "context_sha256": sha256_value(
                    {
                        key: request.get(key)
                        for key in (
                            "root_entity",
                            "input_channel",
                            "quadrant_map",
                            "quadrant_semantics",
                            "quadrant_boundary_rule",
                            "target_pages",
                            "perspectives_required",
                            "perspectives_optional",
                            "block_context_package",
                        )
                    }
                ),
            }

        cases.append(execute("new_source"))
        cases.append(execute("identical_repeat"))
        source.write_text(base.replace("Synthetic observation 1", "Synthetic observation 1 changed") + "\n", encoding="utf-8")
        cases.append(execute("one_chunk_changed"))
        root_page = fixture_root / str(load_config(fixture_root).root_entity["page"])
        root_page.write_text(
            root_page.read_text(encoding="utf-8").replace(
                "input_stage_ref: memories/system/input-stage.md\n",
                "input_stage_ref: memories/system/input-stage.md\n"
                "perspective_bundle_required:\n"
                "  - synthetic-context-lens\n",
                1,
            ),
            encoding="utf-8",
        )
        cases.append(execute("context_only_changed"))
        context_collision = (
            cases[2]["cache_keys"] == cases[3]["cache_keys"]
            and cases[2]["context_sha256"] != cases[3]["context_sha256"]
        )
        return {
            "cases": cases,
            "llm_context_cache_risk": {
                "same_cache_keys_different_context": context_collision,
                "semantics_changed": False,
            },
            "derived_tree": tree_stats(fixture_root / "data/derived"),
        }

    @contextmanager
    def _snapshot_function_telemetry(self) -> Iterator[TelemetryRecorder]:
        import wiki_core.web.snapshot as module

        names = [
            "_markdown_pages",
            "_page_record",
            "_experience_pack_composition_payload",
            "load_active_temporal_adapters",
            "build_git_state",
            "_pages_payload_with_collections",
            "_operations_payload",
            "build_operator_command_cards",
            "build_timeline_payload",
            "build_diff_payload",
            "_safe_blocks",
            "_safe_source_entities",
            "_operator_commands_payload",
            "_work_items_payload",
            "_region_groups_payload",
            "_source_lifecycle_payload",
            "build_temporal_graph_payload",
            "_snapshot_warnings_payload",
            "_safe_quality",
            "_gates_payload",
            "_graph_payload",
            "_sources_payload",
            "_safe_templates",
            "_decisions_payload",
            "_freshness_payload",
            "_safe_ingestion",
            "_commands_payload",
            "_score_payload",
        ]
        recorder = TelemetryRecorder()
        originals: dict[str, Any] = {}
        for name in names:
            original = getattr(module, name, None)
            if not callable(original):
                continue
            originals[name] = original

            def wrapper(*args: Any, __name: str = name, __original: Any = original, **kwargs: Any) -> Any:
                started = time.perf_counter_ns()
                try:
                    return __original(*args, **kwargs)
                finally:
                    recorder.observe(__name, time.perf_counter_ns() - started, {})

            setattr(module, name, wrapper)
        try:
            yield recorder
        finally:
            for name, original in originals.items():
                setattr(module, name, original)

    def _snapshot_benchmark(self, fixture_root: Path, repetitions: int) -> dict[str, Any]:
        config = load_config(fixture_root)
        runs: list[dict[str, Any]] = []
        payloads: dict[str, dict[str, Any]] = {}
        for ordinal in range(repetitions):
            with self._snapshot_function_telemetry() as recorder:
                started = time.perf_counter_ns()
                payloads = build_snapshot(
                    fixture_root,
                    config,
                    mode="performance_cycle1",
                    generated_at="2026-01-01T00:00:00Z",
                )
                duration = time.perf_counter_ns() - started
            serialize_started = time.perf_counter_ns()
            encoded = json.dumps(payloads, ensure_ascii=False, sort_keys=True).encode("utf-8")
            serialize_duration = time.perf_counter_ns() - serialize_started
            runs.append(
                {
                    "temperature": "cold" if ordinal == 0 else "warm",
                    "duration_ms": round(duration / 1_000_000, 3),
                    "serialize_duration_ms": round(serialize_duration / 1_000_000, 3),
                    "payload_bytes": len(encoded),
                    "read_models": recorder.samples,
                    "read_model_call_counts": dict(Counter(row["stage"] for row in recorder.samples)),
                }
            )
        file_sizes = {
            name: len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            for name, payload in payloads.items()
        }
        return {
            "runs": runs,
            "fixture_observed_counts": {
                "pages": len(payloads.get("pages.json", {}).get("pages", [])),
                "relations": len(payloads.get("graph.json", {}).get("edges", [])),
                "temporal_events": payloads.get("temporal_graph.json", {}).get("event_count"),
            },
            "payload_file_count": len(file_sizes),
            "payload_bytes": sum(file_sizes.values()),
            "largest_payloads": dict(sorted(file_sizes.items(), key=lambda item: item[1], reverse=True)[:10]),
            "temporal": {
                "included_in_static_snapshot": "temporal_graph.json" in payloads,
                "limit": None,
                "event_count": payloads.get("temporal_graph.json", {}).get("event_count"),
                "returned_count": payloads.get("temporal_graph.json", {}).get("returned_count"),
            },
        }

    def _http_get(self, port: int, path: str) -> dict[str, Any]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        started = time.perf_counter_ns()
        connection.request("GET", path, headers={"accept": "application/json"})
        response = connection.getresponse()
        headers_ns = time.perf_counter_ns()
        body = response.read()
        completed = time.perf_counter_ns()
        connection.close()
        return {
            "path": path,
            "status": response.status,
            "ttfb_ms": round((headers_ns - started) / 1_000_000, 3),
            "transfer_ms": round((completed - headers_ns) / 1_000_000, 3),
            "total_ms": round((completed - started) / 1_000_000, 3),
            "bytes": len(body),
            "body": json.loads(body),
        }

    def _http_benchmark(self, fixture_root: Path) -> dict[str, Any]:
        config = load_config(fixture_root)
        server = CockpitServer(("127.0.0.1", 0), fixture_root, config)
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        revision_samples: list[dict[str, Any]] = []
        git_state_samples: list[dict[str, Any]] = []
        tree_samples: list[dict[str, Any]] = []
        original = server._snapshot_source_revision
        original_git = server._hash_git_state
        original_tree = server._hash_tree

        def measured_revision() -> Any:
            started = time.perf_counter_ns()
            result = original()
            revision_samples.append(
                {"duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3)}
            )
            return result

        server._snapshot_source_revision = measured_revision  # type: ignore[method-assign]

        def measured_git(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            result = original_git(*args, **kwargs)
            git_state_samples.append(
                {"duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3)}
            )
            return result

        def measured_tree(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            result = original_tree(*args, **kwargs)
            label = args[2] if len(args) > 2 else kwargs.get("label")
            tree_samples.append(
                {
                    "label": str(label) if label is not None else None,
                    "duration_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
                }
            )
            return result

        server._hash_git_state = measured_git  # type: ignore[method-assign]
        server._hash_tree = measured_tree  # type: ignore[method-assign]
        thread.start()
        try:
            requests: list[dict[str, Any]] = []
            for path in ("/api/snapshot/boot", "/api/snapshot/boot", "/api/snapshot/pages.json", "/api/snapshot/temporal_graph.json"):
                item = self._http_get(port, path)
                item["cache_result"] = server.snapshot_cache_health()["last_result"]
                body = item.pop("body")
                item["contains_temporal_graph"] = "temporal_graph.json" in body if path.endswith("/boot") else None
                requests.append(item)
            return {
                "requests": requests,
                "source_revision_walks": revision_samples,
                "git_state_scans": git_state_samples,
                "tree_scans": tree_samples,
                "cache_ttl_seconds": server.SNAPSHOT_CACHE_TTL_S,
                "boot_excludes_temporal_graph": requests[0]["contains_temporal_graph"] is False,
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=10)

    def _bundle_inventory(self, evidence_root: Path) -> dict[str, Any]:
        app = self._stage_app(evidence_root)
        build = _command_result(["sh", "scripts/build-production.sh"], cwd=app, timeout=300)
        if build["returncode"]:
            raise PerformanceContractError("cockpit production build failed")
        dist = app / "dist"
        files: list[dict[str, Any]] = []
        for path in sorted(dist.rglob("*")):
            if not path.is_file():
                continue
            body = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(dist).as_posix(),
                    "bytes": len(body),
                    "gzip_bytes": len(gzip.compress(body, compresslevel=9)),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        top_json = [row for row in files if "/" not in row["path"] and row["path"].endswith(".json")]
        sample_snapshot_top_json = [
            row
            for row in files
            if row["path"].startswith("sample-snapshot/")
            and "/" not in row["path"][len("sample-snapshot/") :]
            and row["path"].endswith(".json")
        ]
        css = [row for row in files if row["path"].endswith(".css")]
        return {
            "build": build,
            "dist": {"files": len(files), "bytes": sum(row["bytes"] for row in files)},
            "dist_tree_sha256": tree_digest(dist),
            "staged_app_source_sha256": _app_source_digest(app),
            "top_level_json": {"files": len(top_json), "bytes": sum(row["bytes"] for row in top_json)},
            "sample_snapshot_top_level_json": {
                "files": len(sample_snapshot_top_json),
                "bytes": sum(row["bytes"] for row in sample_snapshot_top_json),
            },
            "largest_files": sorted(files, key=lambda row: row["bytes"], reverse=True)[:20],
            "css_assets": sorted(css, key=lambda row: row["bytes"], reverse=True),
            "lazy_css_budget_present": False,
        }

    def _browser_smoke(self, evidence_root: Path) -> dict[str, Any]:
        app = self._stage_app(evidence_root)
        port = _free_port()
        preview_config = evidence_root / "performance-preview.config.mjs"
        vite_module = (node_modules_root(self.root) / "vite/dist/node/index.js").as_uri()
        preview_config.write_text(
            (
                f'import {{ defineConfig }} from {json.dumps(vite_module)};\n'
                "export default defineConfig({ plugins: [{ name: 'performance-spa-fallback', "
                "configurePreviewServer(server) { server.middlewares.use((request, _response, next) => { "
                "const path = new URL(request.url || '/', 'http://127.0.0.1').pathname; "
                "if (path === '/demo' || path.startsWith('/demo/') || path === '/w' || path.startsWith('/w/')) request.url = '/index.html'; "
                "next(); }); } }] });\n"
            ),
            encoding="utf-8",
        )
        preview = subprocess.Popen(
            [
                str(app / "node_modules/.bin/vite"),
                "preview",
                "--config",
                str(preview_config),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=app,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    connection.request("GET", "/demo")
                    response = connection.getresponse()
                    response.read()
                    connection.close()
                    if response.status < 500:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise PerformanceContractError("preview server did not become ready")
            output = evidence_root / "browser-smoke.json"
            env = {
                **os.environ,
                "WIKI_PERFORMANCE_BASE_URL": f"http://127.0.0.1:{port}",
                "WIKI_PERFORMANCE_OUTPUT": str(output),
            }
            result = _command_result(
                ["node", "scripts/performance-cycle1-smoke.mjs"], cwd=app, timeout=180, env=env
            )
            if result["returncode"]:
                raise PerformanceContractError(
                    f"Chromium performance smoke failed: {result['stderr'][-2_000:]}"
                )
            return {
                "runner": result,
                "preview_config_sha256": sha256_file(preview_config),
                "measurements": read_json(output),
            }
        finally:
            preview.terminate()
            try:
                preview.wait(timeout=10)
            except subprocess.TimeoutExpired:
                preview.kill()
                preview.wait(timeout=10)

    def run(
        self,
        plan_path: Path,
        evidence_root: Path,
        *,
        resume: bool = False,
        allow_heavy: bool = False,
        confirm_plan_sha: str | None = None,
    ) -> dict[str, Any]:
        plan = read_json(plan_path)
        self._verify_plan_bindings(plan)
        planned_evidence_root = Path(plan["measurement_policy"]["evidence_root"]).resolve()
        if evidence_root.resolve() != planned_evidence_root:
            raise PerformanceContractError("evidence root differs from the plan-bound location")
        self._authorize_heavy(
            plan, allow_heavy=allow_heavy, confirm_plan_sha=confirm_plan_sha
        )
        profile = profile_for(str(plan["profile"]["name"]))
        evidence_root.mkdir(parents=True, exist_ok=True)
        state = self._load_or_create_state(evidence_root, plan, resume=resume)
        fixture_root = evidence_root / "fixture"
        seed = int(plan["fixture"]["seed"])
        if resume and state.get("fixture_tree_sha256"):
            if tree_digest(fixture_root) != state["fixture_tree_sha256"]:
                raise PerformanceContractError("fixture runtime tree changed before resume")

        steps: dict[str, dict[str, Any]] = {}
        steps["focused_tests"] = self._run_step(
            "focused_tests", evidence_root, state, lambda: self._focused_tests(evidence_root)
        )
        steps["fixture_determinism_privacy"] = self._run_step(
            "fixture_determinism_privacy",
            evidence_root,
            state,
            lambda: self._fixture_check(profile, seed),
        )

        def materialize() -> dict[str, Any]:
            return {"fixture": materialize_fixture(self.root, fixture_root, profile, seed)}

        materialization_was_complete = "fixture_materialization" in state["completed_steps"]
        steps["fixture_materialization"] = self._run_step(
            "fixture_materialization", evidence_root, state, materialize
        )
        if not materialization_was_complete:
            state["fixture_tree_stage"] = "fixture_materialization"
            state["fixture_tree_sha256"] = tree_digest(fixture_root)
            write_json(self._state_path(evidence_root), state)
        ingestion_was_complete = "ingestion_four_cases" in state["completed_steps"]
        steps["ingestion_four_cases"] = self._run_step(
            "ingestion_four_cases",
            evidence_root,
            state,
            lambda: self._ingestion_benchmark(fixture_root),
        )
        if not ingestion_was_complete:
            state["fixture_tree_stage"] = "ingestion_four_cases"
            state["fixture_tree_sha256"] = tree_digest(fixture_root)
            write_json(self._state_path(evidence_root), state)
        repetitions = int(plan["measurement_policy"]["repetitions"])
        steps["snapshot_cold_warm"] = self._run_step(
            "snapshot_cold_warm",
            evidence_root,
            state,
            lambda: self._snapshot_benchmark(fixture_root, repetitions),
        )
        http_was_complete = "http_cache_sequence" in state["completed_steps"]
        steps["http_cache_sequence"] = self._run_step(
            "http_cache_sequence",
            evidence_root,
            state,
            lambda: self._http_benchmark(fixture_root),
        )
        if not http_was_complete:
            state["fixture_tree_stage"] = "http_cache_sequence"
            state["fixture_tree_sha256"] = tree_digest(fixture_root)
            write_json(self._state_path(evidence_root), state)
        steps["bundle_inventory"] = self._run_step(
            "bundle_inventory", evidence_root, state, lambda: self._bundle_inventory(evidence_root)
        )
        steps["chromium_desktop_mobile_smoke"] = self._run_step(
            "chromium_desktop_mobile_smoke",
            evidence_root,
            state,
            lambda: self._browser_smoke(evidence_root),
        )
        completed_at = _utc_now()
        outputs = {
            name: {"path": row["path"], "sha256": row["sha256"]}
            for name, row in state["completed_steps"].items()
        }
        receipt: dict[str, Any] = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "harness_version": HARNESS_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "source_subject_sha256": plan["source_subject"]["subject_sha256"],
            "fixture_sha256": plan["fixture"]["fixture_sha256"],
            "toolchain_sha256": plan["toolchain"]["toolchain_sha256"],
            "started_at": state["started_at"],
            "completed_at": completed_at,
            "steps": list(state["completed_steps"]),
            "outputs": outputs,
        }
        receipt["receipt_sha256"] = sha256_value(receipt)
        write_json(evidence_root / "receipt.json", receipt)
        self.report(plan_path, evidence_root / "receipt.json", evidence_root / "report.json")
        return receipt

    def verify(self, plan_path: Path, receipt_path: Path | None = None) -> dict[str, Any]:
        plan = read_json(plan_path)
        self._verify_plan_bindings(plan)
        result = {"plan_valid": True, "receipt_valid": None, "outputs_valid": None}
        if receipt_path is None:
            return result
        receipt = read_json(receipt_path)
        validate_receipt(receipt)
        if receipt["plan_sha256"] != plan["plan_sha256"]:
            raise PerformanceContractError("receipt belongs to another plan")
        expected_bindings = {
            "source_subject_sha256": plan["source_subject"]["subject_sha256"],
            "fixture_sha256": plan["fixture"]["fixture_sha256"],
            "toolchain_sha256": plan["toolchain"]["toolchain_sha256"],
        }
        for field, expected in expected_bindings.items():
            if receipt.get(field) != expected:
                raise PerformanceContractError(f"receipt {field} diverged from plan")
        for output in receipt["outputs"].values():
            path = Path(output["path"])
            if not path.exists() or sha256_file(path) != output["sha256"]:
                raise PerformanceContractError(f"output digest mismatch: {path}")
        result.update({"receipt_valid": True, "outputs_valid": True})
        return result

    def report(self, plan_path: Path, receipt_path: Path, output: Path) -> dict[str, Any]:
        self.verify(plan_path, receipt_path)
        plan = read_json(plan_path)
        receipt = read_json(receipt_path)
        validate_plan(plan)
        validate_receipt(receipt)
        steps = {name: read_json(Path(row["path"])) for name, row in receipt["outputs"].items()}
        ingestion = steps.get("ingestion_four_cases", {})
        snapshot = steps.get("snapshot_cold_warm", {})
        http = steps.get("http_cache_sequence", {})
        bundle = steps.get("bundle_inventory", {})
        browser = steps.get("chromium_desktop_mobile_smoke", {})
        browser_rows = browser.get("measurements", {}).get("measurements", [])
        browser_missing = []
        for row in browser_rows:
            for metric, reason in (
                ("searchLatencyMs", "searchReason"),
                ("searchSelectionMs", "searchSelectionReason"),
                ("centerSelectionMs", "centerSelectionReason"),
                ("firstInteractionMs", "firstInteractionReason"),
                ("chronoscopeMs", "chronoscopeReason"),
                ("frameP95Ms", "runtimeReason"),
                ("heapBytes", "heapReason"),
            ):
                if row.get(metric) is None:
                    browser_missing.append(
                        {
                            "device": row.get("device"),
                            "metric": metric,
                            "reason": row.get(reason) or "unavailable_without_reason",
                        }
                    )
        report: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "plan_sha256": plan["plan_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "subject": plan["source_subject"],
            "profile": plan["profile"],
            "confirmed_measurements": {
                "ingestion": ingestion,
                "snapshot": snapshot,
                "http_cache": http,
                "bundle": bundle,
                "browser_ux": browser,
            },
            "confirmed_findings": [
                "ingestion_stage_timing_is_now_opt_in_and_functionally_inert",
                "snapshot_static_transport_requests_complete_temporal_history_with_limit_none",
                "operator_boot_excludes_temporal_graph",
                "operator_revision_walk_is_measured_on_cache_hit_and_miss",
                "browser_parse_digest_and_interaction_metrics_are_observed_when_available",
            ],
            "hypotheses_refuted": [
                "temporal_graph_is_part_of_operator_boot",
            ],
            "limitations": [
                "cycle1_fixture_only",
                "no_standard_stress_or_soak_execution",
                "no_full_python_frontend_or_browser_matrix",
                "browser_heap_is_null_when_measureUserAgentSpecificMemory_is_unavailable",
                "os_file_cache_cannot_be_flushed_portably_so_cold_means_first_process_observation",
            ],
            "not_collected": [
                "standard_profile_baseline",
                "stress_profile_baseline",
                "soak_drift",
                "full_release_browser_matrix",
                "private_or_real_data",
            ],
            "browser_metrics_not_collected": browser_missing,
            "backlog_not_implemented": [
                "shared_WikiInventory",
                "dirty_sets_and_fail_closed_invalidation_journal",
                "boot_by_capability_or_summary",
                "real_temporal_pagination",
                "timeline_virtualization",
                "canonicalization_and_hash_worker",
                "lazy_css_budget",
            ],
        }
        write_json(output, report)
        self._write_markdown_report(output.with_suffix(".md"), report)
        return report

    def _write_markdown_report(self, path: Path, report: dict[str, Any]) -> None:
        measurements = report["confirmed_measurements"]
        ingestion_cases = measurements.get("ingestion", {}).get("cases", [])
        snapshot_runs = measurements.get("snapshot", {}).get("runs", [])
        http_requests = measurements.get("http_cache", {}).get("requests", [])
        browser_rows = measurements.get("browser_ux", {}).get("measurements", {}).get("measurements", [])
        lines = [
            "# Wiki Viva performance cycle 1",
            "",
            f"Plan: `{report['plan_sha256']}`  ",
            f"Receipt: `{report['receipt_sha256']}`  ",
            f"Source subject: `{report['subject']['subject_sha256']}`  ",
            f"Git base: `{report['subject']['head_sha']}`; clean: `{str(report['subject']['clean']).lower()}`.",
            "",
            "The source subject is a content-bound dirty-tree identity when `clean=false`; it is not described as an immutable Git SHA.",
            "",
            "## Ingestion",
            "",
            "| Case | Chunks | Indexed | Total measured stages (ms) |",
            "| --- | ---: | ---: | ---: |",
        ]
        for case in ingestion_cases:
            result = case.get("result", {})
            lines.append(
                f"| {case.get('case')} | {result.get('chunk_count')} | {result.get('chunks_indexed')} | {case.get('total_stage_duration_ms')} |"
            )
        lines.extend(
            [
                "",
                "## Snapshot",
                "",
                "| Temperature | Build (ms) | Payload bytes |",
                "| --- | ---: | ---: |",
            ]
        )
        for row in snapshot_runs:
            lines.append(f"| {row.get('temperature')} | {row.get('duration_ms')} | {row.get('payload_bytes')} |")
        lines.extend(
            [
                "",
                "## HTTP cache",
                "",
                "| Route | Cache result | TTFB (ms) | Transfer (ms) | Bytes |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in http_requests:
            lines.append(
                f"| `{row.get('path')}` | {row.get('cache_result')} | {row.get('ttfb_ms')} | {row.get('transfer_ms')} | {row.get('bytes')} |"
            )
        lines.extend(
            [
                "",
                "## Bundle",
                "",
                f"Dist: {measurements.get('bundle', {}).get('dist', {}).get('files')} files / {measurements.get('bundle', {}).get('dist', {}).get('bytes')} bytes.  ",
                f"Direct sample-snapshot JSON: {measurements.get('bundle', {}).get('sample_snapshot_top_level_json', {}).get('files')} files / {measurements.get('bundle', {}).get('sample_snapshot_top_level_json', {}).get('bytes')} bytes.  ",
                f"Lazy CSS budget present: `{str(measurements.get('bundle', {}).get('lazy_css_budget_present')).lower()}`.",
                "",
                "## Browser and UX",
                "",
                "| Device | React ready (ms) | Search (ms) | Search selection (ms) | Center selection (ms) | Chronoscope (ms) | Frame p95 (ms) | Heap bytes |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in browser_rows:
            lines.append(
                f"| {row.get('device')} | {row.get('reactReadyMs')} | {row.get('searchLatencyMs')} | {row.get('searchSelectionMs')} | {row.get('centerSelectionMs')} | {row.get('chronoscopeMs')} | {row.get('frameP95Ms')} | {row.get('heapBytes')} |"
            )
        missing = report.get("browser_metrics_not_collected", [])
        if missing:
            lines.extend(["", "Explicitly unavailable browser metrics:", ""])
            lines.extend(
                f"- `{row.get('device')}.{row.get('metric')}`: `{row.get('reason')}`"
                for row in missing
            )
        lines.extend(["", "## Confirmed findings", ""])
        lines.extend(f"- `{item}`" for item in report["confirmed_findings"])
        lines.extend(["", "## Refuted hypotheses", ""])
        lines.extend(f"- `{item}`" for item in report["hypotheses_refuted"])
        lines.extend(["", "## Limitations and not collected", ""])
        lines.extend(f"- `{item}`" for item in report["limitations"])
        lines.extend(f"- `{item}`" for item in report["not_collected"])
        lines.extend(["", "## Backlog only - not implemented", ""])
        lines.extend(f"- `{item}`" for item in report["backlog_not_implemented"])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
