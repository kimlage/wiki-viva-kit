from __future__ import annotations

import fnmatch
import hashlib
import json
import tarfile
from pathlib import Path

import yaml

from wiki_core.upgrade import portable_path_status


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/wiki-upgrade-lanes.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _workflow_jobs() -> dict:
    return _workflow()["jobs"]


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def _write_archive(source: Path, archive: Path) -> None:
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname="handoff")


def _internal_manifest_is_valid(root: Path) -> bool:
    manifest = json.loads((root / "handoff.json").read_text(encoding="utf-8"))
    payload = (root / "payload.txt").read_bytes()
    return manifest["payload_sha256"] == hashlib.sha256(payload).hexdigest()


def _acceptance_anchor_from_plan_stdout(stdout: str) -> str:
    payloads = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
    summaries = [
        item
        for item in payloads
        if item.get("schema_version") == "wiki_viva_upgrade_plan_summary.v1"
    ]
    if len(summaries) != 1:
        raise ValueError("expected exactly one plan summary")
    return str(summaries[0]["acceptance_anchor_sha256"])


def test_pr_paths_cover_runner_toolchain_and_portable_authority() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    paths = set(trigger["pull_request"]["paths"])
    assert {
        ".skills/wiki-*/**",
        "docs/references/fixtures/demo-wiki/**",
        "docs/references/guides/**",
        "docs/references/schemas/**",
        "docs/references/templates/deploy/**",
        "packs/**",
        "requirements.txt",
        "scripts/README.md",
        "scripts/_common.py",
        "scripts/_git_subject.py",
        "scripts/wiki_toolchain_probe.py",
        "scripts/wiki_*.py",
        "scripts/wiki_upgrade*.py",
        "scripts/wiki_visual_evidence.py",
        "tests/test_wiki_node_workspace.py",
        "tests/test_wiki_upgrade_cli.py",
        "tests/test_wiki_visual_evidence.py",
        "wiki_core/**",
    }.issubset(paths)

    package = yaml.safe_load(
        (
            ROOT
            / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml"
        ).read_text(encoding="utf-8")
    )
    portable_scripts = []
    for script in sorted((ROOT / "scripts").glob("wiki_*.py")):
        relative = script.relative_to(ROOT).as_posix()
        allowed, _reason = portable_path_status(relative, package)
        if allowed:
            portable_scripts.append(relative)
    assert portable_scripts
    assert all(
        any(fnmatch.fnmatchcase(relative, pattern) for pattern in paths)
        for relative in portable_scripts
    )


def test_upstream_job_runs_productive_visual_capture_and_capsule_verifier() -> None:
    upstream = _workflow_jobs()["upstream-certification"]
    visual = _step(upstream, "Verify visual evidence implementation")
    prepare = _step(
        upstream, "Prepare exact public cockpit source for productive capture"
    )
    node_authority = _step(
        upstream, "Capture exact external Node workspace authority once"
    )
    capture = _step(upstream, "Capture productive public visual authority")
    certify = _step(
        upstream, "Execute and seal the operator-facing Lane A certification"
    )
    sealed = _step(upstream, "Verify immutable Lane A artifact set")
    verifier = _step(upstream, "Independently verify the sealed Lane A capsule")

    assert "tests/test_wiki_visual_evidence.py" in visual["run"]
    assert 'rm -rf "$ROOT/release-authority"' in prepare["run"]
    assert "capture-authority" in node_authority["run"]
    assert '--source-sha "$SOURCE_SHA"' in node_authority["run"]
    assert "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256" in node_authority["run"]
    assert "wiki_visual_evidence.py\" capture" in capture["run"]
    assert '--out-dir "$ROOT/productive-visual"' in capture["run"]
    assert "observed_in_this_capture_process" in capture["run"]
    assert "productive_authority': False" in capture["run"]
    assert '--visual-root "$ROOT/productive-visual"' in certify["run"]
    assert '--node-workspace-authority "$WIKI_VIVA_NODE_WORKSPACE_AUTHORITY"' in certify[
        "run"
    ]
    assert (
        '--trusted-node-workspace-authority-sha256 '
        '"$WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256"'
        in certify["run"]
    )
    assert "release-authority/visual" not in certify["run"]
    assert "hashes(certified_root) == hashes(captured_root)" in sealed["run"]
    assert (
        "capsule['visual_manifest_sha256'] == capture['visual_manifest_sha256']"
        in sealed["run"]
    )
    names = [step.get("name") for step in upstream["steps"]]
    assert names.index("Prepare exact public cockpit source for productive capture") < names.index(
        "Capture exact external Node workspace authority once"
    )
    assert names.index("Capture exact external Node workspace authority once") < names.index(
        "Capture productive public visual authority"
    )
    assert names.index("Capture productive public visual authority") < names.index(
        "Execute and seal the operator-facing Lane A certification"
    )
    assert "wiki_upgrade.py verify-capsule" in verifier["run"]
    assert "--trusted-attestation-sha256" in verifier["run"]
    assert "--authority" in verifier["run"]


