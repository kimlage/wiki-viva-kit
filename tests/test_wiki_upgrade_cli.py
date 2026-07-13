from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
import yaml
import scripts.wiki_upgrade as upgrade_runner

from wiki_core.upgrade_lanes import (
    NEVER_REUSABLE_GATES,
    ReleaseCapsuleAuthority,
    canonical_sha256,
    collect_release_attestation,
    seal_impact_registry,
    seal_release_capsule,
)
from wiki_core.upgrade import boundary_operations_sha256
from wiki_core.web.commands import is_allowed_argv


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/wiki_upgrade.py"


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    _git(root, "config", "user.name", "Synthetic Fixture")


def _commit_all(root: Path, subject: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", subject)
    return _git(root, "rev-parse", "HEAD")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def _png_bytes(width: int = 16, height: int = 12) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, 9))
        + _png_chunk(b"IEND", b"")
    )


def _seal_authority_capsule(
    *,
    package: dict,
    registry: dict,
    payload: dict,
    source_root: Path,
    visual_root: Path,
    gate_output_root: Path,
) -> tuple[dict, str]:
    probe_ref = str(payload.get("toolchain_probe_ref") or "toolchain-probe.json")
    payload["toolchain_probe_ref"] = probe_ref
    probe_entries = []
    for tool_id in ("browser", "node", "python", "runner"):
        identity = payload["toolchain"][tool_id]
        output_ref = f"outputs/toolchain-{tool_id}.log"
        output_path = gate_output_root / output_ref
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output = f"{identity['name']} {identity['version']}\n".encode("utf-8")
        output_path.write_bytes(output)
        probe_entries.append(
            {
                "id": tool_id,
                "name": identity["name"],
                "version": identity["version"],
                "provenance": "executed",
                "probe_argv": [identity["name"], "--version"],
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "output_bytes": len(output),
            }
        )
    (gate_output_root / probe_ref).write_text(
        json.dumps(
            {
                "schema_version": "wiki_viva_toolchain_probe.v1",
                "run_id": payload["run_id"],
                "entries": probe_entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    attestation = collect_release_attestation(
        payload,
        package=package,
        impact_registry=registry,
        source_root=source_root,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
    )
    attestation_path = gate_output_root / payload["attestation_ref"]
    attestation_path.write_text(
        json.dumps(attestation, sort_keys=True) + "\n", encoding="utf-8"
    )
    trusted = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    authority = ReleaseCapsuleAuthority(
        package=package,
        impact_registry=registry,
        source_root=source_root,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
        verified_attestation_sha256=trusted,
    )
    return seal_release_capsule(payload, authority=authority), trusted


def _reseal_package(fixture: dict[str, Path | str], package: dict) -> None:
    Path(fixture["package"]).write_text(
        yaml.safe_dump(package, sort_keys=False), encoding="utf-8"
    )
    capsule = json.loads(Path(fixture["capsule"]).read_text(encoding="utf-8"))
    capsule.pop("schema_version", None)
    capsule.pop("capsule_sha256", None)
    capsule, trusted = _seal_authority_capsule(
        package=package,
        registry=yaml.safe_load(Path(fixture["registry"]).read_text(encoding="utf-8")),
        payload=capsule,
        source_root=Path(fixture["kit"]),
        visual_root=Path(fixture["visual_root"]),
        gate_output_root=Path(fixture["gate_output_root"]),
    )
    Path(fixture["capsule"]).write_text(json.dumps(capsule, indent=2), encoding="utf-8")
    fixture["trusted_attestation_sha256"] = trusted


def _run(
    fixture: dict[str, Path | str],
    *arguments: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("WIKI_UPGRADE_RUN_DIR", None)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=cwd or ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )


def _plan_args(fixture: dict[str, Path | str]) -> list[str]:
    return [
        "plan",
        "--package",
        str(fixture["package"]),
        "--capsule",
        str(fixture["capsule"]),
        "--impact-registry",
        str(fixture["registry"]),
        "--authority",
        str(fixture["authority"]),
        "--trusted-attestation-sha256",
        str(fixture["trusted_attestation_sha256"]),
        "--consumer-root",
        str(fixture["consumer"]),
        "--kit-root",
        str(fixture["kit"]),
        "--c3-adapter-command",
        (
            "adapt_config::python3 -c \"from pathlib import Path; "
            "Path('wiki.config.yaml').write_text('repo_id: synthetic-consumer-v8\\n', "
            "encoding='utf-8')\""
        ),
    ]


def _adopt_args(
    fixture: dict[str, Path | str],
    *,
    resume: bool = False,
    pause_before_canary: bool = False,
    pause_before_background: bool = False,
) -> list[str]:
    values = [
        "adopt",
        "--plan",
        str(fixture["plan"]),
        "--package",
        str(fixture["package"]),
        "--capsule",
        str(fixture["capsule"]),
        "--impact-registry",
        str(fixture["registry"]),
        "--authority",
        str(fixture["authority"]),
        "--trusted-attestation-sha256",
        str(fixture["trusted_attestation_sha256"]),
        "--consumer-root",
        str(fixture["consumer"]),
        "--kit-root",
        str(fixture["kit"]),
        "--mode",
        "canary",
        "--jobs",
        "4",
        "--heartbeat-seconds",
        "0.1",
    ]
    if resume:
        values.append("--resume")
    if pause_before_canary:
        values.append("--pause-before-canary")
    if pause_before_background:
        values.append("--pause-before-background")
    return values


def _certify_args(
    fixture: dict[str, Path | str], output: Path
) -> list[str]:
    return [
        "certify",
        "--package",
        str(fixture["package"]),
        "--impact-registry",
        str(fixture["registry"]),
        "--source-root",
        str(fixture["kit"]),
        "--visual-root",
        str(fixture["visual_root"]),
        "--visual-manifest-ref",
        "visual-manifest.json",
        "--out-dir",
        str(output),
        "--attestation-authority-id",
        "synthetic-ci",
        "--jobs",
        "4",
        "--heartbeat-seconds",
        "0.1",
    ]


@pytest.fixture
def synthetic_upgrade(tmp_path: Path) -> dict[str, Path | str]:
    kit = tmp_path / "public-kit"
    _init_repo(kit)
    (kit / "portable.txt").write_text("synthetic portable subject\n", encoding="utf-8")
    (kit / "wiki_core").mkdir()
    (kit / "wiki_core/portable.py").write_text("PORTABLE = True\n", encoding="utf-8")
    (kit / "wiki_core/synthetic_canary.py").write_text(
        "import json, os, threading\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "from pathlib import Path\n"
        "from playwright.sync_api import sync_playwright\n"
        "p=Path(os.environ['WIKI_UPGRADE_GATE_ARTIFACT_DIR'])\n"
        "p.mkdir(parents=True,exist_ok=True)\n"
        "html=b'''<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        "body{margin:0;background:#07111f;color:#dff7ff;font:14px system-ui}"
        "main{padding:20px}h1{font-size:22px}.timeline{border-left:2px solid #5eead4;"
        "padding-left:12px}</style></head><body><main><h1>Synthetic Living World</h1>"
        "<p>Public reversible canary</p><section class=\"timeline\" aria-label=\"Timeline\">"
        "<strong>Timeline</strong><p>C1 import - C2 regeneration - C3 adapter</p>"
        "</section></main></body></html>'''\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')\n"
        "  self.send_header('Content-Length',str(len(html))); self.end_headers(); self.wfile.write(html)\n"
        " def log_message(self,*args): pass\n"
        "server=ThreadingHTTPServer(('127.0.0.1',0),Handler)\n"
        "thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()\n"
        "requests=[]; request_errors=[]; console_errors=[]; console_warnings=[]\n"
        "try:\n"
        " with sync_playwright() as runtime:\n"
        "  browser=runtime.chromium.launch(headless=True)\n"
        "  page=browser.new_page(viewport={'width':320,'height':240})\n"
        "  page.on('request',lambda request: requests.append(request.method))\n"
        "  page.on('requestfailed',lambda request: request_errors.append(request.method))\n"
        "  page.on('console',lambda message: (console_errors if message.type=='error' else console_warnings if message.type=='warning' else []).append(message.text))\n"
        "  route='/demo/w/radar'; response=page.goto(f'http://127.0.0.1:{server.server_port}{route}',wait_until='networkidle')\n"
        "  if response is None or not response.ok: raise RuntimeError('served canary navigation failed')\n"
        "  page.get_by_role('heading',name='Synthetic Living World').wait_for()\n"
        "  page.get_by_label('Timeline').wait_for()\n"
        "  page.screenshot(path=str(p/'desktop.png'))\n"
        "  browser.close()\n"
        "finally:\n"
        " server.shutdown(); server.server_close(); thread.join(timeout=5)\n"
        "(p/'network-summary.json').write_text(json.dumps({"
        "'schema_version':'wiki_viva_network_capture_summary.v1',"
        "'capture_method':'playwright_served_public_synthetic',"
        "'request_count':len(requests),'error_count':len(request_errors),"
        "'payloads_redacted':True}))\n"
        "(p/'browser-console-summary.json').write_text(json.dumps({"
        "'schema_version':'wiki_viva_browser_console_summary.v1',"
        "'error_count':len(console_errors),'warning_count':len(console_warnings),"
        "'payloads_redacted':True}))\n"
        "(p/'visual-evidence-summary.json').write_text(json.dumps({"
        "'schema_version':'wiki_viva_canary_visual_summary.v1','entries':[{"
        "'profile':'desktop','artifact':'desktop.png','route':'/demo/w/radar',"
        "'viewport':{'width':320,'height':240}}]}))\n"
        "if request_errors or console_errors: raise RuntimeError('served canary evidence observed errors')\n"
        "print('real_served_playwright_canary')\n",
        encoding="utf-8",
    )
    (kit / "scripts").mkdir()
    (kit / "scripts/wiki_generate_synthetic.py").write_text(
        "from pathlib import Path\n"
        "p=Path('docs/references/fixtures/demo-wiki/memories/artifact.txt')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "p.write_text('generated exactly\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    source_sha = _commit_all(kit, "synthetic portable release")

    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / ".gitignore").write_text(".wiki-viva/\n", encoding="utf-8")
    (consumer / "wiki.config.yaml").write_text(
        "repo_id: synthetic-consumer\n", encoding="utf-8"
    )
    consumer_b0 = _commit_all(consumer, "synthetic consumer B0")
    _git(consumer, "checkout", "-q", "-b", "wiki/synthetic-upgrade")

    classes = {
        "adapter_identity": "consumer_always",
        "affected_check": "affected",
        "audit": "consumer_always",
        "background_suite": "background_certification",
        "diff_check": "consumer_always",
        "input_stage": "consumer_always",
        "operational_pass": "consumer_always",
        "public_evidence_redaction": "consumer_always",
        "real_canary": "canary",
        "rollback_report_verification": "consumer_always",
        "semantic_inventory": "consumer_always",
        "snapshot_contract": "consumer_always",
        "upstream_check": "upstream_certified",
    }
    assert NEVER_REUSABLE_GATES.issubset(classes)
    gate_catalog = []
    for gate_id, gate_class in sorted(classes.items()):
        if gate_id == "rollback_report_verification":
            command = "python3 scripts/wiki_upgrade.py verify-rollback-report --check"
        elif gate_id == "real_canary":
            command = "python3 wiki_core/synthetic_canary.py"
        else:
            command = f'python3 -c "print(\'{gate_id}\')"'
        gate_catalog.append({"id": gate_id, "class": gate_class, "command": command})
    registry = seal_impact_registry(
        {
            "registry_version": "1.0.0",
            "unknown_policy": {
                "path": "full_matrix_and_lane_a",
                "contract": "full_matrix_and_lane_a",
            },
            "gate_catalog": gate_catalog,
            "full_matrix_gates": sorted(classes),
            "surfaces": [
                {
                    "id": "consumer_configuration",
                    "lane": "lane_b",
                    "path_patterns": ["wiki.config.yaml"],
                    "contracts": ["wiki_config.v1"],
                    "gates": ["affected_check"],
                    "depends_on": [],
                },
                {
                    "id": "portable_core",
                    "lane": "lane_a",
                    "path_patterns": ["wiki_core/**"],
                    "contracts": ["wiki_core.v1"],
                    "gates": ["upstream_check"],
                    "depends_on": [],
                },
            ],
            "boundary_policy": {
                "c1_portable_patterns": ["wiki_core/**"],
                "c2_generated_patterns": [
                    "docs/references/fixtures/demo-wiki/memories/**"
                ],
                "c3_consumer_patterns": ["wiki.config.yaml"],
                "domain_content_patterns": ["memories/**"],
            },
        }
    )
    gate_commands = {item["id"]: item["command"] for item in gate_catalog}
    gate_policies = {}
    assertions = {
        "adapter_identity": ["adapter_identity"],
        "audit": ["secret_private_audit"],
        "diff_check": ["diff_verification"],
        "input_stage": ["input_stage"],
        "public_evidence_redaction": ["public_evidence_redaction"],
        "real_canary": ["canary_real"],
        "rollback_report_verification": ["rollback_report_verification"],
        "semantic_inventory": ["semantic_inventory"],
        "snapshot_contract": ["snapshot_contract"],
    }
    for gate_id, gate_class in sorted(classes.items()):
        dependencies: list[str] = []
        if gate_id == "affected_check":
            dependencies = ["adapter_identity"]
        elif gate_id == "operational_pass":
            dependencies = ["input_stage", "semantic_inventory"]
        elif gate_id == "real_canary":
            dependencies = [
                "adapter_identity",
                "audit",
                "diff_check",
                "input_stage",
                "operational_pass",
                "semantic_inventory",
                "snapshot_contract",
            ]
        elif gate_id == "background_suite":
            dependencies = ["real_canary"]
        elif gate_id == "rollback_report_verification":
            dependencies = ["real_canary"]
        gate_policies[gate_id] = {
            "class": gate_class,
            "command_id": gate_id,
            "asserts": assertions.get(gate_id, [f"{gate_id}_contract"]),
            "reuse": {
                "upstream_certified": "exact_capsule",
                "affected": "impact",
            }.get(gate_class, "never"),
            "depends_on": dependencies,
            "resource_group": (
                "browser_private"
                if gate_class == "canary"
                else "python_test"
                if gate_class == "background_certification"
                else f"gate_{gate_id.replace('.', '_').replace('-', '_')}"
            ),
            "required_for_promotion": True,
        }
    c2_command = (
        "python3 -c \"from pathlib import Path; "
        "p=Path('docs/references/fixtures/demo-wiki/memories/artifact.txt'); "
        "p.parent.mkdir(parents=True,exist_ok=True); "
        "p.write_text('generated exactly\\n', "
        "encoding='utf-8')\""
    )
    boundary_operations = {
        "schema_version": "wiki_viva_upgrade_boundary_operations.v1",
        "c2_generators": [
            {
                "id": "generate_fixture",
                "command": c2_command,
                "owns_patterns": [
                    "docs/references/fixtures/demo-wiki/memories/**"
                ],
            }
        ],
        "c3_adapter": {
            "mode": "consumer_plan_commands",
            "contract": "synthetic_consumer_adapter.v1",
            "owns_patterns": ["wiki.config.yaml"],
        },
        "registry_sha256": "0" * 64,
    }
    boundary_operations["registry_sha256"] = boundary_operations_sha256(
        boundary_operations
    )
    package = {
        "schema_version": "wiki_viva_upgrade_package.v3",
        "release": {
            "id": "wiki-viva-v8-public-synthetic",
            "status": "ready",
            "source_sha": source_sha,
            "plan": "docs/synthetic-plan.md",
        },
        "contract_versions": {
            "route": "wiki_world_route.v8",
            "snapshot": "wiki_web_snapshot.v2",
            "snapshot_envelope": "wiki_web_snapshot.v2",
            "blocks": "wiki_templates.v2",
            "visual_grammar": "wiki_visual_grammar.v8",
            "semantic_visual_tokens": "wiki_semantic_visual_tokens.v1",
            "appearance": "wiki_cockpit_appearance.v1",
            "runtime": "wiki_world_runtime.v8",
            "source_lifecycle": "wiki_source_lifecycle.v2",
            "freshness": "wiki_web_freshness.v1",
            "server": "wiki_web_server.v6",
            "activity_timeline": "activity_timeline.v1",
            "temporal_event": "wiki_temporal_event.v1",
            "temporal_graph": "wiki_temporal_graph.v1",
            "experience_pack": "wiki_experience_pack.v1",
            "experience_pack_registry": "wiki_experience_pack_registry.v1",
            "experience_pack_lock": "wiki_experience_pack_lock.v1",
            "experience_pack_composition": "wiki_experience_pack_composition.v1",
            "asset_manifest": "wiki_cockpit_asset_manifest.v1",
            "downstream_adapter_manifest": "wiki_downstream_adapter_manifest.v1",
        },
        "portable_import": {"allow": ["wiki_core/**"], "block": ["memories/**"]},
        "preflight": {
            "branch_prefix": "wiki/",
            "required_gates": ["audit", "pytest"],
            "gate_mapping": {
                "audit": "audit",
                "pytest": "background_suite",
            },
        },
        "migration": {
            "commit_boundaries": [
                "faithful_public_import",
                "regenerated_artifacts",
                "downstream_adaptations",
            ],
            "generated_artifact_patterns": [
                "docs/references/fixtures/demo-wiki/memories/**"
            ],
            "required_gates": sorted(classes),
            "gate_commands": gate_commands,
            "command_registry": {
                gate_id: {
                    "argv": ["sh", "-c", command],
                    "cwd": ".",
                    "timeout_seconds": 900,
                    "env_allowlist": [],
                }
                for gate_id, command in gate_commands.items()
            },
            "command_registry_sha256": canonical_sha256(gate_catalog),
            "impact_registry": {
                "schema_version": "wiki_viva_upgrade_impact_registry.v1",
                "path": "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml",
                "sha256": registry["registry_sha256"],
            },
            "gate_policies": gate_policies,
            "boundary_operations": boundary_operations,
            "visual_profiles": ["desktop"],
        },
        "runtime_policy": {
            "rollout_modes": ["legacy", "compat", "v8"],
            "initial_downstream_mode": "compat",
            "rollback_first": "switch_to_compat_or_legacy",
            "rollback_second": "revert_reviewable_commits",
            "flags_must_not_weaken": [
                "route_grammar",
                "secret_scanning",
                "public_private_boundary",
            ],
        },
        "compatibility": [
            {
                "surface": "legacy_routes",
                "v8_behavior": "normalize_with_explicit_compat_identity",
                "warning_becomes_error": "future_evidence_based_release",
                "removal_target": "no_removal_without_replacement",
            }
        ],
    }
    package_path = tmp_path / "upgrade-package.yaml"
    package_path.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    certified = [
        {
            "id": gate["id"],
            "class": "upstream_certified",
            "provenance": "executed",
            "status": "passed",
            "exit_code": 0,
            "subject_sha": source_sha,
            "command_sha256": _digest(gate["command"]),
            "output_ref": f"outputs/{gate['id']}.log",
            "output_sha256": "0" * 64,
            "output_bytes": 1,
        }
        for gate in gate_catalog
        if gate["class"] == "upstream_certified"
    ]
    authority_base = tmp_path / "release-authority"
    visual_root = authority_base / "visual"
    image_path = visual_root / "images/world-overview.png"
    image_path.parent.mkdir(parents=True)
    image_raw = _png_bytes()
    image_path.write_bytes(image_raw)
    (visual_root / "visual-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "wiki_visual_evidence_manifest.v1",
                "entries": [
                    {
                        "id": "world-overview",
                        "path": "images/world-overview.png",
                        "sha256": hashlib.sha256(image_raw).hexdigest(),
                        "bytes": len(image_raw),
                        "route": "/demo/w/radar",
                        "browser": "chromium",
                        "viewport": {"width": 1280, "height": 900},
                        "capture_dimensions": {"width": 16, "height": 12},
                        "state": "radar-overview",
                        "public_synthetic": True,
                    }
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    gate_output_root = authority_base / "gate-output"
    (gate_output_root / "outputs").mkdir(parents=True)
    for gate in certified:
        (gate_output_root / gate["output_ref"]).write_text(
            f"gate={gate['id']}\nstatus=passed\n", encoding="utf-8"
        )
    capsule_payload = {
        "release_id": "wiki-viva-v8-public-synthetic",
        "status": "certified",
        "source_sha": source_sha,
        "package_sha256": "0" * 64,
        "portable_tree_sha256": "0" * 64,
        "command_registry": gate_catalog,
        "toolchain": {
            "python": {
                "name": platform.python_implementation().lower(),
                "version": platform.python_version(),
            },
            "node": {
                "name": "node",
                "version": subprocess.run(
                    ["node", "--version"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout.strip().removeprefix("v"),
            },
            "browser": {
                "name": "playwright",
                "version": subprocess.run(
                    ["playwright", "--version"],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                ).stdout.strip().removeprefix("Version "),
            },
            "runner": {"name": "wiki-upgrade", "version": "1.0.0"},
        },
        "certified_gates": certified,
        "run_id": "synthetic-run",
        "visual_manifest_ref": "visual-manifest.json",
        "visual_manifest_sha256": "0" * 64,
        "attestation_authority_id": "synthetic-ci",
        "attestation_ref": "execution-attestation.json",
    }
    capsule, trusted_attestation_sha256 = _seal_authority_capsule(
        package=package,
        registry=registry,
        payload=capsule_payload,
        source_root=kit,
        visual_root=visual_root,
        gate_output_root=gate_output_root,
    )
    authority_path = tmp_path / "release-authority.json"
    authority_path.write_text(
        json.dumps(
            {
                "schema_version": "wiki_viva_release_capsule_authority.v1",
                "visual_root": "release-authority/visual",
                "gate_output_root": "release-authority/gate-output",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    registry_path = tmp_path / "impact-registry.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    capsule_path = tmp_path / "release-capsule.json"
    capsule_path.write_text(json.dumps(capsule, indent=2), encoding="utf-8")
    return {
        "kit": kit,
        "consumer": consumer,
        "consumer_b0": consumer_b0,
        "package": package_path,
        "capsule": capsule_path,
        "registry": registry_path,
        "authority": authority_path,
        "trusted_attestation_sha256": trusted_attestation_sha256,
        "visual_root": visual_root,
        "gate_output_root": gate_output_root,
        "plan": consumer / ".wiki-viva/upgrade/plan.json",
    }


def _create_plan(fixture: dict[str, Path | str], changed_path: str = "wiki.config.yaml") -> dict:
    result = _run(fixture, *_plan_args(fixture), "--changed-path", changed_path)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(Path(fixture["plan"]).read_text(encoding="utf-8"))


def _complete_adoption(fixture: dict[str, Path | str]) -> tuple[dict, Path]:
    preplan = _create_plan(fixture)
    paused = _run(
        fixture,
        *_adopt_args(fixture, pause_before_canary=True),
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    assert '"status": "paused_before_canary"' in paused.stdout
    result = _run(fixture, *_adopt_args(fixture, resume=True))
    assert result.returncode == 0, result.stdout + result.stderr
    execution_paths = sorted(Path(fixture["plan"]).parent.glob("execution-plan-*.json"))
    plan = (
        json.loads(execution_paths[-1].read_text(encoding="utf-8"))
        if execution_paths
        else preplan
    )
    run_dir = (
        Path(fixture["consumer"])
        / ".wiki-viva/upgrade/runs"
        / plan["plan_sha256"][:16]
    )
    return plan, run_dir


def test_canary_handoff_resumes_background_on_same_consumer_run(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    _create_plan(synthetic_upgrade)
    fast = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert fast.returncode == 0, fast.stdout + fast.stderr

    canary = _run(
        synthetic_upgrade,
        *_adopt_args(
            synthetic_upgrade,
            resume=True,
            pause_before_background=True,
        ),
    )
    assert canary.returncode == 0, canary.stdout + canary.stderr
    assert '"status": "paused_before_background"' in canary.stdout
    execution = json.loads(
        next(Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json"))
        .read_text(encoding="utf-8")
    )
    run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / execution["plan_sha256"][:16]
    )
    before = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert before["status"] == "paused_before_background"
    assert before["plan_sha256"] == execution["plan_sha256"]
    assert before["gate_results"]["real_canary"]["status"] == "passed"
    assert "background_suite" not in before["gate_results"]
    assert not (run_dir / "adoption-receipt.json").exists()

    background = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )
    assert background.returncode == 0, background.stdout + background.stderr
    after = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert after["status"] == "complete"
    assert after["plan_sha256"] == before["plan_sha256"]
    assert after["identity_sha256"] == before["identity_sha256"]
    assert after["gate_results"]["background_suite"]["status"] == "passed"
    assert (run_dir / "adoption-receipt.json").is_file()


def test_ci_fast_adoption_handoff_is_resumable_runner_state(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    destination_value = os.environ.get("WIKI_UPGRADE_CI_HANDOFF")
    if not destination_value:
        pytest.skip("CI handoff export is only enabled by the two-lane workflow")
    preplan = _create_plan(synthetic_upgrade)
    fast = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert fast.returncode == 0, fast.stdout + fast.stderr
    assert '"status": "paused_before_canary"' in fast.stdout
    execution_paths = sorted(Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json"))
    assert len(execution_paths) == 1
    execution = json.loads(execution_paths[0].read_text(encoding="utf-8"))
    run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / execution["plan_sha256"][:16]
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "paused_before_canary"
    assert state["gate_results"]
    assert not (run_dir / "adoption-receipt.json").exists()

    destination = Path(destination_value).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    fixture_root = Path(synthetic_upgrade["package"]).parent
    shutil.copytree(fixture_root, destination, symlinks=True)
    (destination / "trusted-attestation-sha256").write_text(
        str(synthetic_upgrade["trusted_attestation_sha256"]) + "\n",
        encoding="utf-8",
    )
    handoff = {
        "schema_version": "wiki_viva_upgrade_ci_handoff.v1",
        "preplan_sha256": preplan["plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "run_key": execution["plan_sha256"][:16],
        "state_sha256": hashlib.sha256(
            (run_dir / "state.json").read_bytes()
        ).hexdigest(),
    }
    (destination / "handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_ci_lane_a_inputs_export_only_public_uncertified_fixture(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    destination_value = os.environ.get("WIKI_UPGRADE_CI_CERTIFICATION_INPUTS")
    if not destination_value:
        pytest.skip("CI Lane A input export is enabled only by the two-lane workflow")
    destination = Path(destination_value).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    fixture_root = Path(synthetic_upgrade["package"]).parent
    shutil.copytree(fixture_root, destination, symlinks=True)
    assert (destination / "upgrade-package.yaml").is_file()
    assert (destination / "impact-registry.yaml").is_file()
    assert (destination / "public-kit/.git").is_dir()


def test_certify_executes_only_upstream_and_seals_authority(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    output = tmp_path / "lane-a-certified"
    result = _run(synthetic_upgrade, *_certify_args(synthetic_upgrade, output))
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"status": "certified"' in result.stdout
    required = {
        "release-capsule.json",
        "certification-receipt.json",
        "release-authority.json",
        "trusted-attestation-sha256.txt",
        "gate-output/execution-attestation.json",
        "gate-output/toolchain/probe-manifest.json",
        "visual/visual-manifest.json",
    }
    assert all((output / relative).is_file() for relative in required)
    capsule = json.loads((output / "release-capsule.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (output / "certification-receipt.json").read_text(encoding="utf-8")
    )
    authority = json.loads(
        (output / "release-authority.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in capsule["certified_gates"]] == ["upstream_check"]
    assert receipt["upstream_gate_ids"] == ["upstream_check"]
    assert receipt["certification_gate_ids"] == ["upstream_check"]
    assert "background_gate_ids" not in receipt
    assert {item["class"] for item in receipt["gate_results"]} == {
        "upstream_certified"
    }
    assert receipt["human_gate_required"] is True
    assert authority["certification_receipt_ref"] == "certification-receipt.json"
    assert authority["release_capsule_ref"] == "release-capsule.json"
    assert (output / "gate-output/outputs/upstream_check.log").is_file()
    assert not (output / "gate-output/outputs/background_suite.log").exists()

    plan_args = _plan_args(synthetic_upgrade)
    plan_args[plan_args.index("--capsule") + 1] = str(output / "release-capsule.json")
    plan_args[plan_args.index("--authority") + 1] = str(output / "release-authority.json")
    plan_args[plan_args.index("--trusted-attestation-sha256") + 1] = (
        output / "trusted-attestation-sha256.txt"
    ).read_text(encoding="ascii").strip()
    planned = _run(synthetic_upgrade, *plan_args, "--changed-path", "wiki.config.yaml")
    assert planned.returncode == 0, planned.stdout + planned.stderr

    upstream_log = output / "gate-output/outputs/upstream_check.log"
    upstream_log.write_text("fabricated replacement\n", encoding="utf-8")
    rejected = _run(synthetic_upgrade, *plan_args, "--changed-path", "wiki.config.yaml")
    assert rejected.returncode == 2
    assert '"error_code": "lane_contract_rejected"' in rejected.stdout
    assert str(output) not in rejected.stdout


def test_certify_refuses_validation_pending_without_creating_authority(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    package = yaml.safe_load(Path(synthetic_upgrade["package"]).read_text(encoding="utf-8"))
    package["release"]["status"] = "validation_pending"
    pending = tmp_path / "validation-pending.yaml"
    pending.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    fixture = {**synthetic_upgrade, "package": pending}
    output = tmp_path / "must-not-exist"
    result = _run(fixture, *_certify_args(fixture, output))
    assert result.returncode == 2
    assert '"error_code": "release_not_releasable"' in result.stdout
    assert not output.exists()


def test_v1_v2_transition_package_is_explicitly_outside_v3_runner(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    package = yaml.safe_load(Path(synthetic_upgrade["package"]).read_text(encoding="utf-8"))
    package["schema_version"] = "wiki_viva_upgrade_package.v2"
    legacy = tmp_path / "legacy-package.yaml"
    legacy.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    args = _plan_args({**synthetic_upgrade, "package": legacy})
    result = _run(synthetic_upgrade, *args, "--changed-path", "wiki.config.yaml")
    assert result.returncode == 2
    assert '"error_code": "legacy_package_requires_original_runbook"' in result.stdout
    assert "migration.required_gates" in result.stdout


def test_plan_adopt_resume_canary_and_rollback_are_complete_and_path_free(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan, run_dir = _complete_adoption(synthetic_upgrade)
    assert plan["status"] == "ready"
    assert plan["selection"]["escalation"] == "consumer_delta"
    assert "upstream_check" in plan["selection"]["omitted_gates"]
    receipt = json.loads((run_dir / "adoption-receipt.json").read_text(encoding="utf-8"))
    report = json.loads((run_dir / "migration-report.json").read_text(encoding="utf-8"))
    private_report = json.loads(
        (run_dir / "migration-report.private.json").read_text(encoding="utf-8")
    )
    public_report = json.loads(
        (run_dir / "migration-report.public.json").read_text(encoding="utf-8")
    )
    rollback = json.loads((run_dir / "rollback.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "passed"
    assert report["promotion_ready"] is True
    assert report["human_gate_required"] is True
    assert public_report["public_redacted"] is True
    assert "identity" not in public_report
    assert public_report["identity_sha256"] == canonical_sha256(plan["identity"])
    public_text = json.dumps(public_report, sort_keys=True)
    assert plan["identity"]["consumer_B0"] not in public_text
    assert plan["identity"]["consumer_C3"] not in public_text
    assert public_report["evidence"]["raw_private_evidence"] == "omitted"
    assert "background_suite" in plan["selection"]["selected_gates"]
    assert "operational_pass" in plan["selection"]["selected_gates"]
    preflight_by_id = {item["id"]: item for item in plan["preflight"]["results"]}
    assert preflight_by_id["pytest"]["command_id"] == "background_suite"
    assert len(private_report["evidence"]["gate_logs"]) == len(
        plan["selection"]["selected_gates"]
    )
    assert len(private_report["evidence"]["console"]) >= len(
        plan["selection"]["selected_gates"]
    )
    assert private_report["evidence"]["network"]
    assert rollback["tree_equal"] is True

    resumed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert '"reused_receipt": true' in resumed.stdout

    verified = _run(
        synthetic_upgrade,
        "verify-rollback-report",
        "--check",
        cwd=Path(synthetic_upgrade["consumer"]),
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert '"status": "verified"' in verified.stdout
    assert str(Path(synthetic_upgrade["consumer"])) not in resumed.stdout
    assert str(Path(synthetic_upgrade["consumer"])) not in verified.stdout


def test_unknown_impact_selects_full_matrix_and_blocks_adopt_until_lane_a(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade, "unclassified/surface.txt")
    assert plan["status"] == "requires_lane_a"
    assert plan["selection"]["escalation"] == "unknown_impact_full_lane"
    assert plan["selection"]["selected_gates"] == sorted(
        item["id"] for item in plan["gate_catalog"]
    )
    adopted = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert adopted.returncode == 2
    assert '"error_code": "lane_a_required"' in adopted.stdout
    assert '"next_action"' in adopted.stdout


def test_plan_refuses_detached_or_non_review_branch(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    _git(consumer, "checkout", "-q", "-b", "unsafe-direct-main")
    result = _run(synthetic_upgrade, *_plan_args(synthetic_upgrade))
    assert result.returncode == 2
    assert '"error_code": "upgrade_branch_required"' in result.stdout
    assert not Path(synthetic_upgrade["plan"]).exists()


def test_pre_mutation_plan_proves_distinct_c1_c2_c3_and_replays_generator(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    kit = Path(synthetic_upgrade["kit"])
    b0 = str(synthetic_upgrade["consumer_b0"])
    _git(consumer, "checkout", "-q", "-b", "wiki/synthetic-migration")
    (consumer / "wiki_core").mkdir()
    for relative in ("wiki_core/portable.py", "wiki_core/synthetic_canary.py"):
        source = kit / relative
        destination = consumer / relative
        destination.write_bytes(source.read_bytes())
    c1 = _commit_all(consumer, "C1 faithful public import")
    generated = consumer / "docs/references/fixtures/demo-wiki/memories/artifact.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text(
        "generated exactly\n", encoding="utf-8"
    )
    c2 = _commit_all(consumer, "C2 regenerated artifacts")
    (consumer / "wiki.config.yaml").write_text(
        "repo_id: synthetic-consumer-v8\n", encoding="utf-8"
    )
    c3 = _commit_all(consumer, "C3 consumer adaptation")
    _git(consumer, "checkout", "-q", "wiki/synthetic-upgrade")

    package = yaml.safe_load(Path(synthetic_upgrade["package"]).read_text(encoding="utf-8"))
    package["migration"]["commit_boundaries"] = [
        "faithful_public_import",
        "regenerated_artifacts",
        "downstream_adaptations",
    ]
    _reseal_package(synthetic_upgrade, package)
    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--consumer-b0",
        b0,
        "--consumer-c1",
        c1,
        "--consumer-c2",
        c2,
        "--consumer-c3",
        c3,
        "--changed-path",
        "wiki.config.yaml",
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert _git(consumer, "rev-parse", "HEAD") == b0
    plan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))
    assert len({plan["boundary_commits"][key] for key in ("B0", "C1", "C2", "C3")}) == 4
    assert all(plan["boundaries"][key] for key in ("C1", "C2", "C3"))
    assert plan["boundary_execution"]["C2"][0]["provenance"] == "executed"
    assert (Path(synthetic_upgrade["plan"]).parent / "c2-regenerator.log").is_file()

    _git(consumer, "checkout", "-q", "wiki/synthetic-migration")
    adopted = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert adopted.returncode == 0, adopted.stdout + adopted.stderr
    run_dir = consumer / ".wiki-viva/upgrade/runs" / plan["plan_sha256"][:16]
    rollback = json.loads((run_dir / "rollback.json").read_text(encoding="utf-8"))
    assert rollback["tree_equal"] is True


def test_resume_after_mid_c2_failure_keeps_consumer_at_clean_recorded_phase(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    fail_once = (
        "python3 -c \"import os,sys; from pathlib import Path; "
        "p=Path(os.environ['WIKI_VIVA_KIT_ROOT'])/'.fail-c2-once'; "
        "existed=p.exists(); p.write_text('seen'); "
        "a=Path('docs/references/fixtures/demo-wiki/memories/artifact.txt'); "
        "a.parent.mkdir(parents=True,exist_ok=True); "
        "a.write_text('generated exactly\\n', "
        "encoding='utf-8'); sys.exit(0 if existed else 3)\""
    )
    package = yaml.safe_load(Path(synthetic_upgrade["package"]).read_text(encoding="utf-8"))
    operations = package["migration"]["boundary_operations"]
    operations["c2_generators"][0]["command"] = fail_once
    operations["registry_sha256"] = boundary_operations_sha256(operations)
    _reseal_package(synthetic_upgrade, package)
    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    preplan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))

    failed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert failed.returncode == 2
    assert '"error_code": "mutation_command_failed"' in failed.stdout
    mutation_state_path = (
        Path(synthetic_upgrade["plan"]).parent
        / f"mutation-state-{preplan['plan_sha256'][:16]}.json"
    )
    mutation_state = json.loads(mutation_state_path.read_text(encoding="utf-8"))
    assert mutation_state["phase"] == "C1"
    assert _git(consumer, "rev-parse", "HEAD") == mutation_state["commits"]["C1"]
    assert _git(consumer, "status", "--porcelain=v1", "--untracked-files=all") == ""

    resumed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr


def test_resume_rejects_stale_plan_manual_evidence_and_changed_c3(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan, run_dir = _complete_adoption(synthetic_upgrade)
    state_path = run_dir / "state.json"
    original = json.loads(state_path.read_text(encoding="utf-8"))

    stale = copy.deepcopy(original)
    stale["plan_sha256"] = "f" * 64
    state_path.write_text(json.dumps(stale), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "stale_resume_plan"' in result.stdout

    stale_command = copy.deepcopy(original)
    command_gate = sorted(stale_command["gate_results"])[0]
    stale_command["gate_results"][command_gate]["command_sha256"] = "e" * 64
    state_path.write_text(json.dumps(stale_command), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "stale_resume_gate_identity"' in result.stdout

    manual = copy.deepcopy(original)
    first_gate = sorted(manual["gate_results"])[0]
    manual["gate_results"][first_gate]["provenance"] = "manual"
    state_path.write_text(json.dumps(manual), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "manual_evidence_rejected"' in result.stdout

    state_path.write_text(json.dumps(original), encoding="utf-8")
    consumer = Path(synthetic_upgrade["consumer"])
    (consumer / "wiki.config.yaml").write_text("repo_id: changed-c3\n", encoding="utf-8")
    _commit_all(consumer, "change C3 after plan")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "changed_consumer_C3"' in result.stdout
    assert str(consumer) not in result.stdout
    assert plan["identity"]["consumer_C3"] != _git(consumer, "rev-parse", "HEAD")


def test_scheduler_waits_for_dependencies_before_parallel_gate_wave(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    package = yaml.safe_load(Path(synthetic_upgrade["package"]).read_text(encoding="utf-8"))
    package["migration"]["gate_policies"]["audit"]["resource_group"] = (
        "consumer_python"
    )
    package["migration"]["gate_policies"]["affected_check"]["depends_on"] = [
        "audit"
    ]
    package["migration"]["gate_policies"]["affected_check"]["resource_group"] = (
        "consumer_python"
    )
    _reseal_package(synthetic_upgrade, package)
    _create_plan(synthetic_upgrade)
    plan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))
    affected = next(item for item in plan["gate_catalog"] if item["id"] == "affected_check")
    assert affected["depends_on"] == ["audit"]
    assert affected["resource_group"] == "consumer_python"
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    audit_completed = next(
        index
        for index, event in enumerate(events)
        if event.get("event") == "gate_completed" and event.get("gate") == "audit"
    )
    affected_started = next(
        index
        for index, event in enumerate(events)
        if event.get("event") == "gate_started" and event.get("gate") == "affected_check"
    )
    assert audit_completed < affected_started
    progress = [event for event in events if event.get("event") == "matrix_progress"]
    assert progress
    assert all(
        {"phase", "completed", "total", "elapsed_seconds", "eta_seconds"}
        .issubset(event)
        for event in progress
    )
    assert progress[-1]["completed"] <= progress[-1]["total"]


def test_forged_omission_unsafe_output_and_boundary_mixing_fail_closed(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    plan = _create_plan(synthetic_upgrade)
    plan["selection"]["selected_gates"].remove("audit")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256")
    plan["plan_sha256"] = canonical_sha256(unsigned)
    Path(synthetic_upgrade["plan"]).write_text(json.dumps(plan), encoding="utf-8")
    forged = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert forged.returncode == 2
    assert '"error_code": "stale_or_forged_plan_derivation"' in forged.stdout

    Path(synthetic_upgrade["plan"]).unlink()
    outside = tmp_path / "outside-plan.json"
    unsafe = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
        "--out",
        str(outside),
    )
    assert unsafe.returncode == 2
    assert '"error_code": "unsafe_output_boundary"' in unsafe.stdout
    assert str(tmp_path) not in unsafe.stdout
    assert not outside.exists()

    consumer = Path(synthetic_upgrade["consumer"])
    b0 = str(synthetic_upgrade["consumer_b0"])
    (consumer / "wiki_core").mkdir()
    (consumer / "wiki_core/consumer.py").write_text("VALUE = 1\n", encoding="utf-8")
    c3 = _commit_all(consumer, "mix portable code into C3")
    _git(consumer, "checkout", "-q", "-b", "wiki/mixed-plan", b0)
    mixed = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--consumer-b0",
        b0,
        "--consumer-c1",
        b0,
        "--consumer-c2",
        b0,
        "--consumer-c3",
        c3,
        "--changed-path",
        "wiki.config.yaml",
    )
    assert mixed.returncode == 2
    assert '"error_code": "boundary_ownership_mismatch"' in mixed.stdout


def test_rollback_report_tamper_is_not_accepted(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    _plan, run_dir = _complete_adoption(synthetic_upgrade)
    rollback_path = run_dir / "rollback.json"
    rollback = json.loads(rollback_path.read_text(encoding="utf-8"))
    rollback["tree_equal"] = False
    rollback_path.write_text(json.dumps(rollback), encoding="utf-8")
    result = _run(
        synthetic_upgrade,
        "verify-rollback-report",
        "--check",
        "--run-dir",
        str(run_dir),
        cwd=Path(synthetic_upgrade["consumer"]),
    )
    assert result.returncode == 2
    assert '"error_code": "rollback_report_mismatch"' in result.stdout
    assert str(run_dir) not in result.stdout


def test_upgrade_command_is_versioned_and_only_safe_verifier_is_operator_allowed() -> None:
    assert is_allowed_argv(
        ["python3", "scripts/wiki_upgrade.py", "verify-rollback-report", "--check"]
    )
    assert not is_allowed_argv(["python3", "scripts/wiki_upgrade.py", "certify"])
    assert not is_allowed_argv(["python3", "scripts/wiki_upgrade.py", "plan"])
    assert not is_allowed_argv(["python3", "scripts/wiki_upgrade.py", "adopt"])
    for relative in (
        "scripts/README.md",
        "memories/system/wiki/command-reference.md",
    ):
        assert "wiki_upgrade.py" in (ROOT / relative).read_text(encoding="utf-8")


def test_actual_operator_command_receives_only_complete_exact_bound_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml").read_text(
            encoding="utf-8"
        )
    )
    command = package["migration"]["gate_commands"]["real_canary"]
    assert command == "npm --prefix apps/wiki-cockpit run test:e2e:operator"
    assert upgrade_runner._parse_command(command, kit_root=ROOT) == [
        "npm",
        "--prefix",
        "apps/wiki-cockpit",
        "run",
        "test:e2e:operator",
    ]
    consumer_sha = "a" * 40
    public_sha = "b" * 40
    values = {
        "WIKI_COCKPIT_SNAPSHOT_URL": "http://127.0.0.1:43123/api/snapshot/",
        "WIKI_COCKPIT_REAL_BASE_URL": "http://127.0.0.1:43123",
        "WIKI_COCKPIT_EXPECT_REPO_ID": "synthetic-consumer",
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_REVISION": "synthetic-revision",
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_HASH": "c" * 64,
        "WIKI_COCKPIT_EXPECT_CONSUMER_HEAD": consumer_sha,
        "WIKI_COCKPIT_EXPECT_PUBLIC_RELEASE_SHA": public_sha,
        "WIKI_COCKPIT_EXPECT_ADAPTER_HASH": "d" * 64,
        "WIKI_COCKPIT_EXPECT_SNAPSHOT_VERSION": "wiki_web_snapshot.v2",
        "WIKI_COCKPIT_EXPECT_RUNTIME_VERSION": "wiki_world_runtime.v8",
        "WIKI_COCKPIT_EXPECT_SERVER_VERSION": "wiki_web_server.v6",
        "WIKI_COCKPIT_EXPECT_TEMPORAL_GRAPH_VERSION": "wiki_temporal_graph.v1",
        "WIKI_COCKPIT_EXPECT_TEMPORAL_EVENT_VERSION": "wiki_temporal_event.v1",
        "WIKI_COCKPIT_EXPECT_EXPERIENCE_PACK_COMPOSITION_VERSION": "wiki_experience_pack_composition.v1",
        "WIKI_COCKPIT_EXPECT_COMPOSITION_SHA256": "e" * 64,
        "WIKI_COCKPIT_EXPECT_ACTIVE_PACKS": "[]",
        "WIKI_COCKPIT_EXPECT_CAPABILITIES": "temporal_graph,experience_packs",
        "WIKI_COCKPIT_MIN_PAGES": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WIKI_COCKPIT_API_TOKEN", "must-not-cross-runner-boundary")
    environment = upgrade_runner._gate_environment(
        tmp_path,
        ROOT,
        "real_canary",
        subject_sha=consumer_sha,
        public_release_sha=public_sha,
        require_operator_environment=True,
    )
    assert all(environment[key] == value for key, value in values.items())
    assert "WIKI_COCKPIT_API_TOKEN" not in environment
    monkeypatch.delenv("WIKI_COCKPIT_EXPECT_SERVER_VERSION")
    with pytest.raises(
        upgrade_runner.RunnerError, match="operator environment is incomplete"
    ):
        upgrade_runner._gate_environment(
            tmp_path,
            ROOT,
            "real_canary",
            subject_sha=consumer_sha,
            public_release_sha=public_sha,
            require_operator_environment=True,
        )


def test_two_lane_workflow_handoff_is_retry_safe_for_rerun_failed_jobs() -> None:
    workflow_path = ROOT / ".github/workflows/wiki-upgrade-lanes.yml"
    workflow = workflow_path.read_text(
        encoding="utf-8"
    )
    parsed = yaml.safe_load(workflow)
    assert "github.run_attempt" not in workflow
    assert "wiki-upgrade-fast-adoption-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert "wiki-upgrade-canary-handoff-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert "wiki-upgrade-background-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert workflow.count("overwrite: true") >= 4
    assert "payload['ci_run_id'] = os.environ['GITHUB_RUN_ID']" in workflow
    assert "manifest['ci_run_id'] == os.environ['GITHUB_RUN_ID']" in workflow
    assert "manifest['ci_head_sha'] == os.environ['GITHUB_SHA']" in workflow
    background = parsed["jobs"]["background-certification"]
    assert background["needs"] == "canary"
    assert "canary-handoff.tgz" in workflow
    assert "paused_before_background" in workflow
    assert "--pause-before-background" in workflow
    assert "Broad Python suite" not in workflow
    assert "Broad non-browser cockpit matrix" not in workflow
