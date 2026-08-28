from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from wiki_core.config import load_config
from wiki_core.detectors import scan_text
from wiki_core.ingest import run as ingest_run
from wiki_core.performance.fixtures import fixture_identity, materialize_fixture
from wiki_core.performance.identity import source_subject
from wiki_core.performance.models import (
    PLAN_SCHEMA_VERSION,
    PerformanceContractError,
    read_json,
    sha256_value,
    validate_plan,
    write_json,
)
from wiki_core.performance.profiles import profile_for
from wiki_core.performance.runner import PerformanceRunner, _app_source_digest
from wiki_core.performance.telemetry import TelemetryRecorder

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_node_dependency_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_PERFORMANCE_NODE_MODULES", raising=False)


def _git_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "wiki.config.yaml").write_text("repo_id: performance-test\n", encoding="utf-8")
    (root / "README.md").write_text("# Test\n", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    app = root / "apps/wiki-cockpit"
    (app / "node_modules").mkdir(parents=True)
    (app / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (app / "node_modules/.package-lock.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    subprocess.run(["git", "commit", "-m", "test"], cwd=root, check=True, capture_output=True, env=env)


def test_fixture_profiles_are_deterministic_and_exact() -> None:
    for name in ("cycle1", "standard", "stress", "soak"):
        profile = profile_for(name)
        first = fixture_identity(profile, 469)
        second = fixture_identity(profile, 469)
        assert first == second
        assert first["counts"] == {
            "pages": profile.pages,
            "relations": profile.relations,
            "events": profile.events,
        }
        assert fixture_identity(profile, 470)["fixture_sha256"] != first["fixture_sha256"]


def test_materialized_cycle1_fixture_is_public_synthetic_and_reproducible(tmp_path: Path) -> None:
    profile = profile_for("cycle1")
    first_root = tmp_path / "one"
    second_root = tmp_path / "two"
    first = materialize_fixture(ROOT, first_root, profile, 469)
    second = materialize_fixture(ROOT, second_root, profile, 469)
    assert first["fixture_sha256"] == second["fixture_sha256"]
    assert first["git_sha"] == second["git_sha"]
    assert len(list((first_root / "memories/example").glob("*.md"))) == 100
    assert len((first_root / "data/performance/relations.jsonl").read_text(encoding="utf-8").splitlines()) == 1_000
    assert len((first_root / "data/performance/events.jsonl").read_text(encoding="utf-8").splitlines()) == 100
    findings = []
    for path in first_root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            findings.extend(scan_text(path.read_text(encoding="utf-8", errors="replace")))
    assert [finding for finding in findings if finding.category == "secret"] == []
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in first_root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    ).lower()
    assert "/users/" not in text
    assert "private-user-name" not in text


def test_dirty_source_subject_is_verifiable_but_not_claimed_clean(tmp_path: Path) -> None:
    _git_repo(tmp_path / "repo")
    root = tmp_path / "repo"
    clean = source_subject(root)
    assert clean["clean"] is True
    (root / "README.md").write_text("# Changed\n", encoding="utf-8")
    dirty = source_subject(root)
    assert dirty["clean"] is False
    assert dirty["head_sha"] == clean["head_sha"]
    assert dirty["subject_sha256"] != clean["subject_sha256"]


def test_staged_app_digest_ignores_only_declared_build_outputs(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "source.ts").write_text("export const value = 1;\n", encoding="utf-8")
    baseline = _app_source_digest(app)
    (app / "tsconfig.tsbuildinfo").write_text("generated\n", encoding="utf-8")
    (app / "dist").mkdir()
    (app / "dist/output.js").write_text("generated\n", encoding="utf-8")
    assert _app_source_digest(app) == baseline
    (app / "source.ts").write_text("export const value = 2;\n", encoding="utf-8")
    assert _app_source_digest(app) != baseline


def test_plan_schema_fails_closed_on_stale_or_fabricated_digest() -> None:
    payload = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "harness_version": "wiki_performance_harness.v1",
        "created_at": "2026-01-01T00:00:00Z",
        "source_subject": {},
        "profile": {},
        "fixture": {},
        "config_sha256": "0" * 64,
        "toolchain": {},
        "commands": [],
        "command_registry_sha256": sha256_value([]),
        "measurement_policy": {},
        "heavy_authorization": {},
    }
    payload["plan_sha256"] = sha256_value(payload)
    validate_plan(payload)
    payload["commands"].append("fabricated")
    with pytest.raises(PerformanceContractError, match="plan_sha256"):
        validate_plan(payload)


def test_heavy_profiles_require_three_independent_authorization_signals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_VIVA_PERFORMANCE_USER_AUTHORIZATION", raising=False)
    _git_repo(tmp_path / "repo")
    runner = PerformanceRunner(tmp_path / "repo")
    plan_path = tmp_path / "standard-plan.json"
    plan = runner.create_plan(plan_path, profile_name="standard")
    dry = runner.dry_run(plan_path)
    assert dry["will_execute"] is False
    assert dry["guard"] == "blocked_by_default_requires_new_explicit_user_authorization"
    with pytest.raises(PerformanceContractError, match="heavy profile blocked"):
        runner._authorize_heavy(plan, allow_heavy=True, confirm_plan_sha=plan["plan_sha256"])
    monkeypatch.setenv(
        "WIKI_VIVA_PERFORMANCE_USER_AUTHORIZATION",
        f"{plan['plan_sha256']}:authorized",
    )
    runner._authorize_heavy(plan, allow_heavy=True, confirm_plan_sha=plan["plan_sha256"])


def test_invalid_plan_cannot_create_evidence_or_mutate(tmp_path: Path) -> None:
    _git_repo(tmp_path / "repo")
    runner = PerformanceRunner(tmp_path / "repo")
    plan = tmp_path / "bad.json"
    plan.write_text("{}\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    with pytest.raises(PerformanceContractError):
        runner.run(plan, evidence)
    assert not evidence.exists()


def _reseal_plan(plan: dict[str, object]) -> None:
    plan["plan_sha256"] = sha256_value({key: value for key, value in plan.items() if key != "plan_sha256"})


def test_toolchain_and_fixture_divergence_fail_even_if_plan_is_coherently_resealed(tmp_path: Path) -> None:
    _git_repo(tmp_path / "repo")
    runner = PerformanceRunner(tmp_path / "repo")
    plan_path = tmp_path / "plan.json"
    runner.create_plan(plan_path, profile_name="cycle1")

    toolchain_plan = read_json(plan_path)
    toolchain_plan["toolchain"]["python_version"] = "0.0.0"
    toolchain_plan["toolchain"]["toolchain_sha256"] = sha256_value(
        {key: value for key, value in toolchain_plan["toolchain"].items() if key != "toolchain_sha256"}
    )
    _reseal_plan(toolchain_plan)
    with pytest.raises(PerformanceContractError, match="toolchain changed"):
        runner._verify_plan_bindings(toolchain_plan)

    fixture_plan = read_json(plan_path)
    fixture_plan["fixture"]["records_sha256"] = "0" * 64
    fixture_plan["fixture"]["fixture_sha256"] = sha256_value(
        {key: value for key, value in fixture_plan["fixture"].items() if key != "fixture_sha256"}
    )
    _reseal_plan(fixture_plan)
    with pytest.raises(PerformanceContractError, match="fixture generator diverged"):
        runner._verify_plan_bindings(fixture_plan)


def test_resume_rejects_tampered_completed_output(tmp_path: Path) -> None:
    _git_repo(tmp_path / "repo")
    runner = PerformanceRunner(tmp_path / "repo")
    plan_path = tmp_path / "plan.json"
    plan = runner.create_plan(plan_path, profile_name="cycle1")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    state = runner._load_or_create_state(evidence, plan, resume=False)
    runner._run_step("probe", evidence, state, lambda: {"ok": True})
    output = evidence / "steps/probe.json"
    output.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PerformanceContractError, match="stale or missing"):
        runner._run_step("probe", evidence, state, lambda: {"ok": True})


def test_ingestion_observer_is_opt_in_and_preserves_functional_result(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixture"
    materialize_fixture(ROOT, fixture_root, profile_for("cycle1"), 469)
    source = fixture_root / "source.md"
    source.write_text("# Synthetic source\n\nBounded public content.\n", encoding="utf-8")
    config = load_config(fixture_root)
    plain = ingest_run(str(source), "example", fixture_root, config, write=False, record_score=False)
    recorder = TelemetryRecorder()
    observed = ingest_run(
        str(source),
        "example",
        fixture_root,
        config,
        write=False,
        record_score=False,
        observer=recorder.observe,
    )
    assert observed.to_dict() == plain.to_dict()
    stages = {sample["stage"] for sample in recorder.samples}
    assert {
        "manifest_hash",
        "extraction",
        "chunking",
        "raw_scan",
        "extracted_text_scan",
        "input_stage_context",
        "llm_request",
    }.issubset(stages)