def test_node_workspace_authority_is_captured_once_and_only_in_lane_a() -> None:
    workflow_raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    jobs = _workflow_jobs()
    upstream = jobs["upstream-certification"]
    downstream_ids = ("fast-adoption", "canary", "background-certification")

    assert upstream["timeout-minutes"] == 45
    assert jobs["fast-adoption"]["timeout-minutes"] == 20
    assert jobs["canary"]["timeout-minutes"] == 20
    assert workflow_raw.count("capture-authority") == 1
    assert "npm --prefix" not in workflow_raw
    assert "npm ci" not in workflow_raw
    assert "npx " not in workflow_raw

    for job_id in ("upstream-certification", *downstream_ids):
        job = jobs[job_id]
        setup = next(
            step
            for step in job["steps"]
            if step.get("uses") == "actions/setup-node@v5"
        )
        assert setup["with"]["node-version"] == "22.22.3"
        commands = "\n".join(
            step.get("run", "")
            for step in job["steps"]
            if isinstance(step, dict)
        )
        assert "npm install --global npm@10.9.8" in commands
        assert 'test "$(node --version)" = "v22.22.3"' in commands
        assert 'test "$(npm --version)" = "10.9.8"' in commands
        if job_id in downstream_ids:
            assert "capture-authority" not in commands

    assemble = _step(upstream, "Assemble fail-closed cross-job Lane A bundle")
    assert "node_workspace_authority_sha256" in assemble["run"]
    assert "public-kit/apps/wiki-cockpit/node_modules" in assemble["run"]


def test_every_toolchain_probe_job_installs_the_launched_browser() -> None:
    jobs = _workflow_jobs()
    install_steps = {
        "upstream-certification": "Install certification toolchain",
        "fast-adoption": "Install the certified Playwright command registry",
        "canary": "Install the exact runner and browser toolchain",
        "background-certification": "Install the exact runner and consumer gate toolchain",
    }
    for job_id, step_name in install_steps.items():
        script = _step(jobs[job_id], step_name)["run"]
        assert "python -m playwright install --with-deps chromium" in script


def test_cross_job_handoffs_export_and_consume_raw_archive_sha256() -> None:
    jobs = _workflow_jobs()
    fast = jobs["fast-adoption"]
    canary = jobs["canary"]
    background = jobs["background-certification"]

    assert fast["outputs"]["handoff_archive_sha256"] == (
        "${{ steps.fast_handoff_anchor.outputs.handoff_archive_sha256 }}"
    )
    assert canary["outputs"]["handoff_archive_sha256"] == (
        "${{ steps.canary_handoff_anchor.outputs.handoff_archive_sha256 }}"
    )

    canary_restore = _step(canary, "Restore and verify exact paused state")
    assert canary_restore["env"]["EXPECTED_HANDOFF_ARCHIVE_SHA256"] == (
        "${{ needs['fast-adoption'].outputs.handoff_archive_sha256 }}"
    )
    canary_script = canary_restore["run"]
    assert canary_script.index("hashlib.sha256(archive.read_bytes())") < canary_script.index(
        "tar -C .wiki-viva-ci -xzf"
    )

    background_restore = _step(background, "Restore and verify the same consumer run")
    assert background_restore["env"]["EXPECTED_HANDOFF_ARCHIVE_SHA256"] == (
        "${{ needs['canary'].outputs.handoff_archive_sha256 }}"
    )
    background_script = background_restore["run"]
    assert background_script.index(
        "hashlib.sha256(archive.read_bytes())"
    ) < background_script.index("tar -C .wiki-viva-ci -xzf")


def test_lane_a_archive_is_externally_anchored_before_fast_adoption_extracts_it() -> None:
    jobs = _workflow_jobs()
    upstream = jobs["upstream-certification"]
    fast = jobs["fast-adoption"]

    assert upstream["outputs"]["lane_a_archive_sha256"] == (
        "${{ steps.lane_a_archive_anchor.outputs.lane_a_archive_sha256 }}"
    )
    restore = _step(fast, "Verify and restore exact Lane A release bundle")
    assert restore["env"]["EXPECTED_LANE_A_ARCHIVE_SHA256"] == (
        "${{ needs['upstream-certification'].outputs.lane_a_archive_sha256 }}"
    )
    script = restore["run"]
    assert script.index("hashlib.sha256(archive.read_bytes())") < script.index(
        "tar -C .wiki-viva-ci/lane-a -xzf"
    )


