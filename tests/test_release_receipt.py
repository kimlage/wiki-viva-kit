from __future__ import annotations

import copy
import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
import wiki_core.release_receipt as release_module

from wiki_core.release_receipt import (
    CANONICAL_RELEASE_MATRIX_PATH,
    ReleaseReceiptError,
    _assert_publication_safe,
    _current_release_runtime,
    build_release_receipt,
    collect_git_subject,
    load_json_object,
    sha256_file,
    validate_release_receipt,
)
from scripts.wiki_release_receipt import main as receipt_main


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


def _run(root: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", checksum)
    )


def _png_bytes(width: int = 640, height: int = 360) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_visual_manifest(path: Path, *, public_synthetic: bool = True) -> None:
    root = next(parent for parent in path.parents if (parent / ".git").exists())
    image_relative = "data/derived/release/images/world-overview.png"
    image_path = root / image_relative
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_raw = _png_bytes()
    image_path.write_bytes(image_raw)
    _write(
        path,
        f"{json.dumps({
            'schema_version': 'wiki_visual_evidence_manifest.v1',
            'entries': [{
                'id': 'world-overview',
                'path': image_relative,
                'sha256': hashlib.sha256(image_raw).hexdigest(),
                'bytes': len(image_raw),
                'route': '/demo/w/radar',
                'browser': 'chromium',
                'viewport': {'width': 1280, 'height': 900},
                'capture_dimensions': {'width': 640, 'height': 360},
                'state': 'radar-overview',
                'public_synthetic': public_synthetic,
            }],
        }, sort_keys=True)}\n",
    )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "git", "init", "-b", "main")
    _run(root, "git", "config", "user.name", "Receipt Test")
    _run(root, "git", "config", "user.email", "receipt@example.invalid")
    _write(root / ".gitignore", "data/derived/\napps/wiki-cockpit/dist/\n")
    _write(root / "wiki.config.yaml", "repo_id: receipt-fixture\ncontexts: example\n")
    _write(root / "README.md", "# Fixture\n")
    adapter_relative = "adapters/local.py"
    adapter_raw = b"LOCAL_ADAPTER = 'v1'\n"
    (root / adapter_relative).parent.mkdir(parents=True, exist_ok=True)
    (root / adapter_relative).write_bytes(adapter_raw)
    adapter_files = [
        {
            "path": adapter_relative,
            "sha256": hashlib.sha256(adapter_raw).hexdigest(),
            "bytes": len(adapter_raw),
        }
    ]
    adapter_hash = hashlib.sha256(
        json.dumps(
            {
                "schema_version": "wiki_downstream_adapter_manifest.v1",
                "files": adapter_files,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    _write(
        root / "wiki.adapter-manifest.json",
        f"{json.dumps({
            'schema_version': 'wiki_downstream_adapter_manifest.v1',
            'files': adapter_files,
            'adapter_sha256': adapter_hash,
        }, sort_keys=True)}\n",
    )
    for relative in (
        "apps/wiki-cockpit/playwright.config.ts",
        "apps/wiki-cockpit/playwright.downstream.config.ts",
        "apps/wiki-cockpit/scripts/check-playwright-release.mjs",
        "apps/wiki-cockpit/scripts/release-matrix-lib.mjs",
        "apps/wiki-cockpit/scripts/release-matrix-contract.mjs",
        "apps/wiki-cockpit/scripts/release-build-manifest.mjs",
        "apps/wiki-cockpit/scripts/release-build-policy.mjs",
        "apps/wiki-cockpit/scripts/build-production.mjs",
        "apps/wiki-cockpit/scripts/build-production.sh",
        "apps/wiki-cockpit/scripts/release-server-policy.mjs",
        "apps/wiki-cockpit/scripts/capture-git-subject.mjs",
        "apps/wiki-cockpit/scripts/run-playwright-release.mjs",
        "apps/wiki-cockpit/scripts/run-playwright-release.sh",
        "apps/wiki-cockpit/scripts/preflight-downstream-e2e.mjs",
        "apps/wiki-cockpit/scripts/release-path-safety.mjs",
        "apps/wiki-cockpit/vite.config.ts",
        "scripts/wiki_git_subject.py",
        "scripts/_git_subject.py",
    ):
        _write(root / relative, f"fixture:{relative}\n")
    for relative in (
        "apps/wiki-cockpit/package.json",
        "apps/wiki-cockpit/package-lock.json",
        CANONICAL_RELEASE_MATRIX_PATH,
    ):
        _write(
            root / relative,
            (WORKSPACE_ROOT / relative).read_text(encoding="utf-8"),
        )
    _run(root, "git", "add", ".")
    _run(root, "git", "commit", "-m", "fixture")
    return root