def test_acceptance_anchor_comes_from_plan_stdout_and_crosses_every_resume() -> None:
    jobs = _workflow_jobs()
    fast = jobs["fast-adoption"]
    canary = jobs["canary"]
    background = jobs["background-certification"]

    assert fast["outputs"]["acceptance_anchor_sha256"] == (
        "${{ steps.fast_adoption.outputs.acceptance_anchor_sha256 }}"
    )
    fast_step = _step(fast, "Execute fast adoption and seal resumable runner handoff")
    fast_script = fast_step["run"]
    assert 'PLAN_STDOUT="$(' in fast_script
    assert 'python "$RUNNER" plan' in fast_script
    assert 'printf \'%s\\n\' "$PLAN_STDOUT" | python -c' in fast_script
    assert 'summaries[0]["acceptance_anchor_sha256"]' in fast_script
    assert '"acceptance_anchor_sha256=$ACCEPTANCE_ANCHOR_SHA256"' in fast_script
    assert "'acceptance_anchor_sha256': acceptance_anchor" in fast_script
    assert (
        '--trusted-acceptance-anchor-sha256 "$ACCEPTANCE_ANCHOR_SHA256"'
        in fast_script
    )

    assert canary["outputs"]["acceptance_anchor_sha256"] == (
        "${{ steps.canary_handoff_anchor.outputs.acceptance_anchor_sha256 }}"
    )
    canary_restore = _step(canary, "Restore and verify exact paused state")
    assert canary_restore["env"]["EXPECTED_ACCEPTANCE_ANCHOR_SHA256"] == (
        "${{ needs['fast-adoption'].outputs.acceptance_anchor_sha256 }}"
    )
    assert "manifest['acceptance_anchor_sha256'] == trusted_acceptance" in canary_restore[
        "run"
    ]
    canary_resume = _step(canary, "Resume the exact consumer through served Playwright canary")
    assert 'PLAN="$ROOT/consumer/.wiki-viva/upgrade/plan.json"' in canary_resume["run"]
    assert (
        '--trusted-acceptance-anchor-sha256 "$TRUSTED_ACCEPTANCE_ANCHOR_SHA256"'
        in canary_resume["run"]
    )

    background_restore = _step(background, "Restore and verify the same consumer run")
    assert background_restore["env"]["EXPECTED_ACCEPTANCE_ANCHOR_SHA256"] == (
        "${{ needs['canary'].outputs.acceptance_anchor_sha256 }}"
    )
    assert (
        "manifest['acceptance_anchor_sha256'] == trusted_acceptance"
        in background_restore["run"]
    )
    background_resume = _step(
        background, "Resume only consumer background gates, rollback and reports"
    )
    assert 'PLAN="$ROOT/consumer/.wiki-viva/upgrade/plan.json"' in background_resume[
        "run"
    ]
    assert (
        '--trusted-acceptance-anchor-sha256 "$TRUSTED_ACCEPTANCE_ANCHOR_SHA256"'
        in background_resume["run"]
    )


def test_canary_completion_anchor_crosses_the_background_job_out_of_band() -> None:
    jobs = _workflow_jobs()
    canary = jobs["canary"]
    background = jobs["background-certification"]

    assert canary["outputs"]["canary_completion_anchor_sha256"] == (
        "${{ steps.canary_handoff_anchor.outputs.canary_completion_anchor_sha256 }}"
    )
    served = _step(
        canary, "Resume the exact consumer through served Playwright canary"
    )
    served_script = served["run"]
    assert "wiki_viva_upgrade_canary_completion_summary.v1" in served_script
    assert "canary_completion_anchor_sha256" in served_script

    seal = _step(canary, "Verify and seal the exact post-canary consumer handoff")
    assert seal["env"]["TRUSTED_CANARY_COMPLETION_ANCHOR_SHA256"] == (
        "${{ steps.served_canary.outputs.canary_completion_anchor_sha256 }}"
    )
    assert "canary-completion-anchor.json" in seal["run"]

    restore = _step(background, "Restore and verify the same consumer run")
    assert restore["env"]["EXPECTED_CANARY_COMPLETION_ANCHOR_SHA256"] == (
        "${{ needs['canary'].outputs.canary_completion_anchor_sha256 }}"
    )
    assert "manifest['canary_completion_anchor_sha256']" in restore["run"]
    resume = _step(
        background, "Resume only consumer background gates, rollback and reports"
    )
    assert (
        '--trusted-canary-completion-anchor-sha256 '
        '"$TRUSTED_CANARY_COMPLETION_ANCHOR_SHA256"'
        in resume["run"]
    )


def test_lane_b_bootstraps_only_the_restored_byte_equal_runner() -> None:
    jobs = _workflow_jobs()
    for job_id in ("fast-adoption", "canary", "background-certification"):
        assert jobs[job_id]["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    fast_script = _step(
        jobs["fast-adoption"], "Execute fast adoption and seal resumable runner handoff"
    )["run"]
    assert 'RUNNER="$HANDOFF_ROOT/public-kit/scripts/wiki_upgrade.py"' in fast_script
    assert 'cd "$HANDOFF_ROOT/public-kit"' in fast_script
    assert 'python "$RUNNER" plan' in fast_script
    assert 'python "$RUNNER" adopt' in fast_script

    canary_script = _step(
        jobs["canary"], "Resume the exact consumer through served Playwright canary"
    )["run"]
    background_script = _step(
        jobs["background-certification"],
        "Resume only consumer background gates, rollback and reports",
    )["run"]
    final_script = _step(
        jobs["background-certification"],
        "Verify final consumer receipt, rollback and reports",
    )["run"]
    for script in (canary_script, background_script):
        assert 'cd "$ROOT/public-kit"' in script
        assert '"$ROOT/public-kit/scripts/wiki_upgrade.py"' in script
        assert "python scripts/wiki_upgrade.py" not in script
        assert '"$GITHUB_WORKSPACE/scripts/wiki_upgrade.py"' not in script
    assert 'cd "$ROOT/consumer"' in final_script
    assert 'PYTHONPATH="$ROOT/public-kit"' in final_script
    assert '"$ROOT/public-kit/scripts/wiki_upgrade.py"' in final_script
    assert '"$GITHUB_WORKSPACE/scripts/wiki_upgrade.py"' not in final_script


def test_tampered_persisted_acceptance_anchor_cannot_replace_plan_stdout_anchor() -> None:
    original = "a" * 64
    tampered = "b" * 64
    stdout = "\n".join(
        [
            json.dumps({"schema_version": "wiki_viva_upgrade_progress.v1"}),
            json.dumps(
                {
                    "schema_version": "wiki_viva_upgrade_plan_summary.v1",
                    "acceptance_anchor_sha256": original,
                }
            ),
        ]
    )
    trusted_out_of_band = _acceptance_anchor_from_plan_stdout(stdout)
    coherently_tampered_handoff = {"acceptance_anchor_sha256": tampered}
    coherently_tampered_plan = {
        "acceptance_anchor": {"file_sha256": tampered}
    }

    assert (
        coherently_tampered_handoff["acceptance_anchor_sha256"]
        == coherently_tampered_plan["acceptance_anchor"]["file_sha256"]
    )
    assert coherently_tampered_handoff["acceptance_anchor_sha256"] != trusted_out_of_band


def test_execution_plan_is_verified_state_not_resume_authority() -> None:
    jobs = _workflow_jobs()
    resume_steps = (
        _step(jobs["canary"], "Resume the exact consumer through served Playwright canary"),
        _step(
            jobs["background-certification"],
            "Resume only consumer background gates, rollback and reports",
        ),
    )
    for step in resume_steps:
        script = step["run"]
        assert 'PLAN="$ROOT/consumer/.wiki-viva/upgrade/plan.json"' in script
        assert '--plan "$PLAN"' in script
        assert "execution-plan-*.json" not in script

    for job_id, restore_name in (
        ("canary", "Restore and verify exact paused state"),
        ("background-certification", "Restore and verify the same consumer run"),
    ):
        restore_script = _step(jobs[job_id], restore_name)["run"]
        assert "execution-plan-*.json" in restore_script
        assert "manifest['execution_plan_sha256']" in restore_script


def test_external_archive_anchor_rejects_coherent_content_and_manifest_rewrite(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original"
    original.mkdir()
    payload = b"certified paused consumer state\n"
    (original / "payload.txt").write_bytes(payload)
    (original / "handoff.json").write_text(
        json.dumps({"payload_sha256": hashlib.sha256(payload).hexdigest()}) + "\n",
        encoding="utf-8",
    )
    original_archive = tmp_path / "original.tgz"
    _write_archive(original, original_archive)
    external_anchor = hashlib.sha256(original_archive.read_bytes()).hexdigest()

    tampered = tmp_path / "tampered"
    tampered.mkdir()
    tampered_payload = b"attacker-rewritten paused consumer state\n"
    (tampered / "payload.txt").write_bytes(tampered_payload)
    (tampered / "handoff.json").write_text(
        json.dumps(
            {"payload_sha256": hashlib.sha256(tampered_payload).hexdigest()}
        )
        + "\n",
        encoding="utf-8",
    )
    tampered_archive = tmp_path / "tampered.tgz"
    _write_archive(tampered, tampered_archive)

    assert _internal_manifest_is_valid(tampered)
    assert hashlib.sha256(tampered_archive.read_bytes()).hexdigest() != external_anchor