def _gate(root: Path, *, scope: str, gate_id: str, **overrides: object) -> str:
    subject = collect_git_subject(root)
    run_id = f"fixture-{scope.replace('_', '-')}"
    run_root = f"data/derived/release/runs/{run_id}"
    relative = f"{run_root}/gate-result.json"
    expected_id = {
        "public_required": "playwright-public",
        "downstream_required": "playwright-downstream",
    }[scope]
    command_id = {
        "public_required": "playwright_public_release_v1",
        "downstream_required": "playwright_downstream_release_v1",
    }[scope]
    gate_id = expected_id if gate_id == "default" else gate_id
    payload = {
        "schema_version": "wiki_test_gate_result.v1",
        "id": gate_id,
        "scope": scope,
        "command_id": command_id,
        "run_id": run_id,
        "started_at": "2026-07-11T11:58:00Z",
        "finished_at": "2026-07-11T11:59:00Z",
        "status": "passed",
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "flaky": 0,
        "retries": 0,
        "subject_sha": subject["source_sha"],
        "tree_hash": subject["tree_hash"],
        "dirty": subject["dirty"],
        "dirty_entry_count": subject["dirty_entry_count"],
        "worktree_fingerprint_version": subject["worktree_fingerprint_version"],
        "worktree_fingerprint": subject["worktree_fingerprint"],
        "staged_patch_sha256": subject["staged_patch_sha256"],
        "unstaged_patch_sha256": subject["unstaged_patch_sha256"],
        "untracked_state_sha256": subject["untracked_state_sha256"],
        "untracked_entry_count": subject["untracked_entry_count"],
        "submodule_state_sha256": subject["submodule_state_sha256"],
    }
    contract = CANONICAL_RELEASE_MATRIX_PATH
    matrix = json.loads((root / contract).read_text(encoding="utf-8"))
    selected_matrix = matrix[scope]
    cells = selected_matrix["cells"]
    payload["passed"] = len(cells)
    payload["files"] = selected_matrix["required_specs"]
    payload["test_cells"] = [cell["id"] for cell in cells]
    raw_evidence = f"{run_root}/playwright-report.json"
    suites = []
    for cell in cells:
        title_parts = cell["title"].split(" › ", 1)
        suites.append(
            {
                "title": title_parts[0],
                "specs": [
                    {
                        "file": cell["file"],
                        "title": title_parts[1],
                        "tests": [
                            {
                                "projectName": cell["project"],
                                "status": "expected",
                                "expectedStatus": "passed",
                                "results": [{"status": "passed", "retry": 0}],
                            }
                        ],
                    }
                ],
            }
        )
    _write(
        root / raw_evidence,
        f"{json.dumps({
            'config': {
                'configFile': f'/repo/apps/wiki-cockpit/{selected_matrix["config_file"]}',
                'rootDir': f'/repo/apps/wiki-cockpit/{selected_matrix["test_dir"]}',
                'forbidOnly': True,
                'fullyParallel': False,
                'workers': 1,
                'version': matrix['playwright_version'],
                'projects': [
                    {'name': project, 'retries': 0, 'repeatEach': 1}
                    for project in selected_matrix['required_projects']
                ],
            },
            'suites': suites,
            'errors': [],
            'stats': {'expected': len(cells), 'unexpected': 0, 'skipped': 0, 'flaky': 0},
        }, sort_keys=True)}\n",
    )
    raw_hash, raw_size = sha256_file(root / raw_evidence)
    payload.update(
        {
            "evidence_path": raw_evidence,
            "evidence_sha256": raw_hash,
            "evidence_bytes": raw_size,
        }
    )
    contract_hash, contract_size = sha256_file(root / contract)
    payload["supporting_evidence"] = [
        {
            "id": "release-matrix-contract",
            "path": contract,
            "sha256": contract_hash,
            "bytes": contract_size,
        }
    ]
    build_manifest: str | None = None
    if scope == "public_required":
        dist_relative = "apps/wiki-cockpit/dist/index.html"
        dist_raw = b"<!doctype html><title>fixture release</title>\n"
        (root / dist_relative).parent.mkdir(parents=True, exist_ok=True)
        (root / dist_relative).write_bytes(dist_raw)
        files = [
            {
                "path": "dist/index.html",
                "sha256": hashlib.sha256(dist_raw).hexdigest(),
                "bytes": len(dist_raw),
            }
        ]
        aggregate = hashlib.sha256(
            json.dumps(files, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        build_manifest = f"{run_root}/release-build-manifest.json"
        _write(
            root / build_manifest,
            f"{json.dumps({
                'schema_version': 'wiki_release_build_manifest.v2',
                'scope': 'public_required',
                'subject_sha': subject['source_sha'],
                'dist_root': 'apps/wiki-cockpit/dist',
                'build_inputs': {
                    'schema_version': 'wiki_release_build_inputs.v1',
                    'command_id': 'wiki_cockpit_release_build.v1',
                    'vite_mode': 'production',
                    'node_env': 'production',
                    'vite_env_loading': 'disabled',
                    'runtime_config_path': 'public/wiki-cockpit.config.json',
                    'runtime_config_delivery': 'runtime_fetch_no_store.v1',
                    'environment_policy': {
                        'env_files': 'forbidden',
                        'parent_launcher': 'posix_env_i.v1',
                        'inherited_names': [],
                        'path_policy': 'node_binary_dir_plus_usr_bin_bin.v1',
                        'fixed_variables': {
                            'LANG': 'C',
                            'LC_ALL': 'C',
                            'TZ': 'UTC',
                            'SOURCE_DATE_EPOCH': '0',
                            'NODE_ENV': 'production',
                            'WIKI_COCKPIT_RELEASE_BUILD_INTERNAL': '1',
                        },
                        'forbidden_names': [
                            'BABEL_ENV',
                            'ESBUILD_BINARY_PATH',
                            'NODE_ENV',
                            'NODE_OPTIONS',
                            'NODE_PATH',
                            'WIKI_COCKPIT_PROXY_API',
                            'WIKI_COCKPIT_RELEASE_BUILD_INTERNAL',
                        ],
                        'forbidden_prefixes': ['VITE_'],
                    },
                },
                'builder_runtime': release_module._current_node_binary_identity(),
                'file_count': 1,
                'aggregate_sha256': aggregate,
                'files': files,
            }, sort_keys=True)}\n",
        )
        build_hash, build_size = sha256_file(root / build_manifest)
        payload["supporting_evidence"].append(
            {
                "id": "release-build-manifest",
                "path": build_manifest,
                "sha256": build_hash,
                "bytes": build_size,
            }
        )
    subject_before = f"{run_root}/git-subject-before.json"
    _write(root / subject_before, f"{json.dumps(subject, sort_keys=True)}\n")
    subject_hash, subject_size = sha256_file(root / subject_before)
    payload["supporting_evidence"].append(
        {
            "id": "git-subject-before",
            "path": subject_before,
            "sha256": subject_hash,
            "bytes": subject_size,
        }
    )
    toolchain = f"{run_root}/toolchain-manifest.json"
    toolchain_paths = {
        "playwright-config": (
            "apps/wiki-cockpit/playwright.config.ts"
            if scope == "public_required"
            else "apps/wiki-cockpit/playwright.downstream.config.ts"
        ),
        "release-matrix-checker": "apps/wiki-cockpit/scripts/check-playwright-release.mjs",
        "release-matrix-library": "apps/wiki-cockpit/scripts/release-matrix-lib.mjs",
        "release-matrix-generator": "apps/wiki-cockpit/scripts/release-matrix-contract.mjs",
        "release-matrix-contract": CANONICAL_RELEASE_MATRIX_PATH,
        "release-build-manifest": "apps/wiki-cockpit/scripts/release-build-manifest.mjs",
        "release-build-policy": "apps/wiki-cockpit/scripts/release-build-policy.mjs",
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
    toolchain_files = []
    for item_id, item_path in toolchain_paths.items():
        item_hash, item_size = sha256_file(root / item_path)
        toolchain_files.append(
            {
                "id": item_id,
                "path": item_path,
                "sha256": item_hash,
                "bytes": item_size,
            }
        )
    _write(
        root / toolchain,
        f"{json.dumps({
            'schema_version': 'wiki_playwright_toolchain_manifest.v1',
            'scope': scope,
            'runner_version': 'wiki_playwright_release_runner.v1',
            'runtime': _current_release_runtime(scope),
            'files': toolchain_files,
        }, sort_keys=True)}\n",
    )
    toolchain_hash, toolchain_size = sha256_file(root / toolchain)
    payload["supporting_evidence"].append(
        {
            "id": "release-toolchain-manifest",
            "path": toolchain,
            "sha256": toolchain_hash,
            "bytes": toolchain_size,
        }
    )
    if scope == "downstream_required":
        adapter_manifest = json.loads(
            (root / "wiki.adapter-manifest.json").read_text(encoding="utf-8")
        )
        preflight = f"{run_root}/downstream-preflight.json"
        _write(
            root / preflight,
            f"{json.dumps({
                'schema_version': 'wiki_downstream_preflight.v2',
                'scope': 'downstream_required',
                'status': 'passed',
                'repository': 'receipt-fixture',
                'snapshot_revision': 'receipt-fixture-aaaaaaaaaaaaaaaa',
                'snapshot_hash': 'a' * 64,
                'consumer_head': subject['source_sha'],
                'snapshot_source_commit': subject['source_sha'],
                'snapshot_source_sha': subject['source_sha'],
                'public_release_sha': subject['source_sha'],
                'adapter_hash': adapter_manifest['adapter_sha256'],
                'adapter_manifest': 'wiki.adapter-manifest.json',
                'adapter_manifest_schema_version': 'wiki_downstream_adapter_manifest.v1',
                'adapter_file_count': len(adapter_manifest['files']),
                'snapshot_version': 'wiki_web_snapshot.v2',
                'runtime_version': 'wiki_world_runtime.v8',
                'operator_server_version': 'wiki_web_server.v6',
                'temporal_graph_version': 'wiki_temporal_graph.v1',
                'temporal_event_version': 'wiki_temporal_event.v1',
                'temporal_event_count': 1,
                'experience_pack_composition_version': 'wiki_experience_pack_composition.v1',
                'composition_sha256': 'c' * 64,
                'active_packs': [],
                'contract_errors': [],
                'page_count': 1,
                'minimum_pages': 1,
                'capabilities': ['cors_default_deny_v1', 'operator_security_v2'],
                'snapshot_capabilities': ['experience_packs', 'temporal_graph'],
                'endpoint_origins': {
                    'snapshot': 'http://127.0.0.1:5173',
                    'ui': 'http://127.0.0.1:5173',
                },
            }, sort_keys=True)}\n",
        )
        digest, size = sha256_file(root / preflight)
        payload["supporting_evidence"].append(
            {
                "id": "downstream-preflight",
                "path": preflight,
                "sha256": digest,
                "bytes": size,
            }
        )
    run_result = f"{run_root}/run-result.json"
    payload["run_result_path"] = run_result
    payload.update(overrides)
    _write(root / relative, f"{json.dumps(payload, sort_keys=True)}\n")
    gate_hash, gate_size = sha256_file(root / relative)
    _write(
        root / run_result,
        f"{json.dumps({
            'schema_version': 'wiki_playwright_release_run.v1',
            'runner_version': 'wiki_playwright_release_runner.v1',
            'run_id': run_id,
            'scope': scope,
            'command_id': command_id,
            'status': 'passed',
            'failure_stage': None,
            'exit_code': 0,
            'started_at': '2026-07-11T11:58:00Z',
            'finished_at': '2026-07-11T12:00:00Z',
            'subject_before': subject,
            'subject_after': subject,
            'paths': {
                'report': raw_evidence,
                'preflight': preflight if scope == 'downstream_required' else None,
                'build_manifest': build_manifest,
                'gate_result': {
                    'path': relative,
                    'sha256': gate_hash,
                    'bytes': gate_size,
                },
            },
        }, sort_keys=True)}\n",
    )
    return relative


def _rewrite_gate_and_terminal(
    root: Path,
    relative: str,
    gate: dict[str, object],
    *,
    terminal_changes: dict[str, object] | None = None,
) -> None:
    _write(root / relative, f"{json.dumps(gate, sort_keys=True)}\n")
    gate_hash, gate_size = sha256_file(root / relative)
    terminal_path = root / str(gate["run_result_path"])
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal.update(terminal_changes or {})
    terminal["paths"]["gate_result"].update(
        {"sha256": gate_hash, "bytes": gate_size}
    )
    _write(terminal_path, f"{json.dumps(terminal, sort_keys=True)}\n")


def _evidence(
    root: Path,
    *,
    receipt_kind: str = "public_release",
    **changes: object,
) -> dict[str, object]:
    artifact = "data/derived/release/visual-evidence-manifest.json"
    _write_visual_manifest(root / artifact)
    payload: dict[str, object] = {
        "release_id": "v8-rc-test",
        "receipt_kind": receipt_kind,
        "artifacts": [
            {
                "id": "visual-evidence-manifest",
                "kind": "visual_evidence_manifest",
                "path": artifact,
            }
        ],
        "test_scopes": {
            (
                "public_required"
                if receipt_kind == "public_release"
                else "downstream_required"
            ): {
                "gate_results": [
                    _gate(
                        root,
                        scope=(
                            "public_required"
                            if receipt_kind == "public_release"
                            else "downstream_required"
                        ),
                        gate_id="default",
                    )
                ]
            }
        },
        "review": {"human_product_gate": "passed", "human_privacy_gate": "passed"},
        "waivers": [],
    }
    payload.update(changes)
    return payload


def test_publication_scan_masks_only_opaque_cryptographic_digests() -> None:
    luhn_digest = "4242424242424242" + ("a" * 48)
    luhn_subject_sha = "4242424242424242" + ("a" * 24)
    _assert_publication_safe(
        {
            "publication_boundary": "public_safe",
            "evidence_sha256": luhn_digest,
            "subject_sha": luhn_subject_sha,
        }
    )
    with pytest.raises(ReleaseReceiptError, match="credit_card"):
        _assert_publication_safe(
            {
                "publication_boundary": "public_safe",
                "release_id": luhn_digest,
            }
        )


def test_clean_complete_exact_subject_is_still_closure_only_without_external_e5_authority(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    head = _run(root, "git", "rev-parse", "HEAD")

    receipt = build_release_receipt(
        root,
        evidence,
        base_sha=head,
        promote_e5=True,
        created_at="2026-07-11T12:00:00Z",
    )

    assert receipt["schema_version"] == "wiki_release_receipt.v1"
    assert receipt["evidence_scope"] == "browser_closure"
    assert receipt["overall_status"] == "blocked"
    assert receipt["reason_codes"] == ["e5_external_authority_required"]
    assert receipt["subject"]["source_sha"] == head
    assert receipt["subject"]["tree_hash"] == _run(
        root, "git", "rev-parse", "HEAD^{tree}"
    )
    assert receipt["subject"]["dirty"] is False
    assert receipt["test_scopes"]["public_required"]["skipped"] == 0
    assert receipt["test_scopes"]["downstream_required"]["retries"] == 0
    assert len(receipt["artifacts"][0]["sha256"]) == 64
    assert validate_release_receipt(receipt, root=root) == []
    assert any(
        "external signed authority" in error
        for error in validate_release_receipt(receipt, root=root, require_e5=True)
    )


def test_clean_complete_evidence_only_receipt_is_a_passed_browser_closure(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(
        root,
        _evidence(root, receipt_kind="private_adoption"),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        created_at="2026-07-11T12:00:00Z",
    )
    assert receipt["evidence_scope"] == "browser_closure"
    assert receipt["overall_status"] == "passed"
    assert receipt["reason_codes"] == []
    assert receipt["promotion"] == {
        "requested": "evidence_only",
        "eligible": False,
        "status": "not_requested",
    }
    assert validate_release_receipt(receipt, root=root) == []


def test_hand_authored_pass_without_raw_evidence_cannot_even_form_a_closure_gate(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    gate_path = root / evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    for field in ("evidence_path", "evidence_sha256", "evidence_bytes"):
        gate.pop(field)
    _write(gate_path, f"{json.dumps(gate)}\n")

    with pytest.raises(ReleaseReceiptError, match="raw evidence is required"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
            promote_e5=True,
        )


def test_builder_rejects_invalid_created_at_before_writing_a_receipt(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    with pytest.raises(ReleaseReceiptError, match="created_at"):
        build_release_receipt(
            root,
            _evidence(root),
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
            promote_e5=True,
            created_at="2026-07-11T12:00:00",
        )


def test_dirty_worktree_is_recorded_and_blocks_e5_promotion(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    head = _run(root, "git", "rev-parse", "HEAD")
    _write(root / "README.md", "# Dirty fixture\n")

    receipt = build_release_receipt(root, evidence, base_sha=head, promote_e5=True)

    assert receipt["subject"]["dirty"] is True
    assert receipt["subject"]["dirty_entry_count"] == 1
    assert receipt["evidence_scope"] == "local_uncommitted_closure"
    assert receipt["overall_status"] == "blocked"
    assert "dirty_worktree" in receipt["reason_codes"]
    assert receipt["promotion"] == {
        "requested": "E5",
        "eligible": False,
        "status": "blocked",
    }


def test_dirty_closure_fingerprint_detects_same_count_different_content(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    _write(root / "README.md", "# Dirty A\n")
    evidence = _evidence(root)
    receipt = build_release_receipt(root, evidence)
    original_fingerprint = receipt["subject"]["worktree_fingerprint"]

    _write(root / "README.md", "# Dirty B with entirely different bytes\n")
    current = collect_git_subject(root)

    assert current["dirty_entry_count"] == receipt["subject"]["dirty_entry_count"]
    assert current["worktree_fingerprint"] != original_fingerprint
    errors = validate_release_receipt(receipt, root=root)
    assert any("worktree_fingerprint" in error for error in errors)


def test_fingerprint_separately_binds_staged_unstaged_and_untracked_bytes(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    clean = collect_git_subject(root)
    _write(root / "README.md", "# staged\n")
    _run(root, "git", "add", "README.md")
    staged = collect_git_subject(root)
    _write(root / "README.md", "# staged plus unstaged\n")
    unstaged = collect_git_subject(root)
    _write(root / "new-untracked.txt", "alpha\n")
    untracked_a = collect_git_subject(root)
    _write(root / "new-untracked.txt", "beta with same path\n")
    untracked_b = collect_git_subject(root)

    assert staged["staged_patch_sha256"] != clean["staged_patch_sha256"]
    assert unstaged["unstaged_patch_sha256"] != staged["unstaged_patch_sha256"]
    assert untracked_a["untracked_state_sha256"] != clean["untracked_state_sha256"]
    assert (
        untracked_b["untracked_state_sha256"] != untracked_a["untracked_state_sha256"]
    )
    assert (
        len(
            {
                clean["worktree_fingerprint"],
                staged["worktree_fingerprint"],
                unstaged["worktree_fingerprint"],
                untracked_a["worktree_fingerprint"],
                untracked_b["worktree_fingerprint"],
            }
        )
        == 5
    )


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_git_subject_rejects_index_flags_that_can_hide_dirty_bytes(
    tmp_path: Path, flag: str
) -> None:
    root = _repo(tmp_path)
    _run(root, "git", "update-index", flag, "README.md")
    _write(root / "README.md", "# Hidden dirty fixture\n")

    with pytest.raises(ReleaseReceiptError, match="index flags block"):
        collect_git_subject(root)


def test_clean_subject_without_exact_base_is_only_blocked_local_evidence(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(root, _evidence(root))

    assert receipt["subject"]["dirty"] is False
    assert receipt["evidence_scope"] == "local_evidence"
    assert receipt["overall_status"] == "blocked"
    assert "base_sha_missing" in receipt["reason_codes"]


def test_artifact_registry_rejects_unknown_or_omitted_kinds(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    for kind in (None, "invented_kind"):
        evidence = _evidence(root)
        artifact = dict(evidence["artifacts"][0])
        if kind is None:
            artifact.pop("kind")
        else:
            artifact["kind"] = kind
        evidence["artifacts"] = [artifact]
        with pytest.raises(ReleaseReceiptError, match="kind is not registered"):
            build_release_receipt(
                root,
                evidence,
                base_sha=_run(root, "git", "rev-parse", "HEAD"),
            )


def test_minimal_snapshot_manifest_cannot_claim_closed_release_artifact(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    fake = "data/derived/release/fabricated-snapshot.json"
    _write(
        root / fake,
        f"{json.dumps({
            'schema_version': 'wiki_web_snapshot.v2',
            'snapshot_id': 'fabricated',
            'bundle_hash': 'a' * 64,
            'contract_errors': [],
            'versions': {'snapshot': 'wiki_web_snapshot.v2'},
        })}\n",
    )
    evidence = _evidence(root)
    evidence["artifacts"] = [
        {"id": "fake-snapshot", "kind": "snapshot_manifest", "path": fake}
    ]

    with pytest.raises(ReleaseReceiptError, match="kind is not registered"):
        build_release_receipt(root, evidence)


def test_binary_artifact_is_refused_in_favor_of_textual_visual_manifest(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    binary = root / "data/derived/release/direct-screenshot.png"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00opaque")
    evidence = _evidence(root)
    evidence["artifacts"] = [
        {
            "id": "direct-screenshot",
            "kind": "visual_evidence_manifest",
            "path": binary.relative_to(root).as_posix(),
        }
    ]

    with pytest.raises(ReleaseReceiptError, match="textual evidence manifest"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


def test_public_artifact_blocks_pii_while_private_artifact_keeps_personal_context(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    note = "data/derived/release/private-note.md"
    _write(root / note, "# Evidence\n\nCPF: 529.982.247-25\n")
    public = _evidence(root)
    public["artifacts"] = [{"id": "release-note", "kind": "release_note", "path": note}]
    with pytest.raises(ReleaseReceiptError, match="PII-safe"):
        build_release_receipt(
            root,
            public,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )

    private = _evidence(root, receipt_kind="private_adoption")
    private["artifacts"] = [
        {"id": "release-note", "kind": "release_note", "path": note}
    ]
    receipt = build_release_receipt(
        root,
        private,
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
    )
    assert receipt["artifacts"][0]["safety_scan"] == "secret"


def test_artifact_secret_and_hardlink_are_blocked_for_every_boundary(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    secret_note = "data/derived/release/secret-note.md"
    _write(root / secret_note, "# Evidence\n\nAKIAIOSFODNN7EXAMPLE\n")
    private = _evidence(root, receipt_kind="private_adoption")
    private["artifacts"] = [
        {"id": "release-note", "kind": "release_note", "path": secret_note}
    ]
    with pytest.raises(ReleaseReceiptError, match="secret-safe"):
        build_release_receipt(
            root,
            private,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )

    referent = root / "data/derived/release/referent.md"
    alias = root / "data/derived/release/hardlink.md"
    _write(referent, "# Safe evidence\n")
    alias.hardlink_to(referent)
    public = _evidence(root)
    public["artifacts"] = [
        {
            "id": "release-note",
            "kind": "release_note",
            "path": alias.relative_to(root).as_posix(),
        }
    ]
    with pytest.raises(ReleaseReceiptError, match="must not be hard-linked"):
        build_release_receipt(
            root,
            public,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


def test_top_level_evidence_reader_rejects_hardlinks_before_parsing(
    tmp_path: Path,
) -> None:
    original = tmp_path / "evidence.json"
    alias = tmp_path / "evidence-alias.json"
    _write(original, '{"release_id":"fixture"}\n')
    alias.hardlink_to(original)

    with pytest.raises(ReleaseReceiptError, match="non-hard-linked"):
        load_json_object(alias, label="release evidence")


def test_release_evidence_operations_fail_closed_on_windows_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    monkeypatch.setattr(release_module.os, "name", "nt")

    with pytest.raises(ReleaseReceiptError, match="unsupported on Windows"):
        build_release_receipt(root, evidence)
    with pytest.raises(ReleaseReceiptError, match="unsupported on Windows"):
        load_json_object(root / "wiki.config.yaml", label="fixture")


def test_public_visual_manifest_requires_every_entry_to_be_public_synthetic(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    manifest = "data/derived/release/private-visual.json"
    _write_visual_manifest(root / manifest, public_synthetic=False)
    evidence = _evidence(root)
    evidence["artifacts"] = [
        {"id": "visual", "kind": "visual_evidence_manifest", "path": manifest}
    ]
    with pytest.raises(ReleaseReceiptError, match="not public-synthetic"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "mutated",
        "symlink",
        "hardlink",
        "metadata",
        "dimensions",
        "extension",
    ],
)
def test_visual_manifest_requires_real_closed_png_evidence(
    tmp_path: Path, tamper: str
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    manifest_path = root / evidence["artifacts"][0]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    image_path = root / entry["path"]
    if tamper == "missing":
        image_path.unlink()
    elif tamper == "mutated":
        mutated = bytearray(image_path.read_bytes())
        mutated[-1] ^= 0x01
        image_path.write_bytes(mutated)
    elif tamper == "symlink":
        external = tmp_path / "external.png"
        external.write_bytes(_png_bytes())
        image_path.unlink()
        image_path.symlink_to(external)
    elif tamper == "hardlink":
        referent = tmp_path / "referent.png"
        referent.write_bytes(_png_bytes())
        image_path.unlink()
        image_path.hardlink_to(referent)
    elif tamper == "metadata":
        raw = _png_bytes()
        with_metadata = raw[:33] + _png_chunk(b"tEXt", b"Author\x00Private") + raw[33:]
        image_path.write_bytes(with_metadata)
        entry.update(
            {
                "sha256": hashlib.sha256(with_metadata).hexdigest(),
                "bytes": len(with_metadata),
            }
        )
        _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")
    elif tamper == "dimensions":
        entry["capture_dimensions"]["width"] += 1
        _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")
    else:
        renamed = image_path.with_suffix(".jpg")
        image_path.rename(renamed)
        entry["path"] = renamed.relative_to(root).as_posix()
        _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")

    with pytest.raises(ReleaseReceiptError, match="visual evidence"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


@pytest.mark.parametrize(
    ("idat", "message"),
    [
        (b"not-a-zlib-stream", "image data is invalid"),
        (zlib.compress(b"\x00" * 10_000), "decompressed size/stream is invalid"),
    ],
)
def test_visual_png_requires_valid_bounded_exact_pixel_stream(
    tmp_path: Path,
    idat: bytes,
    message: str,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    manifest_path = root / evidence["artifacts"][0]["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"][0]
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )
    image = root / entry["path"]
    image.write_bytes(raw)
    entry.update(
        {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "capture_dimensions": {"width": 1, "height": 1},
        }
    )
    _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")

    with pytest.raises(ReleaseReceiptError, match=message):
        build_release_receipt(root, evidence)


@pytest.mark.parametrize("field", ["skipped", "flaky", "retries"])
def test_gate_counts_cannot_contradict_independently_parsed_raw_report(
    tmp_path: Path, field: str
) -> None:
    root = _repo(tmp_path)
    artifact = "data/derived/release/visual-evidence.json"
    _write_visual_manifest(root / artifact)
    bad_gate = _gate(root, scope="public_required", gate_id="default", **{field: 1})
    evidence = {
        "release_id": "v8-rc-test",
        "receipt_kind": "public_release",
        "artifacts": [
            {
                "id": "visual-evidence",
                "kind": "visual_evidence_manifest",
                "path": artifact,
            }
        ],
        "test_scopes": {
            "public_required": {"gate_results": [bad_gate]},
        },
        "review": {"human_product_gate": "passed", "human_privacy_gate": "passed"},
    }
    with pytest.raises(ReleaseReceiptError, match="independently parsed raw evidence"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
            promote_e5=True,
        )


def test_public_receipt_marks_downstream_separate_without_blocking_public_closure(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(
        root,
        test_scopes={
            "public_required": {
                "gate_results": [
                    _gate(root, scope="public_required", gate_id="default")
                ]
            }
        },
        review={"human_product_gate": "pending", "human_privacy_gate": "passed"},
    )
    receipt = build_release_receipt(
        root,
        evidence,
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    assert "downstream_required_missing" not in receipt["reason_codes"]
    assert "human_product_gate_pending" in receipt["reason_codes"]
    assert receipt["test_scopes"]["downstream_required"] == {
        "status": "not_applicable",
        "attestation": "separate_receipt_required",
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "flaky": 0,
        "retries": 0,
        "gates": [],
    }
    assert receipt["evidence_scope"] != "e5_release"


def test_downstream_scope_without_hashed_preflight_cannot_form_passing_gate(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    artifact = "data/derived/release/visual-evidence.json"
    _write_visual_manifest(root / artifact)
    downstream = _gate(root, scope="downstream_required", gate_id="default")
    downstream_path = root / downstream
    downstream_payload = json.loads(downstream_path.read_text(encoding="utf-8"))
    downstream_payload["supporting_evidence"] = [
        item
        for item in downstream_payload["supporting_evidence"]
        if item["id"] != "downstream-preflight"
    ]
    _write(downstream_path, f"{json.dumps(downstream_payload, sort_keys=True)}\n")
    refreshed_hash, refreshed_size = sha256_file(downstream_path)
    terminal_path = root / downstream_payload["run_result_path"]
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["paths"]["gate_result"].update(
        {"sha256": refreshed_hash, "bytes": refreshed_size}
    )
    _write(terminal_path, f"{json.dumps(terminal, sort_keys=True)}\n")
    with pytest.raises(ReleaseReceiptError, match="does not attest the passing gate"):
        build_release_receipt(
            root,
            {
                "release_id": "v8-rc-test",
                "receipt_kind": "private_adoption",
                "artifacts": [
                    {
                        "id": "visual-evidence",
                        "kind": "visual_evidence_manifest",
                        "path": artifact,
                    }
                ],
                "test_scopes": {
                    "downstream_required": {"gate_results": [downstream]},
                },
                "review": {
                    "human_product_gate": "passed",
                    "human_privacy_gate": "passed",
                },
            },
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
            promote_e5=True,
        )


def test_each_required_scope_without_release_matrix_contract_is_rejected(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    artifact = "data/derived/release/visual-evidence.json"
    _write_visual_manifest(root / artifact)
    public = _gate(
        root,
        scope="public_required",
        gate_id="default",
        supporting_evidence=[],
    )
    with pytest.raises(
        ReleaseReceiptError,
        match="release matrix cells are unavailable",
    ):
        build_release_receipt(
            root,
            {
                "release_id": "v8-rc-test",
                "receipt_kind": "public_release",
                "artifacts": [
                    {
                        "id": "visual-evidence",
                        "kind": "visual_evidence_manifest",
                        "path": artifact,
                    }
                ],
                "test_scopes": {
                    "public_required": {"gate_results": [public]},
                },
                "review": {
                    "human_product_gate": "passed",
                    "human_privacy_gate": "passed",
                },
            },
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
            promote_e5=True,
        )


def test_reserved_supporting_evidence_id_requires_its_real_schema(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    wrong_contract = "data/derived/release/wrong-contract.json"
    _write(root / wrong_contract, '{"schema_version":"invented"}\n')
    digest, size = sha256_file(root / wrong_contract)
    public = _gate(
        root,
        scope="public_required",
        gate_id="default",
        supporting_evidence=[
            {
                "id": "release-matrix-contract",
                "path": wrong_contract,
                "sha256": digest,
                "bytes": size,
            }
        ],
    )
    evidence["test_scopes"]["public_required"] = {"gate_results": [public]}
    with pytest.raises(ReleaseReceiptError, match="canonical repository path"):
        build_release_receipt(root, evidence)


def test_valid_one_cell_contract_at_arbitrary_path_is_not_canonical(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    relative = evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    support = next(
        item
        for item in gate["supporting_evidence"]
        if item["id"] == "release-matrix-contract"
    )
    fabricated = "data/derived/release/fabricated-one-cell-contract.json"
    contract = json.loads((root / CANONICAL_RELEASE_MATRIX_PATH).read_text())
    for scope in ("public_required", "downstream_required"):
        record = contract[scope]
        record["cells"] = record["cells"][:1]
        record["expected_tests"] = 1
        record["required_specs"] = [record["cells"][0]["file"]]
        record["required_projects"] = [record["cells"][0]["project"]]
    _write(root / fabricated, f"{json.dumps(contract, sort_keys=True)}\n")
    digest, size = sha256_file(root / fabricated)
    support.update({"path": fabricated, "sha256": digest, "bytes": size})
    _rewrite_gate_and_terminal(root, relative, gate)

    with pytest.raises(ReleaseReceiptError, match="canonical repository path"):
        build_release_receipt(root, evidence)


@pytest.mark.parametrize("location", ["raw_report", "support"])
@pytest.mark.parametrize(
    ("receipt_kind", "pii", "blocked"),
    [
        ("public_release", "operator@example.com", True),
        ("public_release", "529.982.247-25", True),
        ("private_adoption", "operator@example.com", False),
        ("private_adoption", "529.982.247-25", False),
    ],
)
def test_gate_bound_evidence_uses_scope_aware_pii_policy(
    tmp_path: Path,
    location: str,
    receipt_kind: str,
    pii: str,
    blocked: bool,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root, receipt_kind=receipt_kind)
    scope = (
        "public_required" if receipt_kind == "public_release" else "downstream_required"
    )
    relative = evidence["test_scopes"][scope]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    if location == "raw_report":
        evidence_path = root / gate["evidence_path"]
        raw_report = json.loads(evidence_path.read_text(encoding="utf-8"))
        raw_report["operator_context"] = pii
        _write(evidence_path, f"{json.dumps(raw_report, sort_keys=True)}\n")
        digest, size = sha256_file(evidence_path)
        gate.update({"evidence_sha256": digest, "evidence_bytes": size})
    else:
        support = next(
            item
            for item in gate["supporting_evidence"]
            if item["id"] == "git-subject-before"
        )
        support_path = root / support["path"]
        support_payload = json.loads(support_path.read_text(encoding="utf-8"))
        support_payload["operator_context"] = pii
        _write(support_path, f"{json.dumps(support_payload, sort_keys=True)}\n")
        digest, size = sha256_file(support_path)
        support.update({"sha256": digest, "bytes": size})
    _rewrite_gate_and_terminal(root, relative, gate)

    if blocked:
        with pytest.raises(ReleaseReceiptError, match="PII"):
            build_release_receipt(root, evidence)
    else:
        receipt = build_release_receipt(root, evidence)
        assert receipt["publication_boundary"] == "private_internal"


def test_receipt_validation_detects_tampered_artifact_hash_and_green_claim(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(
        root,
        _evidence(root),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    receipt["artifacts"][0]["sha256"] = "0" * 64
    receipt["subject"]["dirty"] = True
    receipt["reason_codes"] = []
    receipt["overall_status"] = "passed"

    errors = validate_release_receipt(receipt, root=root, require_e5=True)
    assert any("reason_codes" in error for error in errors)
    assert any("artifact" in error and "hash/size" in error for error in errors)
    assert any("subject.dirty" in error for error in errors)


def test_receipt_validation_reloads_normalized_gate_instead_of_trusting_copied_counts(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(
        root,
        _evidence(root),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    gate = receipt["test_scopes"]["public_required"]["gates"][0]
    gate["passed"] = 2
    receipt["test_scopes"]["public_required"]["passed"] = 2

    errors = validate_release_receipt(receipt, root=root)
    assert any("does not match its normalized result file" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda receipt: receipt.update({"release_id": "bad id"}), "release_id"),
        (
            lambda receipt: receipt.update({"created_at": "2026-07-11T12:00:00"}),
            "created_at",
        ),
        (
            lambda receipt: receipt.update({"evidence_scope": "invented"}),
            "evidence_scope",
        ),
        (lambda receipt: receipt.update({"unexpected": True}), "receipt fields"),
        (
            lambda receipt: receipt["subject"].update({"repository": ""}),
            "subject.repository",
        ),
        (
            lambda receipt: receipt.update({"reason_codes": ["NOT_SAFE"]}),
            "reason_codes",
        ),
        (
            lambda receipt: receipt["test_scopes"]["public_required"]["gates"][
                0
            ].update({"unexpected": True}),
            "gate 0 fields",
        ),
    ],
)
def test_runtime_validator_enforces_critical_schema_invariants_without_jsonschema(
    tmp_path: Path, mutation: object, message: str
) -> None:
    root = _repo(tmp_path)
    original = build_release_receipt(
        root,
        _evidence(root),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    receipt = copy.deepcopy(original)
    mutation(receipt)
    errors = validate_release_receipt(receipt, root=root)
    assert any(message in error for error in errors)


def test_downstream_preflight_is_hashed_into_gate_and_rechecked_by_receipt(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(
        root,
        _evidence(root, receipt_kind="private_adoption"),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    gate = receipt["test_scopes"]["downstream_required"]["gates"][0]
    support_by_id = {item["id"]: item for item in gate["supporting_evidence"]}
    assert "release-matrix-contract" in support_by_id
    support = support_by_id["downstream-preflight"]
    assert support["id"] == "downstream-preflight"
    assert len(support["sha256"]) == 64

    _write(root / support["path"], '{"status":"tampered"}\n')
    errors = validate_release_receipt(receipt, root=root)
    assert any(
        "supporting evidence downstream-preflight hash/size" in error
        for error in errors
    )


def test_downstream_receipt_reopens_the_tracked_adapter_files(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(
        root,
        _evidence(root, receipt_kind="private_adoption"),
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        promote_e5=True,
    )
    (root / "adapters/local.py").write_text("LOCAL_ADAPTER = 'tampered'\n", encoding="utf-8")
    errors = validate_release_receipt(receipt, root=root)
    assert any("adapter manifest" in error for error in errors)


def test_coherently_tampered_downstream_source_identity_cannot_cross_gate_subject(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root, receipt_kind="private_adoption")
    gate_path = root / evidence["test_scopes"]["downstream_required"][
        "gate_results"
    ][0]
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    preflight_record = next(
        item
        for item in gate["supporting_evidence"]
        if item["id"] == "downstream-preflight"
    )
    preflight_path = root / preflight_record["path"]
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    foreign_subject = "f" * 40
    preflight.update(
        {
            "consumer_head": foreign_subject,
            "snapshot_source_commit": foreign_subject,
            "snapshot_source_sha": foreign_subject,
        }
    )
    _write(preflight_path, f"{json.dumps(preflight, sort_keys=True)}\n")
    preflight_hash, preflight_size = sha256_file(preflight_path)
    preflight_record.update({"sha256": preflight_hash, "bytes": preflight_size})
    _write(gate_path, f"{json.dumps(gate, sort_keys=True)}\n")
    gate_hash, gate_size = sha256_file(gate_path)
    terminal_path = root / gate["run_result_path"]
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["paths"]["gate_result"].update(
        {"sha256": gate_hash, "bytes": gate_size}
    )
    _write(terminal_path, f"{json.dumps(terminal, sort_keys=True)}\n")

    with pytest.raises(ReleaseReceiptError, match="does not match the gate subject"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


def test_passed_gate_is_unusable_without_matching_terminal_run_result(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    gate_path = Path(evidence["test_scopes"]["public_required"]["gate_results"][0])
    gate = json.loads((root / gate_path).read_text(encoding="utf-8"))
    run_path = root / gate["run_result_path"]
    terminal = json.loads(run_path.read_text(encoding="utf-8"))
    terminal.update(
        {
            "status": "blocked",
            "failure_stage": "subject_after",
            "exit_code": 1,
        }
    )
    _write(run_path, f"{json.dumps(terminal, sort_keys=True)}\n")

    with pytest.raises(ReleaseReceiptError, match="does not attest the passing gate"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


def test_downstream_terminal_run_cannot_contradict_hashed_preflight_path(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root, receipt_kind="private_adoption")
    gate_path = Path(evidence["test_scopes"]["downstream_required"]["gate_results"][0])
    gate = json.loads((root / gate_path).read_text(encoding="utf-8"))
    run_path = root / gate["run_result_path"]
    terminal = json.loads(run_path.read_text(encoding="utf-8"))
    terminal["paths"]["preflight"] = gate["evidence_path"]
    _write(run_path, f"{json.dumps(terminal, sort_keys=True)}\n")

    with pytest.raises(ReleaseReceiptError, match="does not attest the passing gate"):
        build_release_receipt(
            root,
            evidence,
            base_sha=_run(root, "git", "rev-parse", "HEAD"),
        )


def test_toolchain_manifest_rehashes_every_executed_config_and_checker(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(root, _evidence(root))
    _write(
        root / "apps/wiki-cockpit/scripts/release-matrix-lib.mjs",
        "fixture:changed-after-gate\n",
    )

    errors = validate_release_receipt(receipt, root=root)
    assert any(
        "toolchain file release-matrix-library hash/size is stale" in error
        for error in errors
    )


def test_coherently_tampered_toolchain_runtime_cannot_self_attest(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    relative = evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    support = next(
        item
        for item in gate["supporting_evidence"]
        if item["id"] == "release-toolchain-manifest"
    )
    manifest_path = root / support["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_runtime = _current_release_runtime("public_required")
    manifest["runtime"] = {
        "platform": current_runtime["platform"],
        "arch": current_runtime["arch"],
        "node_version": "99.99.99",
        "playwright_version": "99.99.99",
        "python_version": "99.99.99",
        "browser_engines": [
            {"name": name, "version": "99.99.99"}
            for name in ("chromium", "firefox", "webkit")
        ],
    }
    _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")
    digest, size = sha256_file(manifest_path)
    support.update({"sha256": digest, "bytes": size})
    _rewrite_gate_and_terminal(root, relative, gate)

    with pytest.raises(ReleaseReceiptError, match="runtime does not match"):
        build_release_receipt(root, evidence)


def test_stale_coherent_gate_replay_blocks_browser_closure(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    relative = evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    gate.update(
        {
            "started_at": "2000-01-01T00:00:00Z",
            "finished_at": "2000-01-01T00:01:00Z",
        }
    )
    _rewrite_gate_and_terminal(
        root,
        relative,
        gate,
        terminal_changes={
            "started_at": "2000-01-01T00:00:00Z",
            "finished_at": "2000-01-01T00:02:00Z",
        },
    )

    receipt = build_release_receipt(
        root,
        evidence,
        base_sha=_run(root, "git", "rev-parse", "HEAD"),
        created_at="2026-07-11T12:00:00Z",
    )

    assert receipt["overall_status"] == "blocked"
    assert "public_required_gate_evidence_stale" in receipt["reason_codes"]
    assert validate_release_receipt(receipt, root=root) == []


def test_release_build_manifest_reopens_exact_ignored_dist_inventory(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(root, _evidence(root))
    dist_file = root / "apps/wiki-cockpit/dist/index.html"
    dist_file.write_text("mutated ignored dist\n", encoding="utf-8")

    errors = validate_release_receipt(receipt, root=root)

    assert any("release build manifest file" in error for error in errors)


def test_release_build_manifest_rejects_tampered_effective_inputs(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    relative = evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    support = next(
        item
        for item in gate["supporting_evidence"]
        if item["id"] == "release-build-manifest"
    )
    manifest_path = root / support["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["build_inputs"]["node_env"] = "development"
    _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")
    support_hash, support_size = sha256_file(manifest_path)
    support.update({"sha256": support_hash, "bytes": support_size})
    _rewrite_gate_and_terminal(root, relative, gate)

    with pytest.raises(ReleaseReceiptError, match="manifest inputs are invalid"):
        build_release_receipt(root, evidence)


def test_release_build_manifest_rejects_tampered_node_executable_identity(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    relative = evidence["test_scopes"]["public_required"]["gate_results"][0]
    gate = json.loads((root / relative).read_text(encoding="utf-8"))
    support = next(
        item
        for item in gate["supporting_evidence"]
        if item["id"] == "release-build-manifest"
    )
    manifest_path = root / support["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["builder_runtime"]["node_executable_sha256"] = "0" * 64
    _write(manifest_path, f"{json.dumps(manifest, sort_keys=True)}\n")
    support_hash, support_size = sha256_file(manifest_path)
    support.update({"sha256": support_hash, "bytes": support_size})
    _rewrite_gate_and_terminal(root, relative, gate)

    with pytest.raises(ReleaseReceiptError, match="Node runtime is invalid"):
        build_release_receipt(root, evidence)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        " gate.json",
        "gate.json ",
        "\x00gate.json",
        "./data/derived/gate.json",
        "data/./gate.json",
        "data/../gate.json",
        "data//gate.json",
        "data/derived/gate.json/",
        "/data/derived/gate.json",
        "~/gate.json",
        "C:/data/derived/gate.json",
        "C:\\data\\derived\\gate.json",
        "data\\derived\\gate.json",
        "data/derived/.ENV.local",
        "data/derived/CREDENTIALS.json",
    ],
)
def test_gate_result_paths_use_portable_case_insensitive_fail_closed_policy(
    tmp_path: Path, unsafe_path: str
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    evidence["test_scopes"] = {
        "public_required": {"gate_results": [unsafe_path]},
        "downstream_required": {"gate_results": []},
    }
    with pytest.raises(ReleaseReceiptError, match="path"):
        build_release_receipt(root, evidence)


def test_gate_result_must_bind_the_exact_subject(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)

    bad = _gate(root, scope="public_required", gate_id="default", subject_sha="0" * 40)
    evidence["test_scopes"] = {
        "public_required": {"gate_results": [bad]},
        "downstream_required": {"gate_results": []},
    }
    with pytest.raises(
        ReleaseReceiptError,
        match="release build manifest identity|pre-run Git subject contradicts",
    ):
        build_release_receipt(root, evidence)


def test_gate_rejects_free_command_text_and_sensitive_file_metadata(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    command_gate = _gate(
        root,
        scope="public_required",
        gate_id="default",
        command="npm run unallowlisted-extra-command",
    )
    evidence["test_scopes"]["public_required"] = {"gate_results": [command_gate]}
    with pytest.raises(ReleaseReceiptError, match="command_id"):
        build_release_receipt(root, evidence)

    evidence = _evidence(root)
    sensitive_gate = _gate(
        root,
        scope="public_required",
        gate_id="default",
        files=["e2e/.env.private.spec.ts"],
    )
    evidence["test_scopes"]["public_required"] = {"gate_results": [sensitive_gate]}
    with pytest.raises(ReleaseReceiptError, match="in-scope spec path"):
        build_release_receipt(root, evidence)


def test_release_evidence_manifest_rejects_access_secrets_even_in_unused_fields(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence = _evidence(root)
    evidence["unused_note"] = "AKIAIOSFODNN7EXAMPLE"
    with pytest.raises(ReleaseReceiptError, match="access-secret"):
        build_release_receipt(root, evidence)


def test_json_schema_rejects_the_old_contradictory_green_e5_shape(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt = build_release_receipt(root, _evidence(root))
    contradictory = copy.deepcopy(receipt)
    contradictory["subject"]["dirty"] = True
    contradictory["subject"]["dirty_entry_count"] = 99
    contradictory["reason_codes"] = []
    contradictory["overall_status"] = "passed"
    contradictory["evidence_scope"] = "e5_release"
    contradictory["promotion"] = {
        "requested": "E5",
        "eligible": True,
        "status": "promoted",
    }
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "docs/references/schemas/wiki-release-receipt-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(receipt)) == []
    errors = list(validator.iter_errors(contradictory))
    assert errors
    messages = "\n".join(error.message for error in errors)
    assert "e5_release" in messages or "false" in messages or "promoted" in messages


def test_receipt_output_must_be_gitignored_to_preserve_its_subject(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence_path = root / "data/derived/release/evidence.json"
    _write(evidence_path, f"{json.dumps(_evidence(root))}\n")
    result = receipt_main(
        [
            "--root",
            str(root),
            "--evidence",
            str(evidence_path),
            "--out",
            "release-receipt.json",
        ]
    )
    assert result == 1
    assert not (root / "release-receipt.json").exists()


def test_receipt_output_never_replaces_a_tracked_file_even_below_ignored_root(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt_path = root / "data/derived/wiki/release-receipt.json"
    sentinel = b"tracked sentinel\n"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(sentinel)
    _run(root, "git", "add", "-f", receipt_path.relative_to(root).as_posix())
    _run(root, "git", "commit", "-m", "tracked ignored sentinel")
    evidence_path = root / "data/derived/release/evidence.json"
    _write(evidence_path, f"{json.dumps(_evidence(root))}\n")

    result = receipt_main(
        [
            "--root",
            str(root),
            "--evidence",
            str(evidence_path),
            "--out",
            str(receipt_path),
        ]
    )

    assert result == 1
    assert receipt_path.read_bytes() == sentinel


def test_receipt_output_never_replaces_existing_untracked_evidence(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    receipt_path = root / "data/derived/wiki/release-existing.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel = b"immutable untracked receipt\n"
    receipt_path.write_bytes(sentinel)
    evidence_path = root / "data/derived/release/evidence.json"
    _write(evidence_path, f"{json.dumps(_evidence(root))}\n")

    result = receipt_main(
        [
            "--root",
            str(root),
            "--evidence",
            str(evidence_path),
            "--out",
            str(receipt_path),
        ]
    )

    assert result == 1
    assert receipt_path.read_bytes() == sentinel


@pytest.mark.parametrize("attack", ["parent_symlink", "target_symlink"])
def test_receipt_output_rejects_symlink_paths_without_touching_external_referent(
    tmp_path: Path,
    attack: str,
) -> None:
    root = _repo(tmp_path)
    evidence_path = root / "data/derived/release/evidence.json"
    _write(evidence_path, f"{json.dumps(_evidence(root))}\n")
    external = tmp_path / "external-receipt-target"
    external.mkdir()
    referent = external / "sentinel.json"
    sentinel = b"external bytes stay immutable\n"
    referent.write_bytes(sentinel)
    output = root / "data/derived/wiki/release.json"
    if attack == "parent_symlink":
        output.parent.symlink_to(external, target_is_directory=True)
    else:
        output.parent.mkdir(parents=True)
        output.symlink_to(referent)

    result = receipt_main(
        [
            "--root",
            str(root),
            "--evidence",
            str(evidence_path),
            "--out",
            str(output),
        ]
    )

    assert result == 1
    assert referent.read_bytes() == sentinel


def test_cli_writes_blocked_closure_and_returns_two_for_dirty_e5_request(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    evidence_path = root / "data/derived/release/evidence.json"
    receipt_path = root / "data/derived/release/receipt.json"
    _write(evidence_path, f"{json.dumps(_evidence(root))}\n")
    _write(root / "README.md", "# Dirty CLI fixture\n")
    head = _run(root, "git", "rev-parse", "HEAD")

    result = receipt_main(
        [
            "--root",
            str(root),
            "--evidence",
            str(evidence_path),
            "--out",
            str(receipt_path),
            "--base-sha",
            head,
            "--promote-e5",
        ]
    )

    assert result == 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["evidence_scope"] == "local_uncommitted_closure"
    assert receipt["overall_status"] == "blocked"
    assert "dirty_worktree" in receipt["reason_codes"]
    assert (
        receipt_main(
            [
                "--root",
                str(root),
                "--receipt",
                str(receipt_path),
                "--check",
                "--require-e5",
            ]
        )
        == 1
    )
