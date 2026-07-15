from __future__ import annotations

import copy
import datetime as dt
import functools
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import zlib
from io import BytesIO
from pathlib import Path

import pytest
import yaml
import scripts.wiki_upgrade as upgrade_runner

from wiki_core.upgrade_lanes import (
    LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION,
    NEVER_REUSABLE_GATES,
    ReleaseCapsuleAuthority,
    VISUAL_PROFILE_CONTRACTS,
    canonical_sha256,
    collect_release_attestation,
    seal_impact_registry,
    seal_release_capsule,
)
from wiki_core.upgrade import (
    CONFIG_BOUND_C3_ROLE_SPECS,
    boundary_operations_sha256,
)
from wiki_core.web.commands import is_allowed_argv
from wiki_core.node_workspace import (
    ALLOWED_SCRIPTS,
    authority_identity_sha256 as node_authority_identity_sha256,
    build_policy as build_node_workspace_policy,
    capture_authority as capture_node_workspace_authority,
    load_authority as load_node_workspace_authority,
    npm_workspace_toolchain_identity,
    serialize_policy as serialize_node_workspace_policy,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/wiki_upgrade.py"
_SYNTHETIC_NODE_CACHE: dict[str, object] = {}


@functools.lru_cache(maxsize=1)
def _active_toolchain() -> dict[str, dict[str, str]]:
    python_identity, _python_argv, _python_raw = upgrade_runner._python_toolchain_probe(
        cwd=ROOT
    )
    browser_identity, _browser_argv, _browser_raw = (
        upgrade_runner._browser_toolchain_probe(kit_root=ROOT)
    )
    npm_identity, _npm_argv, _npm_raw = upgrade_runner._npm_toolchain_probe(cwd=ROOT)
    node_identity, _node_argv, _node_raw = upgrade_runner._node_toolchain_probe(
        cwd=ROOT
    )
    return {
        "python": python_identity,
        "node": node_identity,
        "npm": npm_identity,
        "browser": browser_identity,
        "runner": {
            "name": "wiki-upgrade",
            "version": upgrade_runner._runner_identity_version(ROOT),
        },
    }


def test_c3_stage_accepts_consumer_skill_but_rejects_portable_wiki_skill() -> None:
    upgrade_runner._require_stage_paths(
        [".skills/local-operator/SKILL.md", ".skills/README.md", "AGENTS.md"],
        [".skills/*/**", ".skills/README.md", "AGENTS.md"],
        label="C3",
        forbidden_patterns=[".skills/wiki-*/**"],
    )
    with pytest.raises(upgrade_runner.RunnerError, match="outside its owned boundary"):
        upgrade_runner._require_stage_paths(
            [".skills/README.md"],
            [".skills/*/**"],
            label="C3",
        )
    with pytest.raises(upgrade_runner.RunnerError, match="outside its owned boundary"):
        upgrade_runner._require_stage_paths(
            [".skills/wiki-viva/SKILL.md"],
            [".skills/*/**"],
            label="C3",
            forbidden_patterns=[".skills/wiki-*/**"],
        )


def test_toolchain_identity_binds_resolved_python_and_launched_browser() -> None:
    toolchain = _active_toolchain()
    assert toolchain["python"]["name"].endswith("-resolved")
    assert re.fullmatch(
        r"[A-Za-z0-9._+-]+\+deps\.[0-9a-f]{64}",
        toolchain["python"]["version"],
    )
    assert toolchain["browser"]["name"] == "playwright-chromium"
    assert re.fullmatch(
        r"[A-Za-z0-9._+-]+\+chromium\.[A-Za-z0-9._+-]+",
        toolchain["browser"]["version"],
    )
    assert toolchain["npm"]["name"] == "npm-resolved"
    assert re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+\+[a-z0-9._-]+\.[a-z0-9._-]+\.tree\.[0-9a-f]{64}",
        toolchain["npm"]["version"],
    )
    assert toolchain["node"]["name"] == "node-resolved"
    assert ".runtime." in toolchain["node"]["version"]


def test_python_probe_uses_only_an_alias_for_the_executing_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    divergent = tmp_path / "divergent-python3"
    divergent.write_text("synthetic", encoding="utf-8")
    active = sys.executable

    monkeypatch.setattr(
        upgrade_runner.shutil,
        "which",
        lambda name: str(divergent) if name == "python3" else active,
    )
    assert upgrade_runner._active_python_alias() == "python"
    assert upgrade_runner._parse_command(
        "python3 -m pytest -q -W error tests/", kit_root=ROOT
    ) == ["python", "-m", "pytest", "-q", "-W", "error", "tests/"]

    monkeypatch.setattr(
        upgrade_runner.shutil,
        "which",
        lambda _name: str(divergent),
    )
    with pytest.raises(upgrade_runner.RunnerError, match="executing this runner"):
        upgrade_runner._active_python_alias()
    with pytest.raises(upgrade_runner.RunnerError, match="executing this runner"):
        upgrade_runner._parse_command(
            "python3 scripts/wiki_build_demo.py --check", kit_root=ROOT
        )


@pytest.mark.parametrize(
    "command",
    [
        "npm --prefix apps/wiki-cockpit run test",
        "node apps/wiki-cockpit/scripts/build.mjs",
        "/usr/local/bin/npm run test",
        "env CI=1 npx playwright test",
        "sh -c 'npm run test'",
    ],
)
def test_parse_command_rejects_raw_node_before_execution(command: str) -> None:
    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._parse_command(command, kit_root=ROOT)

    assert caught.value.code == "raw_node_command_rejected"


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/wiki_node_workspace.py run test",
        "python3 ./scripts/wiki_node_workspace.py run test",
        "python3 scripts/wiki_node_workspace.py test",
        "python3 scripts/wiki_node_workspace.py run",
    ],
)
def test_parse_command_rejects_non_exact_node_wrapper(command: str) -> None:
    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._parse_command(command, kit_root=ROOT)

    assert caught.value.code == "invalid_node_workspace_command"


def test_parse_command_preserves_non_node_python_and_git_commands() -> None:
    parsed_git = upgrade_runner._parse_command("git diff --check", kit_root=ROOT)
    assert parsed_git[0] == upgrade_runner.resolved_git_executable()
    assert parsed_git[-4:] == ["diff", "--no-ext-diff", "--no-textconv", "--check"]
    parsed = upgrade_runner._parse_command(
        "python3 scripts/wiki_audit.py --check", kit_root=ROOT
    )
    assert parsed == [
        upgrade_runner._active_python_alias(),
        "scripts/wiki_audit.py",
        "--check",
    ]


@pytest.mark.parametrize(
    "command",
    [
        'python3 -c "print(1)" API_TOKEN=synthetic-secret-value',
        'python3 -c "print(1)" --token=synthetic-secret-value',
        'python3 -c "print(1)" Authorization: Bearer synthetic-secret-value',
        'python3 -c "print(1)" Cookie: session=synthetic-secret-value',
        'python3 -c "print(1)" https://user:synthetic-secret-value@example.invalid',
        'python3 -c "print(1)" https://example.invalid/?api_key=synthetic-secret-value',
        'python3 -c "print(1)" api%255Ftoken%253Dsynthetic-secret-value',
    ],
)
def test_named_and_parsed_commands_reject_secret_input_without_echo(
    command: str,
) -> None:
    for operation in (
        lambda: upgrade_runner._named_commands(
            [f"adapt::{command}"], kit=ROOT, label="C3"
        ),
        lambda: upgrade_runner._parse_command(command, kit_root=ROOT),
    ):
        with pytest.raises(upgrade_runner.RunnerError) as caught:
            operation()
        assert caught.value.code == "secret_command_input"
        public_failure = json.dumps(upgrade_runner._failure_payload(caught.value))
        assert "synthetic-secret-value" not in public_failure


def test_command_secret_filter_accepts_benign_public_arguments() -> None:
    command = 'python3 -c "print(1)" --session-mode=synthetic --tokenize=public'
    parsed = upgrade_runner._parse_command(command, kit_root=ROOT)
    assert parsed[-2:] == ["--session-mode=synthetic", "--tokenize=public"]


def test_parse_command_rejects_non_diff_git_subcommands() -> None:
    for command in ("git status", "git evil", "git diff --stat"):
        with pytest.raises(upgrade_runner.RunnerError) as caught:
            upgrade_runner._parse_command(command, kit_root=ROOT)
        assert caught.value.code == "unsafe_git_command"


def test_certification_python_gate_executes_probed_alias_but_binds_registered_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    probed = bin_root / "python"
    probed.write_text(
        "#!/bin/sh\nprintf 'probed-python-gate\\n'\n",
        encoding="utf-8",
    )
    probed.chmod(0o755)
    divergent = bin_root / "python3"
    divergent.write_text(
        "#!/bin/sh\nprintf 'divergent-python-gate\\n'\nexit 41\n",
        encoding="utf-8",
    )
    divergent.chmod(0o755)
    monkeypatch.setattr(upgrade_runner, "_active_python_alias", lambda: "python")
    monkeypatch.setattr(
        upgrade_runner,
        "_certification_environment",
        lambda: {
            "PATH": str(bin_root),
            "PYTHONUNBUFFERED": "1",
            "TZ": "UTC",
        },
    )
    monkeypatch.setattr(
        upgrade_runner, "_require_certification_source", lambda *_args: None
    )
    command = "python3 -m synthetic_gate"
    output_root = tmp_path / "gate-output"

    result = upgrade_runner._run_certification_gate(
        {
            "id": "synthetic_python",
            "class": "upstream_certified",
            "command": command,
        },
        source_root=tmp_path,
        gate_output_root=output_root,
        source_sha="a" * 40,
        timeout=30,
        heartbeat=1,
    )

    assert result["status"] == "passed"
    assert result["command_sha256"] == hashlib.sha256(command.encode()).hexdigest()
    assert (output_root / result["output_ref"]).read_text(encoding="utf-8") == (
        "probed-python-gate\n"
    )


def test_failed_certification_wave_freezes_subject_even_after_strict_gate_passed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_sha = "a" * 40
    catalog = [
        {
            "id": "browser_synthetic_release",
            "class": "upstream_certified",
            "command": ("python3 scripts/wiki_node_workspace.py run test:e2e:release"),
        },
        {
            "id": "portable_python",
            "class": "upstream_certified",
            "command": "python3 -m pytest -q -W error tests/",
        },
    ]
    package = {
        "migration": {
            "gate_policies": {
                "browser_synthetic_release": {
                    "depends_on": [],
                    "resource_group": "browser_public",
                },
                "portable_python": {
                    "depends_on": [],
                    "resource_group": "python_test",
                },
            }
        }
    }
    monkeypatch.setattr(
        upgrade_runner, "_require_certification_source", lambda *_args: None
    )

    def synthetic_result(gate: dict[str, str], **_kwargs: object) -> dict[str, object]:
        return {
            "id": gate["id"],
            "status": (
                "passed" if gate["id"] == "browser_synthetic_release" else "failed"
            ),
        }

    monkeypatch.setattr(upgrade_runner, "_run_certification_gate", synthetic_result)

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._execute_certification_matrix(
            package=package,
            catalog=catalog,
            source_root=tmp_path,
            gate_output_root=tmp_path / "gate-output",
            source_sha=source_sha,
            jobs=2,
            timeout=30,
            heartbeat=1,
        )

    assert caught.value.code == "certification_gate_failed"
    assert caught.value.surface == "portable_python"
    assert "freeze this failed release subject" in caught.value.next_action
    assert "never retry or relabel this subject" in caught.value.next_action
    assert "start a new certification run" not in caught.value.next_action


def _certification_source(tmp_path: Path, gate_source: str) -> tuple[Path, str]:
    source = tmp_path / "source"
    _init_repo(source)
    (source / "tracked.txt").write_text("original\n", encoding="utf-8")
    (source / "gate.py").write_text(gate_source, encoding="utf-8")
    return source, _commit_all(source, "initialize certification source")


@pytest.mark.parametrize("mutation", ["tracked", "untracked", "head"])
def test_certification_gate_rejects_source_mutation(
    tmp_path: Path, mutation: str
) -> None:
    source, source_sha = _certification_source(
        tmp_path,
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "mode = sys.argv[1]\n"
        "if mode == 'tracked':\n"
        "    Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\n"
        "elif mode == 'untracked':\n"
        "    Path('untracked.txt').write_text('new\\n', encoding='utf-8')\n"
        "elif mode == 'head':\n"
        "    Path('tracked.txt').write_text('committed\\n', encoding='utf-8')\n"
        "    subprocess.run(['/usr/bin/git', 'add', 'tracked.txt'], check=True)\n"
        "    subprocess.run(['/usr/bin/git', 'commit', '-q', '-m', 'mutate'], check=True)\n"
        "print('gate=mutation status=passed')\n",
    )
    output_root = tmp_path / "gate-output"

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._run_certification_gate(
            {
                "id": "source_mutation",
                "class": "upstream_certified",
                "command": f"python3 gate.py {mutation}",
            },
            source_root=source,
            gate_output_root=output_root,
            source_sha=source_sha,
            timeout=30,
            heartbeat=0.1,
        )

    assert caught.value.code == "changed_certification_source"
    assert not (output_root / "outputs/source_mutation.log").exists()


def test_certification_matrix_mutation_blocks_later_wave_and_authority(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "later-wave-ran"
    source, source_sha = _certification_source(
        tmp_path,
        "from pathlib import Path\n"
        "Path('tracked.txt').write_text('changed\\n', encoding='utf-8')\n"
        "print('gate=mutation status=passed')\n",
    )
    (source / "later.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('ran\\n', encoding='utf-8')\n"
        "print('gate=later status=passed')\n",
        encoding="utf-8",
    )
    source_sha = _commit_all(source, "add dependent gate")
    catalog = [
        {
            "id": "mutating_gate",
            "class": "upstream_certified",
            "command": "python3 gate.py",
        },
        {
            "id": "later_gate",
            "class": "upstream_certified",
            "command": "python3 later.py",
        },
    ]
    package = {
        "migration": {
            "gate_policies": {
                "mutating_gate": {
                    "depends_on": [],
                    "resource_group": "python_first",
                },
                "later_gate": {
                    "depends_on": ["mutating_gate"],
                    "resource_group": "python_second",
                },
            }
        }
    }
    output_root = tmp_path / "gate-output"

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._execute_certification_matrix(
            package=package,
            catalog=catalog,
            source_root=source,
            gate_output_root=output_root,
            source_sha=source_sha,
            jobs=2,
            timeout=30,
            heartbeat=0.1,
        )

    assert caught.value.code == "changed_certification_source"
    assert not sentinel.exists()
    assert not list(tmp_path.rglob("release-capsule.json"))
    assert not list(tmp_path.rglob("execution-attestation.json"))


def _escaped_gate_source() -> str:
    return (
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "pid_path = Path.cwd().parent / f\"escaped-{os.environ['WIKI_UPGRADE_GATE_ID']}.pid\"\n"
        'child = ("import os,time; from pathlib import Path; os.setsid(); "\n'
        "         \"Path(os.environ['ESCAPED_PID']).write_text(str(os.getpid()), encoding='utf-8'); \"\n"
        '         "time.sleep(60)")\n'
        "environment = dict(os.environ)\n"
        "environment['ESCAPED_PID'] = str(pid_path)\n"
        "subprocess.Popen([sys.executable, '-c', child], env=environment)\n"
        "deadline = time.monotonic() + 5\n"
        "while not pid_path.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "if not pid_path.exists():\n"
        "    raise SystemExit(41)\n"
        "print('gate=escaped status=passed')\n"
    )


def _assert_process_absent(pid: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    pytest.fail("escaped descendant survived bounded gate cleanup")


def test_certification_gate_terminates_escaped_descendant(tmp_path: Path) -> None:
    source, source_sha = _certification_source(tmp_path, _escaped_gate_source())
    result = upgrade_runner._run_certification_gate(
        {
            "id": "escaped_certification",
            "class": "upstream_certified",
            "command": "python3 gate.py",
        },
        source_root=source,
        gate_output_root=tmp_path / "gate-output",
        source_sha=source_sha,
        timeout=30,
        heartbeat=0.1,
    )

    pid = int((tmp_path / "escaped-escaped_certification.pid").read_text())
    _assert_process_absent(pid)
    assert result["status"] == "passed"


def test_certification_gate_rejects_oversized_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source, source_sha = _certification_source(tmp_path, "print('x' * 4096)\n")
    monkeypatch.setattr(upgrade_runner, "_MAX_GATE_OUTPUT_BYTES", 64)

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._run_certification_gate(
            {
                "id": "oversized_gate",
                "class": "upstream_certified",
                "command": "python3 gate.py",
            },
            source_root=source,
            gate_output_root=tmp_path / "gate-output",
            source_sha=source_sha,
            timeout=30,
            heartbeat=0.1,
        )

    assert caught.value.code == "oversized_certification_output"
    assert not (tmp_path / "gate-output/outputs/oversized_gate.log").exists()


@pytest.mark.parametrize(
    "unsafe_output",
    [
        "artifact=/tmp/private-proof.json\n",
        "cache=/opt/wiki-viva/cache.json\n",
        "state=/var/folders/session.json\n",
        "store=/nix/store/synthetic-python/bin/python\n",
        "workspace=/workspace/repo/tests/test_public.py\n",
        "runtime=/run/user/501/wiki-viva\n",
        "ci=/__w/wiki-viva-kit/wiki-viva-kit\n",
        "GET /consumer/account/timeline 200\n",
        "https://example.invalid/real/account\n",
        "route=[/real/customer]\n",
        "route,{/consumer/account}\n",
        "[/real]\n",
        "route=%2Freal%2Fcustomer\n",
        "route=%252Fconsumer%252Faccount\n",
        "route=%2525252Freal%2525252Fcustomer\n",
        "https://example.invalid/%72eal/customer\n",
        "artifact=%2Ftmp%2Fprivate-proof.json\n",
    ],
)
def test_public_certification_output_rejects_host_paths_and_private_routes(
    unsafe_output: str,
) -> None:
    with pytest.raises(upgrade_runner.RunnerError, match="private evidence"):
        upgrade_runner._require_public_certification_output(
            unsafe_output.encode("utf-8"), gate_id="synthetic-public-gate"
        )
    for safe_output in (
        b"GET /demo/w/radar 200\n",
        b"docs/real/customer.md\n",
        b"GET /realtime 200\n",
        b"GET /consumer-v2 200\n",
        b"GET %2Fdemo%2Fw%2Fradar 200\n",
        b"docs%2Freal%2Fcustomer.md\n",
    ):
        upgrade_runner._require_public_certification_output(
            safe_output, gate_id="synthetic-public-gate"
        )


def test_published_frontend_and_portable_python_success_output_is_public_safe(
    tmp_path: Path,
) -> None:
    package = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml").read_text(
            encoding="utf-8"
        )
    )
    registry = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml").read_text(
            encoding="utf-8"
        )
    )
    commands = package["migration"]["gate_commands"]
    registered = {item["id"]: item["command"] for item in registry["gate_catalog"]}
    expected = {
        "frontend": (
            "python3 scripts/wiki_node_workspace.py run test -- --reporter=tap"
        ),
        "portable_python": "python3 -m pytest -q -W error tests/",
    }
    assert {gate_id: commands[gate_id] for gate_id in expected} == expected
    assert {gate_id: registered[gate_id] for gate_id in expected} == expected

    python_root = tmp_path / "public-python-fixture"
    (python_root / "tests").mkdir(parents=True)
    (python_root / "tests/test_public_fixture.py").write_text(
        "def test_public_fixture():\n    assert True\n", encoding="utf-8"
    )
    synthetic = _build_synthetic_upgrade(tmp_path / "node-wrapper")
    synthetic_kit = Path(synthetic["kit"])
    wrapper_environment = {
        **os.environ,
        "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY": str(
            synthetic["node_workspace_authority"]
        ),
        "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256": str(
            synthetic["node_workspace_authority_sha256"]
        ),
        "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA": _git(synthetic_kit, "rev-parse", "HEAD"),
    }
    executions = {
        "portable_python": (
            python_root,
            expected["portable_python"],
            dict(os.environ),
        ),
        "frontend": (synthetic_kit, expected["frontend"], wrapper_environment),
    }
    for gate_id, (cwd, command, environment) in executions.items():
        result = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        assert result.returncode == 0, result.stdout.decode("utf-8", "replace")
        upgrade_runner._require_public_certification_output(
            result.stdout, gate_id=gate_id
        )
        assert str(cwd.resolve()).encode("utf-8") not in result.stdout


def test_registered_portable_python_fails_closed_on_path_bearing_warning(
    tmp_path: Path,
) -> None:
    package = yaml.safe_load(
        (ROOT / "docs/references/upgrades/wiki-viva-v8/upgrade-package.yaml").read_text(
            encoding="utf-8"
        )
    )
    command = package["migration"]["gate_commands"]["portable_python"]
    assert command == "python3 -m pytest -q -W error tests/"
    python_root = tmp_path / "warning-python-fixture"
    (python_root / "tests").mkdir(parents=True)
    (python_root / "tests/test_warning_fixture.py").write_text(
        "import warnings\n\n"
        "def test_warning_fixture():\n"
        "    warnings.warn_explicit(\n"
        "        'synthetic runtime warning',\n"
        "        DeprecationWarning,\n"
        "        '/opt/synthetic-python/lib/runtime.py',\n"
        "        66,\n"
        "    )\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        shlex.split(command),
        cwd=python_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert b"/opt/synthetic-python" in result.stdout
    with pytest.raises(
        upgrade_runner.RunnerError, match="host-local or private evidence"
    ):
        upgrade_runner._require_public_certification_output(
            result.stdout, gate_id="portable_python"
        )


def test_certify_rejects_published_gate_output_with_absolute_root() -> None:
    for gate_id in ("frontend", "portable_python"):
        raw = f"status=passed\nroot={ROOT.resolve()}\n".encode("utf-8")
        with pytest.raises(
            upgrade_runner.RunnerError, match="host-local or private evidence"
        ) as caught:
            upgrade_runner._require_public_certification_output(raw, gate_id=gate_id)
        assert "freeze this failed release subject" in caught.value.next_action
        assert "never retry or relabel this subject" in caught.value.next_action


@pytest.mark.parametrize("raw", [b"", b"\xff"])
def test_invalid_certification_output_requires_a_new_release_subject(
    raw: bytes,
) -> None:
    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._require_public_certification_output(
            raw, gate_id="portable_python"
        )
    assert caught.value.lane == "lane_a"
    assert caught.value.surface == "portable_python"
    assert "freeze this failed release subject" in caught.value.next_action
    assert "never retry or relabel this subject" in caught.value.next_action


@pytest.mark.parametrize(
    ("entries", "error_code"),
    [
        (
            [
                {
                    "id": "desktop-bad",
                    "state": "capture-" + ("0" * 64),
                    "path": "images/desktop.png",
                }
            ],
            "invalid_visual_manifest",
        ),
        (
            [
                {
                    "id": "desktop",
                    "state": "hand-authored-state",
                    "path": "images/desktop.png",
                }
            ],
            "invalid_visual_manifest",
        ),
        (
            [
                {
                    "id": "desktop",
                    "state": "capture-" + ("0" * 64),
                    "path": "images/desktop.png",
                },
                {
                    "id": "desktop",
                    "state": "capture-" + ("1" * 64),
                    "path": "images/desktop-copy.png",
                },
            ],
            "duplicate_visual_artifact",
        ),
    ],
)
def test_visual_authority_staging_rejects_invalid_or_duplicate_record_identity(
    tmp_path: Path, entries: list[dict[str, str]], error_code: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "visual-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "wiki_visual_evidence_manifest.v1",
                "entries": entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    destination = tmp_path / "destination"

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._stage_visual_authority(
            source_root=source,
            manifest_ref="visual-manifest.json",
            destination_root=destination,
        )

    assert raised.value.code == error_code
    assert not destination.exists()


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_safe_certification_file_rejects_linked_authority(
    tmp_path: Path, link_kind: str
) -> None:
    root = tmp_path / "authority"
    root.mkdir()
    original = root / "original.json"
    original.write_text('{"status":"trusted"}\n', encoding="utf-8")
    linked = root / "linked.json"
    if link_kind == "symlink":
        linked.symlink_to(original.name)
    else:
        os.link(original, linked)

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._safe_certification_file(
            root, linked.name, label="test authority"
        )

    assert raised.value.code == "unsafe_certification_file"


def test_safe_certification_file_is_pinned_when_path_is_replaced_during_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "authority"
    root.mkdir()
    authority = root / "authority.json"
    replacement = root / "replacement.json"
    displaced = root / "displaced.json"
    trusted = b'{"status":"trusted"}\n'
    authority.write_bytes(trusted)
    replacement.write_bytes(b'{"status":"swapped"}\n')
    original_read = upgrade_runner.os.read
    swapped = False

    def replace_after_open(descriptor: int, size: int) -> bytes:
        nonlocal swapped
        if not swapped:
            authority.replace(displaced)
            replacement.replace(authority)
            swapped = True
        return original_read(descriptor, size)

    monkeypatch.setattr(upgrade_runner.os, "read", replace_after_open)

    relative, raw = upgrade_runner._safe_certification_file(
        root, "authority.json", label="test authority"
    )

    assert relative == "authority.json"
    assert raw == trusted
    assert authority.read_bytes() != raw


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_gate_artifact_collection_rejects_links_before_copy(
    tmp_path: Path, link_kind: str
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/audit"
    artifact_dir.mkdir(parents=True)
    outside = tmp_path / "outside.log"
    outside.write_text("outside evidence\n", encoding="utf-8")
    linked = artifact_dir / "console-linked.log"
    if link_kind == "symlink":
        linked.symlink_to(outside)
    else:
        os.link(outside, linked)

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="audit",
            gate_class="consumer_always",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "unsafe_gate_artifact"
    assert not list((run_dir / "evidence").rglob("*.bin"))


def test_gate_evidence_destination_symlink_is_rejected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/audit"
    artifact_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_dir / "evidence").symlink_to(outside, target_is_directory=True)

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="audit",
            gate_class="consumer_always",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "unsafe_gate_evidence_destination"
    assert not list(outside.iterdir())


@pytest.mark.parametrize("artifact_name", ["console-secret.log", "network-secret.har"])
def test_gate_artifact_secret_is_rejected_before_runner_persistence(
    tmp_path: Path, artifact_name: str
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/audit"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / artifact_name).write_text(
        "api_key=abcdef1234567890\n", encoding="utf-8"
    )

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="audit",
            gate_class="consumer_always",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "secret_gate_evidence"
    assert not list((run_dir / "evidence").rglob("*.bin"))


def test_gate_artifact_collection_is_size_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/audit"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "console-too-large.log").write_bytes(b"x" * 9)
    monkeypatch.setattr(upgrade_runner, "_MAX_GATE_ARTIFACT_FILE_BYTES", 8)

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="audit",
            gate_class="consumer_always",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "unsafe_gate_artifact"
    assert not list((run_dir / "evidence").rglob("*.bin"))


def test_gate_private_path_is_rejected_before_runner_persistence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/audit"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "console-private.log").write_text(
        "root=/Users/example/private-wiki\n", encoding="utf-8"
    )

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="audit",
            gate_class="consumer_always",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "private_gate_evidence"
    assert not list((run_dir / "evidence").rglob("*.bin"))


def _write_canary_visual_artifacts(
    artifact_dir: Path,
    *,
    schema_version: str = "wiki_viva_canary_visual_summary.v2",
    runtime_mode: str | None = "v8",
    profile: str = "desktop",
    route: str = "/w?view=quadrants&tour=0",
    view: str = "quadrants",
    viewport: tuple[int, int] = (1440, 1000),
) -> None:
    artifact_dir.mkdir(parents=True)
    width, height = viewport
    (artifact_dir / "desktop.png").write_bytes(_png_bytes(width, height))
    entry = {
        "profile": profile,
        "artifact": "desktop.png",
        "route": route,
        "view": view,
        "viewport": {"width": width, "height": height},
    }
    if runtime_mode is not None:
        entry["runtime_mode"] = runtime_mode
    (artifact_dir / "visual-evidence-summary.json").write_text(
        json.dumps({"schema_version": schema_version, "entries": [entry]}),
        encoding="utf-8",
    )


def test_gate_visual_summary_preserves_exact_v8_runtime(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/real_canary"
    _write_canary_visual_artifacts(artifact_dir)

    evidence = upgrade_runner._collect_gate_evidence(
        gate_id="real_canary",
        gate_class="canary",
        subject_sha="a" * 40,
        output_sha256="b" * 64,
        artifact_dir=artifact_dir,
        run_dir=run_dir,
    )

    assert evidence["screenshots"][0]["runtime_mode"] == "v8"


def test_gate_visual_summary_rejects_bounded_but_noncanonical_viewport(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/real_canary"
    _write_canary_visual_artifacts(artifact_dir, viewport=(1280, 900))

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="real_canary",
            gate_class="canary",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "invalid_visual_evidence_summary"


@pytest.mark.parametrize(
    ("schema_version", "runtime_mode", "profile", "route", "view"),
    [
        (
            "wiki_viva_canary_visual_summary.v1",
            "v8",
            "desktop",
            "/w?view=quadrants&tour=0",
            "quadrants",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            None,
            "desktop",
            "/w?view=quadrants&tour=0",
            "quadrants",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            "compat",
            "desktop",
            "/w?view=quadrants&tour=0",
            "quadrants",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            "legacy",
            "desktop",
            "/w?view=quadrants&tour=0",
            "quadrants",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            "v8",
            "desktop",
            "/totally-wrong-but-safe",
            "quadrants",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            "v8",
            "desktop",
            "/w?view=quadrants&tour=0",
            "timeline",
        ),
        (
            "wiki_viva_canary_visual_summary.v2",
            "v8",
            "custom_profile",
            "/w?view=quadrants&tour=0",
            "quadrants",
        ),
    ],
)
def test_gate_visual_summary_rejects_stale_or_non_native_observation(
    tmp_path: Path,
    schema_version: str,
    runtime_mode: str | None,
    profile: str,
    route: str,
    view: str,
) -> None:
    run_dir = tmp_path / "run"
    artifact_dir = run_dir / "gate-artifacts/real_canary"
    _write_canary_visual_artifacts(
        artifact_dir,
        schema_version=schema_version,
        runtime_mode=runtime_mode,
        profile=profile,
        route=route,
        view=view,
    )

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._collect_gate_evidence(
            gate_id="real_canary",
            gate_class="canary",
            subject_sha="a" * 40,
            output_sha256="b" * 64,
            artifact_dir=artifact_dir,
            run_dir=run_dir,
        )

    assert raised.value.code == "invalid_visual_evidence_summary"


def test_gate_stdout_secret_is_rejected_before_log_persistence(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / "README.md").write_text("synthetic consumer\n", encoding="utf-8")
    subject_sha = _commit_all(consumer, "initialize synthetic consumer")
    run_dir = consumer / ".wiki-viva/upgrade/runs/test"
    gate = {
        "id": "audit",
        "class": "consumer_always",
        "command": (
            'python3 -c "import sys; '
            "print(''.join(map(chr,[97,112,105,95,107,101,121,61,97,98,99,100,101,102,49,50,51,52,53,54,55,56,57,48])), file=sys.stderr)\""
        ),
    }

    with pytest.raises(upgrade_runner.RunnerError) as raised:
        upgrade_runner._run_gate(
            gate,
            consumer=consumer,
            kit=ROOT,
            run_dir=run_dir,
            subject_sha=subject_sha,
            public_release_sha="b" * 40,
            timeout=30,
            heartbeat=0.1,
            completed_before=0,
            total_count=1,
            run_started_unix_ns=time.time_ns(),
        )

    assert raised.value.code == "secret_gate_evidence"
    assert not (run_dir / "logs/audit.log").exists()


def _consumer_gate_source(tmp_path: Path, source: str) -> tuple[Path, str]:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / ".gitignore").write_text(".wiki-viva/\n", encoding="utf-8")
    (consumer / "README.md").write_text("synthetic consumer\n", encoding="utf-8")
    (consumer / "gate.py").write_text(source, encoding="utf-8")
    return consumer, _commit_all(consumer, "initialize bounded consumer gate")


def test_preflight_terminates_escaped_descendant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    consumer, b0 = _consumer_gate_source(tmp_path, _escaped_gate_source())
    monkeypatch.setattr(
        upgrade_runner,
        "_preflight_commands",
        lambda *_args, **_kwargs: [
            {
                "id": "diff_check",
                "command_id": "diff_check",
                "command": "python3 gate.py",
            }
        ],
    )

    result = upgrade_runner._execute_preflight(
        package={"release": {"source_sha": "b" * 40}},
        explicit_specs=[],
        consumer=consumer,
        kit=consumer,
        b0=b0,
        output_root=consumer / ".wiki-viva/upgrade",
    )

    pid = int((tmp_path / "escaped-diff_check.pid").read_text())
    _assert_process_absent(pid)
    assert result["results"][0]["status"] == "passed"


def test_lane_b_gate_terminates_escaped_descendant(tmp_path: Path) -> None:
    consumer, subject_sha = _consumer_gate_source(tmp_path, _escaped_gate_source())
    result = upgrade_runner._run_gate(
        {
            "id": "audit",
            "class": "consumer_always",
            "command": "python3 gate.py",
        },
        consumer=consumer,
        kit=consumer,
        run_dir=consumer / ".wiki-viva/upgrade/runs/test",
        subject_sha=subject_sha,
        public_release_sha="b" * 40,
        timeout=30,
        heartbeat=0.1,
        completed_before=0,
        total_count=1,
        run_started_unix_ns=time.time_ns(),
    )

    pid = int((tmp_path / "escaped-audit.pid").read_text())
    _assert_process_absent(pid)
    assert result["status"] == "passed"


@pytest.mark.parametrize("surface", ["preflight", "lane_b"])
def test_consumer_gate_output_limit_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, surface: str
) -> None:
    consumer, subject_sha = _consumer_gate_source(tmp_path, "print('x' * 4096)\n")
    monkeypatch.setattr(upgrade_runner, "_MAX_GATE_OUTPUT_BYTES", 64)
    if surface == "preflight":
        monkeypatch.setattr(
            upgrade_runner,
            "_preflight_commands",
            lambda *_args, **_kwargs: [
                {
                    "id": "diff_check",
                    "command_id": "diff_check",
                    "command": "python3 gate.py",
                }
            ],
        )
        with pytest.raises(upgrade_runner.RunnerError) as caught:
            upgrade_runner._execute_preflight(
                package={"release": {"source_sha": "b" * 40}},
                explicit_specs=[],
                consumer=consumer,
                kit=consumer,
                b0=subject_sha,
                output_root=consumer / ".wiki-viva/upgrade",
            )
        assert caught.value.code == "preflight_gate_output_oversized"
        assert not list((consumer / ".wiki-viva/upgrade").rglob("*.log"))
    else:
        with pytest.raises(upgrade_runner.RunnerError) as caught:
            upgrade_runner._run_gate(
                {
                    "id": "audit",
                    "class": "consumer_always",
                    "command": "python3 gate.py",
                },
                consumer=consumer,
                kit=consumer,
                run_dir=consumer / ".wiki-viva/upgrade/runs/test",
                subject_sha=subject_sha,
                public_release_sha="b" * 40,
                timeout=30,
                heartbeat=0.1,
                completed_before=0,
                total_count=1,
                run_started_unix_ns=time.time_ns(),
            )
        assert caught.value.code == "oversized_gate_output"
        assert not (consumer / ".wiki-viva/upgrade/runs/test/logs/audit.log").exists()


def test_preflight_secret_output_is_rejected_before_log_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "print(''.join(map(chr,[97,112,105,95,107,101,121,61,97,98,99,100,101,102,49,50,51,52,53,54,55,56,57,48])))\n"
    consumer, b0 = _consumer_gate_source(tmp_path, source)
    monkeypatch.setattr(
        upgrade_runner,
        "_preflight_commands",
        lambda *_args, **_kwargs: [
            {
                "id": "diff_check",
                "command_id": "diff_check",
                "command": "python3 gate.py",
            }
        ],
    )

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._execute_preflight(
            package={"release": {"source_sha": "b" * 40}},
            explicit_specs=[],
            consumer=consumer,
            kit=consumer,
            b0=b0,
            output_root=consumer / ".wiki-viva/upgrade",
        )

    assert caught.value.code == "secret_gate_evidence"
    assert not list((consumer / ".wiki-viva/upgrade").rglob("*.log"))


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


def _commit_all_deterministic(root: Path, subject: str) -> str:
    _git(root, "add", "-A")
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        }
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", subject],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return _git(root, "rev-parse", "HEAD")


def _acceptance_anchor_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / ".gitignore").write_text(".wiki-viva/\n", encoding="utf-8")
    (consumer / "README.md").write_text("synthetic consumer\n", encoding="utf-8")
    _commit_all(consumer, "initialize acceptance consumer")
    plan_path = consumer / ".wiki-viva/upgrade/plan.json"
    attempt = hashlib.sha256(b"synthetic acceptance attempt").hexdigest()
    return consumer, plan_path, attempt


def test_runner_git_ignores_ambient_executable_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / "README.md").write_text("synthetic\n", encoding="utf-8")
    head = _commit_all(consumer, "initialize Git consumer")
    sentinel = tmp_path / "ambient-git-sentinel"
    executable = tmp_path / "fsmonitor.sh"
    executable.write_text(
        f"#!/bin/sh\ntouch {shlex.quote(str(sentinel))}\nprintf '0\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(executable))

    assert upgrade_runner._head(consumer) == head
    upgrade_runner._require_clean(consumer)
    assert not sentinel.exists()


def test_runner_git_rejects_local_executable_config(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / "README.md").write_text("synthetic\n", encoding="utf-8")
    _commit_all(consumer, "initialize Git consumer")
    sentinel = tmp_path / "local-git-sentinel"
    _git(consumer, "config", "alias.evil", f"!touch {sentinel}")

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._head(consumer)

    assert caught.value.code == "git_contract_failed"
    assert not sentinel.exists()


def test_preplanted_acceptance_anchor_without_digest_fails_unchanged(
    tmp_path: Path,
) -> None:
    consumer, plan_path, attempt = _acceptance_anchor_fixture(tmp_path)
    anchor_path = upgrade_runner._acceptance_anchor_path(plan_path, attempt)
    anchor_path.parent.mkdir(parents=True)
    preplanted = b'{"preplanted":true}\n'
    anchor_path.write_bytes(preplanted)
    before = anchor_path.stat()

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._load_or_create_acceptance_anchor(
            consumer=consumer,
            plan_path=plan_path,
            attempt_identity_sha256=attempt,
            invocation_started_unix_ns=time.time_ns(),
        )

    after = anchor_path.stat()
    assert caught.value.code == "untrusted_acceptance_anchor"
    assert anchor_path.read_bytes() == preplanted
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )


def test_acceptance_anchor_wrong_digest_fails_and_exact_digest_reuses_inode(
    tmp_path: Path,
) -> None:
    consumer, plan_path, attempt = _acceptance_anchor_fixture(tmp_path)
    anchor, trusted = upgrade_runner._load_or_create_acceptance_anchor(
        consumer=consumer,
        plan_path=plan_path,
        attempt_identity_sha256=attempt,
        invocation_started_unix_ns=time.time_ns(),
    )
    anchor_path = upgrade_runner._acceptance_anchor_path(plan_path, attempt)
    original_raw = anchor_path.read_bytes()
    before = anchor_path.stat()

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._load_or_create_acceptance_anchor(
            consumer=consumer,
            plan_path=plan_path,
            attempt_identity_sha256=attempt,
            invocation_started_unix_ns=time.time_ns(),
            trusted_file_sha256="0" * 64,
        )
    assert caught.value.code == "untrusted_acceptance_anchor"

    reused, observed = upgrade_runner._load_or_create_acceptance_anchor(
        consumer=consumer,
        plan_path=plan_path,
        attempt_identity_sha256=attempt,
        invocation_started_unix_ns=time.time_ns(),
        trusted_file_sha256=trusted,
    )
    after = anchor_path.stat()
    assert reused == anchor
    assert observed == trusted
    assert anchor_path.read_bytes() == original_raw
    assert (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_acceptance_anchor_reuse_rejects_linked_file(
    tmp_path: Path, link_kind: str
) -> None:
    consumer, plan_path, attempt = _acceptance_anchor_fixture(tmp_path)
    _anchor, trusted = upgrade_runner._load_or_create_acceptance_anchor(
        consumer=consumer,
        plan_path=plan_path,
        attempt_identity_sha256=attempt,
        invocation_started_unix_ns=time.time_ns(),
    )
    anchor_path = upgrade_runner._acceptance_anchor_path(plan_path, attempt)
    original = anchor_path.with_name("original-anchor.json")
    anchor_path.replace(original)
    if link_kind == "symlink":
        anchor_path.symlink_to(original.name)
    else:
        os.link(original, anchor_path)

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._load_or_create_acceptance_anchor(
            consumer=consumer,
            plan_path=plan_path,
            attempt_identity_sha256=attempt,
            invocation_started_unix_ns=time.time_ns(),
            trusted_file_sha256=trusted,
        )

    assert caught.value.code in {"unsafe_output_symlink", "unsafe_private_evidence"}


def test_atomic_create_once_fails_closed_on_zero_progress_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(upgrade_runner.os, "write", lambda *_args: 0)

    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._atomic_create_once(tmp_path / "evidence.json", b"payload")

    assert caught.value.code == "immutable_evidence_write_failed"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)
    )


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
    payload["schema_version"] = upgrade_runner.RELEASE_CAPSULE_SCHEMA_VERSION
    probe_ref = str(payload.get("toolchain_probe_ref") or "toolchain-probe.json")
    payload["toolchain_probe_ref"] = probe_ref
    probe_entries = []
    for tool_id in ("browser", "node", "npm", "python", "runner"):
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
                "schema_version": upgrade_runner.TOOLCHAIN_PROBE_SCHEMA_VERSION,
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


def _convert_fixture_to_legacy_v1(
    fixture: dict[str, Path | str],
) -> Path:
    """Freeze a public synthetic pre-RT173 v1 authority for CLI verification."""

    package_path = Path(fixture["package"])
    registry_path = Path(fixture["registry"])
    capsule_path = Path(fixture["capsule"])
    authority_path = Path(fixture["authority"])
    package = yaml.safe_load(package_path.read_text(encoding="utf-8"))
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))

    package["portable_import"]["block"].remove("apps/wiki-cockpit/node_modules/**")
    raw_gate_command = "npm --prefix apps/wiki-cockpit run test"
    registry_entry = next(
        item for item in registry["gate_catalog"] if item["id"] == "upstream_check"
    )
    registry_entry["command"] = raw_gate_command
    registry.pop("registry_sha256")
    registry["registry_sha256"] = canonical_sha256(registry)
    migration = package["migration"]
    migration.pop("command_registry", None)
    migration["gate_commands"]["upstream_check"] = raw_gate_command
    migration["command_registry_sha256"] = canonical_sha256(registry["gate_catalog"])
    migration["impact_registry"]["sha256"] = registry["registry_sha256"]
    migration["boundary_operations"]["c2_generators"][0][
        "command"
    ] = "npm --prefix apps/wiki-cockpit run build"
    migration["boundary_operations"]["registry_sha256"] = boundary_operations_sha256(
        migration["boundary_operations"]
    )
    package_path.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )

    package_sha256 = canonical_sha256(package)
    visual_root = Path(fixture["visual_root"])
    manifest_path = visual_root / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        record_path = visual_root / "records" / f"{entry['id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["package_sha256"] = package_sha256
        record_raw = (upgrade_runner.canonical_json(record) + "\n").encode("utf-8")
        record_path.write_bytes(record_raw)
        entry["state"] = f"capture-{hashlib.sha256(record_raw).hexdigest()}"
    manifest_path.write_bytes(
        (upgrade_runner.canonical_json(manifest) + "\n").encode("utf-8")
    )

    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    capsule["schema_version"] = upgrade_runner.LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION
    capsule.pop("node_workspace_authority")
    capsule.pop("node_workspace_authority_sha256")
    capsule["command_registry"] = copy.deepcopy(registry["gate_catalog"])
    capsule["command_registry_sha256"] = canonical_sha256(capsule["command_registry"])
    command_by_id = {item["id"]: item["command"] for item in registry["gate_catalog"]}
    for result in capsule["certified_gates"]:
        result["command_sha256"] = _digest(command_by_id[result["id"]])
    capsule["toolchain"] = {
        "browser": copy.deepcopy(capsule["toolchain"]["browser"]),
        "node": {"name": "node", "version": "22.22.3"},
        "python": {
            "name": "cpython-resolved",
            "version": f"3.12.4+deps.{'1' * 64}",
        },
        "runner": {
            "name": "wiki-upgrade",
            "version": f"1.4.0+payload.{'2' * 64}",
        },
    }
    capsule["toolchain_sha256"] = canonical_sha256(capsule["toolchain"])
    capsule["toolchain_probe_ref"] = "toolchain/probe-manifest-v1.json"
    capsule["attestation_ref"] = "execution-attestation-v1.json"

    gate_output_root = Path(fixture["gate_output_root"])
    probe_entries = []
    for tool_id, identity in sorted(capsule["toolchain"].items()):
        output_ref = f"toolchain/legacy-{tool_id}.log"
        output = f"{identity['name']} {identity['version']}\n".encode("utf-8")
        output_path = gate_output_root / output_ref
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(output)
        probe_entries.append(
            {
                "id": tool_id,
                **identity,
                "provenance": "executed",
                "probe_argv": [tool_id, "--version"],
                "exit_code": 0,
                "output_ref": output_ref,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "output_bytes": len(output),
            }
        )
    (gate_output_root / capsule["toolchain_probe_ref"]).write_text(
        json.dumps(
            {
                "schema_version": LEGACY_TOOLCHAIN_PROBE_SCHEMA_VERSION,
                "run_id": capsule["run_id"],
                "entries": probe_entries,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    evidence = collect_release_attestation(
        capsule,
        package=package,
        impact_registry=registry,
        source_root=Path(fixture["kit"]),
        visual_root=visual_root,
        gate_output_root=gate_output_root,
    )
    for field in (
        "package_sha256",
        "portable_tree_sha256",
        "portable_tree_entry_count",
        "visual_manifest_sha256",
        "visual_manifest_entry_count",
        "command_registry_sha256",
        "toolchain",
        "toolchain_sha256",
        "toolchain_probe_sha256",
        "toolchain_probe_entry_count",
    ):
        capsule[field] = evidence[field]
    output_by_id = {item["id"]: item for item in evidence["gate_outputs"]}
    for result in capsule["certified_gates"]:
        output = output_by_id[result["id"]]
        for field in ("output_ref", "output_sha256", "output_bytes"):
            result[field] = output[field]
    capsule["gate_receipt_sha256"] = canonical_sha256(capsule["certified_gates"])
    attestation_path = gate_output_root / capsule["attestation_ref"]
    attestation_path.write_text(
        json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8"
    )
    trusted = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
    capsule["attestation_sha256"] = trusted
    capsule.pop("capsule_sha256", None)
    capsule["capsule_sha256"] = canonical_sha256(capsule)
    capsule_raw = upgrade_runner._json_bytes(capsule)
    capsule_path.write_bytes(capsule_raw)

    gate_ids = [item["id"] for item in capsule["certified_gates"]]
    receipt = {
        "schema_version": upgrade_runner.CERTIFICATION_RECEIPT_SCHEMA_VERSION,
        "status": "passed",
        "lane": "lane_a",
        "release_id": capsule["release_id"],
        "run_id": capsule["run_id"],
        "source_sha": capsule["source_sha"],
        "package_sha256": capsule["package_sha256"],
        "portable_tree_sha256": capsule["portable_tree_sha256"],
        "command_registry_sha256": capsule["command_registry_sha256"],
        "toolchain_sha256": capsule["toolchain_sha256"],
        "visual_manifest_sha256": capsule["visual_manifest_sha256"],
        "capsule_ref": capsule_path.name,
        "capsule_sha256": capsule["capsule_sha256"],
        "attestation_ref": capsule["attestation_ref"],
        "attestation_sha256": trusted,
        "authority_ref": authority_path.name,
        "certification_gate_ids": gate_ids,
        "upstream_gate_ids": gate_ids,
        "gate_results": capsule["certified_gates"],
        "human_gate_required": True,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    receipt_path = authority_path.parent / "certification-receipt.json"
    receipt_raw = upgrade_runner._json_bytes(receipt)
    receipt_path.write_bytes(receipt_raw)
    trust_path = authority_path.parent / "trusted-attestation-sha256.txt"
    trust_raw = f"{trusted}\n".encode("ascii")
    trust_path.write_bytes(trust_raw)
    authority = {
        "schema_version": "wiki_viva_release_capsule_authority.v1",
        "visual_root": visual_root.relative_to(authority_path.parent).as_posix(),
        "gate_output_root": gate_output_root.relative_to(
            authority_path.parent
        ).as_posix(),
        "release_capsule_ref": capsule_path.name,
        "release_capsule_file_sha256": hashlib.sha256(capsule_raw).hexdigest(),
        "certification_receipt_ref": receipt_path.name,
        "certification_receipt_file_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "trust_anchor_ref": trust_path.name,
        "trust_anchor_file_sha256": hashlib.sha256(trust_raw).hexdigest(),
    }
    authority_path.write_bytes(upgrade_runner._json_bytes(authority))
    fixture["trusted_attestation_sha256"] = trusted
    return authority_path.parent


def _reseal_package(fixture: dict[str, Path | str], package: dict) -> None:
    Path(fixture["package"]).write_text(
        yaml.safe_dump(package, sort_keys=False), encoding="utf-8"
    )
    visual_root = Path(fixture["visual_root"])
    manifest_path = visual_root / "visual-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        record_path = visual_root / "records" / f"{entry['id']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["package_sha256"] = canonical_sha256(package)
        record_raw = (upgrade_runner.canonical_json(record) + "\n").encode("utf-8")
        record_path.write_bytes(record_raw)
        entry["state"] = f"capture-{hashlib.sha256(record_raw).hexdigest()}"
    manifest_path.write_bytes(
        (upgrade_runner.canonical_json(manifest) + "\n").encode("utf-8")
    )
    capsule = json.loads(Path(fixture["capsule"]).read_text(encoding="utf-8"))
    capsule.pop("schema_version", None)
    capsule.pop("capsule_sha256", None)
    capsule, trusted = _seal_authority_capsule(
        package=package,
        registry=yaml.safe_load(Path(fixture["registry"]).read_text(encoding="utf-8")),
        payload=capsule,
        source_root=Path(fixture["kit"]),
        visual_root=visual_root,
        gate_output_root=Path(fixture["gate_output_root"]),
    )
    Path(fixture["capsule"]).write_text(json.dumps(capsule, indent=2), encoding="utf-8")
    fixture["trusted_attestation_sha256"] = trusted


def _replace_synthetic_gate_command(
    fixture: dict[str, Path | str], gate_id: str, command: str
) -> None:
    package = yaml.safe_load(Path(fixture["package"]).read_text(encoding="utf-8"))
    registry = yaml.safe_load(Path(fixture["registry"]).read_text(encoding="utf-8"))
    catalog_entry = next(
        item for item in registry["gate_catalog"] if item["id"] == gate_id
    )
    catalog_entry["command"] = command
    registry.pop("registry_sha256", None)
    registry = seal_impact_registry(registry)
    Path(fixture["registry"]).write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )

    migration = package["migration"]
    migration["gate_commands"][gate_id] = command
    migration["command_registry"][gate_id]["argv"] = ["sh", "-c", command]
    migration["command_registry_sha256"] = canonical_sha256(registry["gate_catalog"])
    migration["impact_registry"]["sha256"] = registry["registry_sha256"]

    capsule_path = Path(fixture["capsule"])
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    capsule["command_registry"] = registry["gate_catalog"]
    capsule_path.write_text(json.dumps(capsule, indent=2), encoding="utf-8")
    _reseal_package(fixture, package)


def _run(
    fixture: dict[str, Path | str],
    *arguments: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = _relocated_runtime_environment()
    environment.pop("WIKI_UPGRADE_RUN_DIR", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=cwd or ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    for line in result.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        digest = payload.get("canary_completion_anchor_sha256")
        if isinstance(digest, str):
            fixture["trusted_canary_completion_anchor_sha256"] = digest
    return result


def _copy_runner_runtime(destination: Path) -> Path:
    (destination / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, destination / "scripts/wiki_upgrade.py")
    shutil.copy2(ROOT / "scripts/_common.py", destination / "scripts/_common.py")
    shutil.copy2(
        ROOT / "scripts/_git_subject.py",
        destination / "scripts/_git_subject.py",
    )
    shutil.copy2(
        ROOT / "scripts/wiki_toolchain_probe.py",
        destination / "scripts/wiki_toolchain_probe.py",
    )
    shutil.copy2(
        ROOT / "scripts/wiki_node_workspace.py",
        destination / "scripts/wiki_node_workspace.py",
    )
    shutil.copytree(
        ROOT / "wiki_core",
        destination / "wiki_core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(
        ROOT / "docs/references/schemas",
        destination / "docs/references/schemas",
    )
    return destination / "scripts/wiki_upgrade.py"


def _relocated_runtime_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    node_bin = ROOT / "apps/wiki-cockpit/node_modules/.bin"
    environment["PATH"] = str(node_bin) + os.pathsep + environment.get("PATH", "")
    return environment


def _plan_args(fixture: dict[str, Path | str]) -> list[str]:
    values = [
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
            'adapt_config::python3 -c "from pathlib import Path; '
            "Path('wiki.config.yaml').write_text('repo_id: synthetic-consumer-v8\\n', "
            "encoding='utf-8')\""
        ),
    ]
    trusted_anchor = fixture.get("trusted_acceptance_anchor_sha256")
    if isinstance(trusted_anchor, str):
        values.extend(["--trusted-acceptance-anchor-sha256", trusted_anchor])
    return values


def _adopt_args(
    fixture: dict[str, Path | str],
    *,
    resume: bool = False,
    pause_before_canary: bool = False,
    pause_before_background: bool = False,
) -> list[str]:
    trusted_acceptance_anchor_sha256 = str(fixture["trusted_acceptance_anchor_sha256"])
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
        "--trusted-acceptance-anchor-sha256",
        trusted_acceptance_anchor_sha256,
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
    completion_digest = fixture.get("trusted_canary_completion_anchor_sha256")
    if isinstance(completion_digest, str):
        values.extend(["--trusted-canary-completion-anchor-sha256", completion_digest])
    return values


def _remember_plan_anchor(
    fixture: dict[str, Path | str], result: subprocess.CompletedProcess[str]
) -> None:
    summaries = [
        json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")
    ]
    summary = next(
        item
        for item in summaries
        if item.get("schema_version") == "wiki_viva_upgrade_plan_summary.v1"
    )
    fixture["trusted_acceptance_anchor_sha256"] = summary["acceptance_anchor_sha256"]


def _certify_args(fixture: dict[str, Path | str], output: Path) -> list[str]:
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
        "--node-workspace-authority",
        str(fixture["node_workspace_authority"]),
        "--trusted-node-workspace-authority-sha256",
        str(fixture["node_workspace_authority_sha256"]),
        "--jobs",
        "4",
        "--heartbeat-seconds",
        "0.1",
    ]


def _verify_capsule_args(
    fixture: dict[str, Path | str], authority_root: Path
) -> list[str]:
    return [
        "verify-capsule",
        "--package",
        str(fixture["package"]),
        "--capsule",
        str(authority_root / "release-capsule.json"),
        "--impact-registry",
        str(fixture["registry"]),
        "--authority",
        str(authority_root / "release-authority.json"),
        "--trusted-attestation-sha256",
        (authority_root / "trusted-attestation-sha256.txt")
        .read_text(encoding="ascii")
        .strip(),
        "--kit-root",
        str(fixture["kit"]),
    ]


def _regular_file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _setup_synthetic_node_workspace(kit: Path) -> None:
    workspace = kit / "apps/wiki-cockpit"
    vendor = workspace / "vendor"
    vendor.mkdir(parents=True)

    def write_archive(path: Path, package_files: Mapping[str, bytes]) -> None:
        tar_raw = BytesIO()
        with tarfile.open(fileobj=tar_raw, mode="w") as bundle:
            for name, raw in sorted(package_files.items()):
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                info.mode = 0o644
                info.mtime = 0
                bundle.addfile(info, BytesIO(raw))
        with path.open("wb") as output:
            with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
                compressed.write(tar_raw.getvalue())

    archive = vendor / "wiki-viva-synthetic-node-dependency-1.0.0.tgz"
    write_archive(
        archive,
        {
            "package/package.json": (
                json.dumps(
                    {
                        "name": "wiki-viva-synthetic-node-dependency",
                        "version": "1.0.0",
                        "main": "index.js",
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
            "package/index.js": b"module.exports = 'synthetic';\n",
        },
    )
    browser_version = _active_toolchain()["browser"]["version"]
    playwright_version, chromium_version = browser_version.split("+chromium.", 1)
    playwright_archive = vendor / "playwright-synthetic.tgz"
    write_archive(
        playwright_archive,
        {
            "package/package.json": (
                json.dumps(
                    {
                        "name": "playwright",
                        "version": playwright_version,
                        "main": "index.js",
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
            "package/index.js": (
                "module.exports={chromium:{launch:async()=>({"
                f"version:()=>{chromium_version!r},close:async()=>{{}}"
                "})}};\n"
            ).encode("utf-8"),
        },
    )
    scripts = {
        name: "node -e \"process.stdout.write('synthetic-node-gate\\n')\" --"
        for name in ALLOWED_SCRIPTS
    }
    scripts["build"] = "node ../../synthetic_fixture/generate-c2.cjs"
    (workspace / "package.json").write_text(
        json.dumps(
            {
                "name": "wiki-viva-synthetic-cockpit",
                "version": "1.0.0",
                "private": True,
                "packageManager": "npm@10.9.8",
                "scripts": scripts,
                "dependencies": {
                    "playwright": "file:vendor/playwright-synthetic.tgz",
                    "wiki-viva-synthetic-node-dependency": (
                        "file:vendor/wiki-viva-synthetic-node-dependency-1.0.0.tgz"
                    ),
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    generated = subprocess.run(
        [
            "npm",
            "--prefix",
            str(workspace),
            "install",
            "--package-lock-only",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
        ],
        cwd=kit,
        env={**os.environ, "NPM_CONFIG_USERCONFIG": os.devnull},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    assert generated.returncode == 0, generated.stderr.decode("utf-8", "replace")
    policy = build_node_workspace_policy(kit)
    (workspace / "node-workspace.lock.json").write_bytes(
        serialize_node_workspace_policy(policy)
    )


def _build_synthetic_upgrade(tmp_path: Path) -> dict[str, Path | str]:
    kit = tmp_path / "public-kit"
    _init_repo(kit)
    (kit / ".gitignore").write_text(
        "apps/wiki-cockpit/node_modules/\n.wiki-viva/\n", encoding="utf-8"
    )
    (kit / "portable.txt").write_text("synthetic portable subject\n", encoding="utf-8")
    shutil.copytree(
        ROOT / "wiki_core",
        kit / "wiki_core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (kit / "synthetic_fixture").mkdir()
    (kit / "synthetic_fixture/portable.py").write_text(
        "PORTABLE = True\n", encoding="utf-8"
    )
    (kit / "synthetic_fixture/generate-c2.cjs").write_text(
        "const fs = require('node:fs');\n"
        "const path = require('node:path');\n"
        "const target = path.resolve(__dirname, "
        "'../docs/references/fixtures/demo-wiki/memories/artifact.txt');\n"
        "fs.mkdirSync(path.dirname(target), { recursive: true });\n"
        "fs.writeFileSync(target, 'generated exactly\\n', 'utf8');\n"
        "process.stdout.write('synthetic-node-c2-generated\\n');\n",
        encoding="utf-8",
    )
    (kit / "synthetic_fixture/synthetic_canary.py").write_text(
        "import json, os, threading\n"
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
        "from pathlib import Path\n"
        "from playwright.sync_api import sync_playwright\n"
        "p=Path(os.environ['WIKI_UPGRADE_GATE_ARTIFACT_DIR'])\n"
        "p.mkdir(parents=True,exist_ok=True)\n"
        "html=b'''<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        "body{margin:0;background:#07111f;color:#dff7ff;font:14px system-ui}"
        "main{padding:20px}h1{font-size:22px}.quadrants{border-left:2px solid #5eead4;"
        "padding-left:12px}</style></head><body><main><h1>Synthetic Living World</h1>"
        '<p>Public reversible canary</p><section class="worldWorkspace" data-world-view="quadrants" data-runtime-mode="v8">'
        '<section class="quadrants" aria-label="Quadrants">'
        "<strong>Quadrants</strong><p>C1 import - C2 regeneration - C3 adapter</p>"
        "</section></section></main></body></html>'''\n"
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
        "  page=browser.new_page(viewport={'width':1440,'height':1000})\n"
        "  page.on('request',lambda request: requests.append(request.method))\n"
        "  page.on('requestfailed',lambda request: request_errors.append(request.method))\n"
        "  page.on('console',lambda message: (console_errors if message.type=='error' else console_warnings if message.type=='warning' else []).append(message.text))\n"
        "  route='/w?view=quadrants&tour=0'; response=page.goto(f'http://127.0.0.1:{server.server_port}{route}',wait_until='networkidle')\n"
        "  if response is None or not response.ok: raise RuntimeError('served canary navigation failed')\n"
        "  page.get_by_role('heading',name='Synthetic Living World').wait_for()\n"
        "  page.get_by_label('Quadrants').wait_for()\n"
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
        "'schema_version':'wiki_viva_canary_visual_summary.v2','entries':[{"
        "'profile':'desktop','artifact':'desktop.png','route':'/w?view=quadrants&tour=0',"
        "'view':'quadrants','runtime_mode':'v8',"
        "'viewport':{'width':1440,'height':1000}}]}))\n"
        "if request_errors or console_errors: raise RuntimeError('served canary evidence observed errors')\n"
        "print('real_served_playwright_canary')\n",
        encoding="utf-8",
    )
    (kit / "scripts").mkdir()
    shutil.copy2(SCRIPT, kit / "scripts/wiki_upgrade.py")
    shutil.copy2(ROOT / "scripts/_common.py", kit / "scripts/_common.py")
    shutil.copy2(ROOT / "scripts/_git_subject.py", kit / "scripts/_git_subject.py")
    shutil.copy2(
        ROOT / "scripts/wiki_toolchain_probe.py",
        kit / "scripts/wiki_toolchain_probe.py",
    )
    shutil.copy2(
        ROOT / "scripts/wiki_node_workspace.py",
        kit / "scripts/wiki_node_workspace.py",
    )
    shutil.copytree(
        ROOT / "docs/references/schemas",
        kit / "docs/references/schemas",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (kit / "scripts/wiki_generate_synthetic.py").write_text(
        "from pathlib import Path\n"
        "p=Path('docs/references/fixtures/demo-wiki/memories/artifact.txt')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "p.write_text('generated exactly\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _setup_synthetic_node_workspace(kit)
    source_sha = _commit_all_deterministic(kit, "synthetic portable release")
    node_authority_path = tmp_path / "node-workspace-authority.json"
    cached_source = _SYNTHETIC_NODE_CACHE.get("source_sha")
    cached_tree = _SYNTHETIC_NODE_CACHE.get("node_modules")
    cached_authority = _SYNTHETIC_NODE_CACHE.get("authority_raw")
    if (
        cached_source == source_sha
        and isinstance(cached_tree, Path)
        and cached_tree.is_dir()
        and isinstance(cached_authority, bytes)
    ):
        shutil.copytree(
            cached_tree,
            kit / "apps/wiki-cockpit/node_modules",
            symlinks=True,
        )
        node_authority_path.write_bytes(cached_authority)
        capture_receipt = {
            "authority_sha256": node_authority_identity_sha256(
                load_node_workspace_authority(node_authority_path)
            )
        }
    else:
        capture_receipt = capture_node_workspace_authority(
            kit,
            node_authority_path,
            source_sha=source_sha,
        )
        _SYNTHETIC_NODE_CACHE.update(
            {
                "source_sha": source_sha,
                "node_modules": kit / "apps/wiki-cockpit/node_modules",
                "authority_raw": node_authority_path.read_bytes(),
            }
        )
    node_workspace_authority = load_node_workspace_authority(node_authority_path)
    node_workspace_authority_sha256 = node_authority_identity_sha256(
        node_workspace_authority
    )
    assert capture_receipt["authority_sha256"] == node_workspace_authority_sha256

    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / ".gitignore").write_text(
        ".wiki-viva/\napps/wiki-cockpit/node_modules/\n", encoding="utf-8"
    )
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
            command = "python3 synthetic_fixture/synthetic_canary.py"
        else:
            command = f"python3 -c \"print('{gate_id}')\""
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
                    "configured_path_roles": [
                        "command_reference_page",
                        "operational_pass_page",
                        "release_records",
                    ],
                    "contracts": [
                        "wiki_config.v1",
                        "wiki_consumer_command_reference.v1",
                        "wiki_consumer_operational_pass.v1",
                        "wiki_consumer_release_record.v1",
                    ],
                    "gates": ["affected_check"],
                    "depends_on": [],
                },
                {
                    "id": "content_semantics",
                    "lane": "lane_b",
                    "path_patterns": ["memories/**"],
                    "contracts": ["wiki_content.v1"],
                    "gates": [
                        "input_stage",
                        "operational_pass",
                        "semantic_inventory",
                        "snapshot_contract",
                    ],
                    "depends_on": ["consumer_configuration"],
                },
                {
                    "id": "portable_core",
                    "lane": "lane_a",
                    "path_patterns": ["synthetic_fixture/**"],
                    "contracts": ["wiki_core.v1"],
                    "gates": ["upstream_check"],
                    "depends_on": [],
                },
            ],
            "boundary_policy": {
                "c1_portable_patterns": [
                    "wiki_core/**",
                    "synthetic_fixture/portable.py",
                    "synthetic_fixture/generate-c2.cjs",
                    "synthetic_fixture/synthetic_canary.py",
                    "scripts/wiki_generate_synthetic.py",
                    "scripts/wiki_upgrade.py",
                    "scripts/_common.py",
                    "scripts/_git_subject.py",
                    "scripts/wiki_toolchain_probe.py",
                    "scripts/wiki_node_workspace.py",
                    "apps/wiki-cockpit/package.json",
                    "apps/wiki-cockpit/package-lock.json",
                    "apps/wiki-cockpit/node-workspace.lock.json",
                    "apps/wiki-cockpit/vendor/playwright-synthetic.tgz",
                    "apps/wiki-cockpit/vendor/wiki-viva-synthetic-node-dependency-1.0.0.tgz",
                ],
                "c2_generated_patterns": [
                    "docs/references/fixtures/demo-wiki/memories/**"
                ],
                "c3_consumer_patterns": ["wiki.config.yaml"],
                "configured_c3_roles": [
                    "command_reference_page",
                    "operational_pass_page",
                    "release_records",
                ],
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
                "python_browser_private"
                if gate_class == "canary"
                else (
                    "python_test"
                    if gate_class == "background_certification"
                    else f"gate_{gate_id.replace('.', '_').replace('-', '_')}"
                )
            ),
            "required_for_promotion": True,
        }
    c2_command = "python3 scripts/wiki_node_workspace.py run build"
    boundary_operations = {
        "schema_version": "wiki_viva_upgrade_boundary_operations.v2",
        "c2_generators": [
            {
                "id": "generate_fixture",
                "command": c2_command,
                "owns_patterns": ["docs/references/fixtures/demo-wiki/memories/**"],
            }
        ],
        "c3_adapter": {
            "mode": "consumer_plan_commands",
            "contract": "wiki_consumer_adaptation_plan.v2",
            "owns_patterns": ["wiki.config.yaml"],
            "configured_ownership": {
                "schema_version": "wiki_viva_config_bound_c3_policy.v1",
                "config_path": "wiki.config.yaml",
                "roles": [dict(item) for item in CONFIG_BOUND_C3_ROLE_SPECS],
            },
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
            "consumer_c3_authority": "wiki_viva_upgrade_consumer_c3_authority.v1",
        },
        "portable_import": {
            "allow": [
                "wiki_core/**",
                "synthetic_fixture/portable.py",
                "synthetic_fixture/generate-c2.cjs",
                "synthetic_fixture/synthetic_canary.py",
                "scripts/wiki_generate_synthetic.py",
                "scripts/wiki_upgrade.py",
                "scripts/_common.py",
                "scripts/_git_subject.py",
                "scripts/wiki_toolchain_probe.py",
                "scripts/wiki_node_workspace.py",
                "apps/wiki-cockpit/package.json",
                "apps/wiki-cockpit/package-lock.json",
                "apps/wiki-cockpit/node-workspace.lock.json",
                "apps/wiki-cockpit/vendor/playwright-synthetic.tgz",
                "apps/wiki-cockpit/vendor/wiki-viva-synthetic-node-dependency-1.0.0.tgz",
            ],
            "block": [
                "apps/wiki-cockpit/node_modules/**",
                "docs/references/fixtures/demo-wiki/memories/**",
                "memories/**",
            ],
        },
        "preflight": {
            "branch_prefix": "wiki/",
            "required_gates": ["diff_check"],
            "gate_mapping": {"diff_check": "diff_check"},
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
                    "argv": shlex.split(command),
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
            "acceptance_budget": {
                "schema_version": "wiki_viva_upgrade_acceptance_budget_policy.v1",
                "scope": "plan_to_real_canary",
                "limit_seconds": 1200,
                "enforcement": "promotion_blocking",
            },
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
    image_ref = "images/desktop.png"
    image_path = visual_root / image_ref
    image_path.parent.mkdir(parents=True)
    image_raw = _png_bytes(1440, 1000)
    image_path.write_bytes(image_raw)
    image_sha256 = hashlib.sha256(image_raw).hexdigest()
    route = VISUAL_PROFILE_CONTRACTS["desktop"]["route"]
    viewport = {"width": 1440, "height": 1000}
    browser_toolchain = copy.deepcopy(_active_toolchain()["browser"])
    record = {
        "schema_version": "wiki_visual_evidence_capture.v2",
        "profile": "desktop",
        "source_sha": source_sha,
        "package_sha256": canonical_sha256(package),
        "requested_route": route,
        "route": route,
        "viewport": viewport,
        "view": "quadrants",
        "runtime_mode": "v8",
        "browser_toolchain": browser_toolchain,
        "browser_toolchain_sha256": canonical_sha256(browser_toolchain),
        "image": {
            "path": image_ref,
            "sha256": image_sha256,
            "bytes": len(image_raw),
            "dimensions": viewport,
        },
        "console_summary": {
            "capture": "sanitized_counts_only",
            "warning_count": 0,
            "error_count": 0,
            "page_error_count": 0,
            "truncated": False,
        },
        "network_summary": {
            "capture": "sanitized_counts_only",
            "request_count": 1,
            "response_error_count": 0,
            "request_failed_count": 0,
            "truncated": False,
        },
        "capture": {
            "method": "playwright_served_public_synthetic",
            "action_count": 0,
            "state": "webgl",
            "settled": True,
        },
    }
    record_raw = (upgrade_runner.canonical_json(record) + "\n").encode("utf-8")
    record_path = visual_root / "records/desktop.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_bytes(record_raw)
    manifest = {
        "schema_version": "wiki_visual_evidence_manifest.v1",
        "entries": [
            {
                "id": "desktop",
                "path": image_ref,
                "sha256": image_sha256,
                "bytes": len(image_raw),
                "route": route,
                "browser": "chromium",
                "viewport": viewport,
                "capture_dimensions": viewport,
                "state": f"capture-{hashlib.sha256(record_raw).hexdigest()}",
                "public_synthetic": True,
            }
        ],
    }
    (visual_root / "visual-manifest.json").write_bytes(
        (upgrade_runner.canonical_json(manifest) + "\n").encode("utf-8")
    )
    gate_output_root = authority_base / "gate-output"
    (gate_output_root / "outputs").mkdir(parents=True)
    for gate in certified:
        (gate_output_root / gate["output_ref"]).write_text(
            f"gate={gate['id']}\nstatus=passed\n", encoding="utf-8"
        )
    capsule_toolchain = copy.deepcopy(_active_toolchain())
    capsule_toolchain["npm"] = npm_workspace_toolchain_identity(
        node_workspace_authority
    )
    capsule_payload = {
        "release_id": "wiki-viva-v8-public-synthetic",
        "status": "certified",
        "source_sha": source_sha,
        "package_sha256": "0" * 64,
        "portable_tree_sha256": "0" * 64,
        "command_registry": gate_catalog,
        "toolchain": capsule_toolchain,
        "node_workspace_authority": node_workspace_authority,
        "node_workspace_authority_sha256": node_workspace_authority_sha256,
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
    registry_path.write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )
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
        "node_workspace_authority": node_authority_path,
        "node_workspace_authority_sha256": node_workspace_authority_sha256,
        "plan": consumer / ".wiki-viva/upgrade/plan.json",
    }


def test_fresh_clean_c1_executes_real_node_c2_generator_via_wrapper(
    tmp_path: Path,
) -> None:
    fixture = _build_synthetic_upgrade(tmp_path / "synthetic-node-c2")
    kit = Path(fixture["kit"])
    package = yaml.safe_load(Path(fixture["package"]).read_text(encoding="utf-8"))
    source_sha = package["release"]["source_sha"]
    generator = package["migration"]["boundary_operations"]["c2_generators"][0]
    assert generator["command"] == ("python3 scripts/wiki_node_workspace.py run build")

    c1 = tmp_path / "fresh-c1"
    c1.mkdir()
    entries = upgrade_runner._portable_entries(package, kit, source_sha)
    assert "apps/wiki-cockpit/node_modules" not in entries
    assert not any("/node_modules/" in path for path in entries)
    for relative, entry in entries.items():
        destination = c1 / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry["bytes"])
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)

    node_modules = c1 / "apps/wiki-cockpit/node_modules"
    generated = c1 / "docs/references/fixtures/demo-wiki/memories/artifact.txt"
    assert not node_modules.exists()
    assert not generated.exists()

    environment = {
        **os.environ,
        "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY": str(fixture["node_workspace_authority"]),
        "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256": str(
            fixture["node_workspace_authority_sha256"]
        ),
        "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA": source_sha,
    }
    result = subprocess.run(
        upgrade_runner._parse_command(generator["command"], kit_root=c1),
        cwd=c1,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout.decode("utf-8", "replace")
    assert node_modules.is_dir()
    assert generated.read_text(encoding="utf-8") == "generated exactly\n"
    assert b"synthetic-node-c2-generated" in result.stdout
    assert b'"script":"build"' in result.stdout
    assert b'"status":"passed"' in result.stdout


@pytest.fixture
def synthetic_upgrade(tmp_path: Path) -> dict[str, Path | str]:
    return _build_synthetic_upgrade(tmp_path)


@pytest.fixture(scope="module")
def sealed_upgrade(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Path | str], Path]:
    fixture = _build_synthetic_upgrade(tmp_path_factory.mktemp("sealed-public-upgrade"))
    output = Path(fixture["package"]).parent / "lane-a-certified"
    result = _run(fixture, *_certify_args(fixture, output))
    assert result.returncode == 0, result.stdout + result.stderr
    return fixture, output


def _localize_consumer_b0(fixture: dict[str, Path | str]) -> str:
    consumer = Path(fixture["consumer"])
    config = (
        "repo_id: synthetic-consumer\n"
        "paths:\n"
        "  memory_root: memorias\n"
        "  references_root: docs/referencias\n"
        "  command_reference_page: memorias/sistema/wiki/comandos.md\n"
        "  operational_pass_page: memorias/passagem-operacional.md\n"
    )
    (consumer / "wiki.config.yaml").write_text(config, encoding="utf-8")
    _git(consumer, "add", "wiki.config.yaml")
    _git(consumer, "commit", "-q", "--amend", "--no-edit")
    consumer_b0 = _git(consumer, "rev-parse", "HEAD")
    fixture["consumer_b0"] = consumer_b0
    return consumer_b0


def _localized_c3_adapter_spec() -> str:
    config = (
        "repo_id: synthetic-consumer-v8\n"
        "paths:\n"
        "  memory_root: memorias\n"
        "  references_root: docs/referencias\n"
        "  command_reference_page: memorias/sistema/wiki/comandos.md\n"
        "  operational_pass_page: memorias/passagem-operacional.md\n"
    )
    code = (
        "from pathlib import Path; "
        "command=Path('memorias/sistema/wiki/comandos.md'); "
        "command.parent.mkdir(parents=True,exist_ok=True); "
        "command.write_text('# Comandos sinteticos\\n',encoding='utf-8'); "
        "release=Path('docs/referencias/releases/rc-sintetico.md'); "
        "release.parent.mkdir(parents=True,exist_ok=True); "
        "release.write_text('# Release sintetica\\n',encoding='utf-8'); "
        f"Path('wiki.config.yaml').write_text({config!r},encoding='utf-8')"
    )
    return f"adapt_localized::{sys.executable} -c {json.dumps(code)}"


def _create_plan(
    fixture: dict[str, Path | str], changed_path: str = "wiki.config.yaml"
) -> dict:
    result = _run(fixture, *_plan_args(fixture), "--changed-path", changed_path)
    assert result.returncode == 0, result.stdout + result.stderr
    _remember_plan_anchor(fixture, result)
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
        Path(fixture["consumer"]) / ".wiki-viva/upgrade/runs" / plan["plan_sha256"][:16]
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
        next(
            Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
        ).read_text(encoding="utf-8")
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


def test_resume_rejects_execution_plan_that_omits_anchored_impact_input(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
        "--changed-contract",
        "wiki_config.v1",
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    _remember_plan_anchor(synthetic_upgrade, planned)
    paused = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    execution_path = next(
        Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
    )
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    original_execution_sha256 = execution["plan_sha256"]
    assert execution["impact_inputs"]["changed_contracts"] == ["wiki_config.v1"]
    execution["impact_inputs"]["changed_contracts"] = []
    execution["conceptual_diff"]["changed_contract_count"] = 0
    execution["plan_sha256"] = upgrade_runner._plan_digest(execution)
    execution_path.write_text(
        json.dumps(execution, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    original_run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / original_execution_sha256[:16]
    )
    state_path = original_run_dir / "state.json"
    state_before = state_path.read_bytes()

    rejected = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )
    assert rejected.returncode == 2
    assert '"error_code": "stale_execution_plan_lineage"' in rejected.stdout
    assert state_path.read_bytes() == state_before


def test_ci_fast_adoption_handoff_is_resumable_runner_state(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    destination_value = os.environ.get("WIKI_UPGRADE_CI_HANDOFF")
    if not destination_value:
        pytest.skip("CI handoff export is only enabled by the two-lane workflow")
    lane_a_value = os.environ.get("WIKI_UPGRADE_CI_LANE_A")
    if not lane_a_value:
        pytest.fail("CI fast adoption must consume the upstream Lane A bundle")
    lane_a_root = Path(lane_a_value).resolve()
    bundle_manifest = json.loads(
        (lane_a_root / "bundle-manifest.json").read_text(encoding="utf-8")
    )
    certified_root = lane_a_root / "certified"
    inputs_root = lane_a_root / "inputs"
    synthetic_upgrade = {
        **synthetic_upgrade,
        "kit": inputs_root / "public-kit",
        "package": inputs_root / "upgrade-package.yaml",
        "registry": inputs_root / "impact-registry.yaml",
        "capsule": certified_root / "release-capsule.json",
        "authority": certified_root / "release-authority.json",
        "trusted_attestation_sha256": (
            certified_root / "trusted-attestation-sha256.txt"
        )
        .read_text(encoding="ascii")
        .strip(),
    }
    capsule = json.loads(Path(synthetic_upgrade["capsule"]).read_text(encoding="utf-8"))
    assert capsule["capsule_sha256"] == bundle_manifest["capsule_sha256"]
    assert capsule["source_sha"] == bundle_manifest["source_sha"]
    assert capsule["package_sha256"] == bundle_manifest["package_sha256"]
    preplan = _create_plan(synthetic_upgrade)
    fast = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert fast.returncode == 0, fast.stdout + fast.stderr
    assert '"status": "paused_before_canary"' in fast.stdout
    execution_paths = sorted(
        Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
    )
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
    shutil.copytree(inputs_root, destination, symlinks=True)
    shutil.copytree(certified_root, destination, symlinks=True, dirs_exist_ok=True)
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
        "source_sha": bundle_manifest["source_sha"],
        "capsule_sha256": bundle_manifest["capsule_sha256"],
        "package_sha256": bundle_manifest["package_sha256"],
        "impact_registry_sha256": bundle_manifest["impact_registry_sha256"],
        "certification_receipt_sha256": bundle_manifest["certification_receipt_sha256"],
        "trusted_attestation_sha256": bundle_manifest["trusted_attestation_sha256"],
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
        "visual/records/desktop.json",
    }
    assert all((output / relative).is_file() for relative in required)
    capsule = json.loads((output / "release-capsule.json").read_text(encoding="utf-8"))
    probe_manifest = json.loads(
        (output / "gate-output/toolchain/probe-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = json.loads(
        (output / "certification-receipt.json").read_text(encoding="utf-8")
    )
    authority = json.loads(
        (output / "release-authority.json").read_text(encoding="utf-8")
    )
    assert [item["id"] for item in capsule["certified_gates"]] == ["upstream_check"]
    assert ".workspace." in capsule["toolchain"]["npm"]["version"]
    browser_probe = next(
        item for item in probe_manifest["entries"] if item["id"] == "browser"
    )
    assert browser_probe["probe_argv"][0] == "node"
    assert not any(
        upgrade_runner._HOST_PATH_RE.search(argument)
        for argument in browser_probe["probe_argv"]
    )
    assert receipt["upstream_gate_ids"] == ["upstream_check"]
    assert receipt["certification_gate_ids"] == ["upstream_check"]
    assert "background_gate_ids" not in receipt
    assert {item["class"] for item in receipt["gate_results"]} == {"upstream_certified"}
    assert receipt["human_gate_required"] is True
    assert authority["certification_receipt_ref"] == "certification-receipt.json"
    assert authority["release_capsule_ref"] == "release-capsule.json"
    assert (output / "visual/records/desktop.json").read_bytes() == (
        Path(synthetic_upgrade["visual_root"]) / "records/desktop.json"
    ).read_bytes()
    assert (output / "gate-output/outputs/upstream_check.log").is_file()
    assert not (output / "gate-output/outputs/background_suite.log").exists()

    plan_args = _plan_args(synthetic_upgrade)
    plan_args[plan_args.index("--capsule") + 1] = str(output / "release-capsule.json")
    plan_args[plan_args.index("--authority") + 1] = str(
        output / "release-authority.json"
    )
    plan_args[plan_args.index("--trusted-attestation-sha256") + 1] = (
        (output / "trusted-attestation-sha256.txt").read_text(encoding="ascii").strip()
    )
    planned = _run(synthetic_upgrade, *plan_args, "--changed-path", "wiki.config.yaml")
    assert planned.returncode == 0, planned.stdout + planned.stderr

    upstream_log = output / "gate-output/outputs/upstream_check.log"
    upstream_log.write_text("fabricated replacement\n", encoding="utf-8")
    rejected = _run(synthetic_upgrade, *plan_args, "--changed-path", "wiki.config.yaml")
    assert rejected.returncode == 2
    assert '"error_code": "stale_certification_gate_output"' in rejected.stdout
    assert str(output) not in rejected.stdout


def test_verify_capsule_recomputes_exact_sealed_authority_read_only_and_path_free(
    sealed_upgrade: tuple[dict[str, Path | str], Path],
) -> None:
    fixture, authority_root = sealed_upgrade
    source_root = Path(fixture["kit"])
    authority_before = _regular_file_hashes(authority_root)
    source_before = _regular_file_hashes(source_root)
    input_before = {
        key: Path(fixture[key]).read_bytes() for key in ("package", "registry")
    }

    result = _run(fixture, *_verify_capsule_args(fixture, authority_root))

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert set(summary) == {
        "schema_version",
        "status",
        "lane",
        "release_id",
        "source_sha",
        "capsule_sha256",
        "package_sha256",
        "portable_tree_sha256",
        "command_registry_sha256",
        "impact_registry_sha256",
        "toolchain_sha256",
        "visual_manifest_sha256",
        "attestation_sha256",
        "human_gate_required",
    }
    assert summary["schema_version"] == (
        "wiki_viva_release_capsule_verification_summary.v1"
    )
    assert summary["status"] == "verified"
    assert summary["lane"] == "lane_a"
    assert summary["human_gate_required"] is True
    capsule = json.loads(
        (authority_root / "release-capsule.json").read_text(encoding="utf-8")
    )
    assert summary["capsule_sha256"] == capsule["capsule_sha256"]
    assert summary["attestation_sha256"] == capsule["attestation_sha256"]
    assert not any(key.endswith("_ref") for key in summary)
    combined = result.stdout + result.stderr
    for path in (source_root, authority_root, Path(fixture["package"]).parent):
        assert str(path.resolve()) not in combined
    upgrade_runner._require_public_certification_output(
        result.stdout.encode("utf-8"), gate_id="verify-capsule"
    )
    assert _regular_file_hashes(authority_root) == authority_before
    assert _regular_file_hashes(source_root) == source_before
    assert {
        key: Path(fixture[key]).read_bytes() for key in ("package", "registry")
    } == input_before


def test_verify_capsule_accepts_legacy_v1_as_immutable_history_only(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    authority_root = _convert_fixture_to_legacy_v1(synthetic_upgrade)
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    capsule = json.loads(
        (authority_root / "release-capsule.json").read_text(encoding="utf-8")
    )
    assert (
        "apps/wiki-cockpit/node_modules/**" not in package["portable_import"]["block"]
    )
    assert package["migration"]["gate_commands"]["upstream_check"].startswith(
        "npm --prefix "
    )
    assert package["migration"]["boundary_operations"]["c2_generators"][0][
        "command"
    ].startswith("npm --prefix ")
    assert capsule["schema_version"] == (
        upgrade_runner.LEGACY_RELEASE_CAPSULE_SCHEMA_VERSION
    )
    assert set(capsule["toolchain"]) == {"browser", "node", "python", "runner"}
    assert "node_workspace_authority" not in capsule

    result = _run(
        synthetic_upgrade,
        *_verify_capsule_args(synthetic_upgrade, authority_root),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["status"] == "verified"
    assert summary["capsule_sha256"] == capsule["capsule_sha256"]
    assert summary["toolchain_sha256"] == capsule["toolchain_sha256"]


def test_legacy_v1_cannot_plan_adopt_resume_or_certify(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    _convert_fixture_to_legacy_v1(synthetic_upgrade)

    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
    )
    assert planned.returncode == 2
    assert '"error_code": "legacy_capsule_verification_only"' in planned.stdout

    plan_path = Path(synthetic_upgrade["plan"])
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("{}\n", encoding="utf-8")
    synthetic_upgrade["trusted_acceptance_anchor_sha256"] = "0" * 64
    for resume in (False, True):
        adopted = _run(
            synthetic_upgrade,
            *_adopt_args(synthetic_upgrade, resume=resume),
        )
        assert adopted.returncode == 2
        assert '"error_code": "legacy_capsule_verification_only"' in adopted.stdout

    output = tmp_path / "legacy-must-not-certify"
    certified = _run(
        synthetic_upgrade,
        *_certify_args(synthetic_upgrade, output),
    )
    assert certified.returncode == 2
    assert '"error_code": "invalid_upgrade_package"' in certified.stdout
    assert not output.exists()


def test_verify_capsule_rejects_tampered_authority_without_leaking_paths(
    sealed_upgrade: tuple[dict[str, Path | str], Path], tmp_path: Path
) -> None:
    fixture, authority_root = sealed_upgrade
    tampered = tmp_path / "tampered-authority"
    shutil.copytree(authority_root, tampered)
    (tampered / "gate-output/outputs/upstream_check.log").write_text(
        "fabricated replacement\n", encoding="utf-8"
    )

    result = _run(fixture, *_verify_capsule_args(fixture, tampered))

    assert result.returncode == 2
    assert '"error_code": "stale_certification_gate_output"' in result.stdout
    assert str(tampered.resolve()) not in result.stdout + result.stderr
    upgrade_runner._require_public_certification_output(
        result.stdout.encode("utf-8"), gate_id="verify-capsule-rejection"
    )


def test_verify_capsule_rejects_divergent_trust_and_unsealed_authority(
    sealed_upgrade: tuple[dict[str, Path | str], Path],
) -> None:
    fixture, authority_root = sealed_upgrade
    arguments = _verify_capsule_args(fixture, authority_root)
    arguments[arguments.index("--trusted-attestation-sha256") + 1] = "0" * 64
    wrong_trust = _run(fixture, *arguments)
    assert wrong_trust.returncode == 2
    assert '"error_code": "lane_contract_rejected"' in wrong_trust.stdout

    arguments = _verify_capsule_args(fixture, authority_root)
    arguments[arguments.index("--authority") + 1] = str(fixture["authority"])
    unsealed = _run(fixture, *arguments)
    assert unsealed.returncode == 2
    assert '"error_code": "lane_contract_rejected"' in unsealed.stdout

    combined = (
        wrong_trust.stdout + wrong_trust.stderr + unsealed.stdout + unsealed.stderr
    )
    for path in (authority_root, Path(fixture["authority"]), Path(fixture["kit"])):
        assert str(path.resolve()) not in combined


def test_verify_capsule_rejects_validation_pending_before_authority_use(
    sealed_upgrade: tuple[dict[str, Path | str], Path], tmp_path: Path
) -> None:
    fixture, authority_root = sealed_upgrade
    package = yaml.safe_load(Path(fixture["package"]).read_text(encoding="utf-8"))
    package["release"]["status"] = "validation_pending"
    pending = tmp_path / "validation-pending.yaml"
    pending.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    arguments = _verify_capsule_args(fixture, authority_root)
    arguments[arguments.index("--package") + 1] = str(pending)

    result = _run(fixture, *arguments)

    assert result.returncode == 2
    assert '"error_code": "release_not_releasable"' in result.stdout
    assert str(pending.resolve()) not in result.stdout + result.stderr


def test_verify_capsule_rejects_path_bearing_authority_without_echoing_it(
    sealed_upgrade: tuple[dict[str, Path | str], Path], tmp_path: Path
) -> None:
    fixture, authority_root = sealed_upgrade
    unsafe = tmp_path / "path-bearing-authority"
    shutil.copytree(authority_root, unsafe)
    authority_path = unsafe / "release-authority.json"
    authority = json.loads(authority_path.read_text(encoding="utf-8"))
    authority["visual_root"] = str(tmp_path.resolve())
    authority_path.write_text(
        json.dumps(authority, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _run(fixture, *_verify_capsule_args(fixture, unsafe))

    assert result.returncode == 2
    assert '"error_code": "lane_contract_rejected"' in result.stdout
    assert str(tmp_path.resolve()) not in result.stdout + result.stderr


def test_certify_refuses_validation_pending_without_creating_authority(
    synthetic_upgrade: dict[str, Path | str], tmp_path: Path
) -> None:
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
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
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    package["schema_version"] = "wiki_viva_upgrade_package.v2"
    legacy = tmp_path / "legacy-package.yaml"
    legacy.write_text(yaml.safe_dump(package, sort_keys=False), encoding="utf-8")
    args = _plan_args({**synthetic_upgrade, "package": legacy})
    result = _run(synthetic_upgrade, *args, "--changed-path", "wiki.config.yaml")
    assert result.returncode == 2
    assert '"error_code": "legacy_package_requires_original_runbook"' in result.stdout
    assert "migration.required_gates" in result.stdout


def test_plan_preflight_accepts_legacy_b0_with_prospective_portable_drift(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    portable_paths = package["portable_import"]["allow"]
    assert portable_paths
    assert all(not (consumer / relative).exists() for relative in portable_paths)

    package["preflight"] = {
        "branch_prefix": "wiki/",
        "required_gates": ["diff_check"],
        "gate_mapping": {"diff_check": "diff_check"},
    }
    _reseal_package(synthetic_upgrade, package)

    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
    )

    assert planned.returncode == 0, planned.stdout + planned.stderr
    _remember_plan_anchor(synthetic_upgrade, planned)
    plan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))
    assert len(plan["preflight"]["results"]) == 1
    assert plan["preflight"]["results"][0]["id"] == "diff_check"
    assert plan["preflight"]["results"][0]["command_id"] == "diff_check"
    assert plan["mutation"]["c1_prospective_paths"]
    prospective_paths = set(plan["mutation"]["c1_prospective_paths"])
    for pattern in portable_paths:
        if any(character in pattern for character in "*?["):
            assert any(
                upgrade_runner._matches_repo_patterns(path, [pattern])
                for path in prospective_paths
            )
        else:
            assert pattern in prospective_paths
    assert "semantic_inventory" in plan["selection"]["selected_gates"]


def test_custom_ignored_plan_root_owns_all_adoption_state_and_evidence(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    (consumer / ".gitignore").write_text(
        "output/upgrade/\napps/wiki-cockpit/node_modules/\n",
        encoding="utf-8",
    )
    _git(consumer, "add", ".gitignore")
    _git(consumer, "commit", "-q", "--amend", "--no-edit")
    synthetic_upgrade["consumer_b0"] = _git(consumer, "rev-parse", "HEAD")
    plan_root = consumer / "output/upgrade"
    synthetic_upgrade["plan"] = plan_root / "plan.json"

    assert _git(consumer, "check-ignore", "-q", "output/upgrade/plan.json") == ""
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", ".wiki-viva/upgrade/plan.json"],
            cwd=consumer,
            check=False,
        ).returncode
        == 1
    )

    planned = _run(
        synthetic_upgrade,
        *_plan_args(synthetic_upgrade),
        "--changed-path",
        "wiki.config.yaml",
        "--out",
        str(synthetic_upgrade["plan"]),
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    _remember_plan_anchor(synthetic_upgrade, planned)
    paused = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    assert '"status": "paused_before_canary"' in paused.stdout

    execution_path = next(plan_root.glob("execution-plan-*.json"))
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    run_dir = plan_root / "runs" / execution["plan_sha256"][:16]
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "paused_before_canary"
    assert (run_dir / "evidence").is_dir()
    assert not (consumer / ".wiki-viva").exists()

    completed = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (run_dir / "adoption-receipt.json").is_file()
    assert (run_dir / "migration-report.private.json").is_file()
    assert (run_dir / "rollback.json").is_file()
    assert (plan_root / "latest.json").is_file()
    assert not (consumer / ".wiki-viva").exists()


@pytest.mark.parametrize(
    "gate_id",
    ["input_stage", "semantic_inventory", "snapshot_contract"],
)
def test_domain_sensitive_gate_failure_requests_new_b0_not_boundary_content(
    synthetic_upgrade: dict[str, Path | str],
    gate_id: str,
) -> None:
    _replace_synthetic_gate_command(
        synthetic_upgrade,
        gate_id,
        (
            'python3 -c "import sys; '
            "print('synthetic consumer preparation required'); sys.exit(3)\""
        ),
    )
    _create_plan(synthetic_upgrade)

    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))

    assert result.returncode == 2
    failure = next(
        json.loads(line)
        for line in reversed(result.stdout.splitlines())
        if line.startswith("{") and '"error_code"' in line
    )
    assert failure["error_code"] == "consumer_prep_required"
    assert failure["lane"] == "lane_b"
    assert failure["surface"] == gate_id
    assert failure["contract"] == gate_id
    next_action = failure["next_action"]
    assert "roll back this failed run" in next_action
    assert "new B0" in next_action
    assert "new plan" in next_action
    assert "certify a new release" in next_action
    assert "never add domain content in C1, C2 or C3" in next_action


def test_plan_adopt_resume_canary_and_rollback_are_complete_and_path_free(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan, run_dir = _complete_adoption(synthetic_upgrade)
    assert plan["schema_version"] == "wiki_viva_upgrade_plan.v4"
    assert plan["status"] == "ready"
    assert plan["selection"]["escalation"] == "consumer_delta"
    assert "upstream_check" in plan["selection"]["omitted_gates"]
    receipt = json.loads(
        (run_dir / "adoption-receipt.json").read_text(encoding="utf-8")
    )
    report = json.loads((run_dir / "migration-report.json").read_text(encoding="utf-8"))
    private_report = json.loads(
        (run_dir / "migration-report.private.json").read_text(encoding="utf-8")
    )
    public_report = json.loads(
        (run_dir / "migration-report.public.json").read_text(encoding="utf-8")
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    rollback = json.loads((run_dir / "rollback.json").read_text(encoding="utf-8"))
    authority_sha256 = plan["consumer_c3_authority_sha256"]
    assert plan["consumer_c3_authority"]["authority_sha256"] == authority_sha256
    assert receipt["schema_version"] == "wiki_viva_upgrade_adoption_receipt.v4"
    assert state["schema_version"] == "wiki_viva_upgrade_runner_state.v4"
    assert private_report["schema_version"] == "wiki_viva_upgrade_runner_report.v3"
    assert {
        receipt["consumer_c3_authority_sha256"],
        state["consumer_c3_authority_sha256"],
        private_report["consumer_c3_authority_sha256"],
    } == {authority_sha256}
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
    assert set(preflight_by_id) == {"diff_check"}
    assert preflight_by_id["diff_check"]["command_id"] == "diff_check"
    assert len(private_report["evidence"]["gate_logs"]) == len(
        plan["selection"]["selected_gates"]
    )
    assert len(private_report["evidence"]["console"]) >= len(
        plan["selection"]["selected_gates"]
    )
    assert private_report["evidence"]["network"]
    assert rollback["tree_equal"] is True

    receipt_bytes = (run_dir / "adoption-receipt.json").read_bytes()
    resumed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert resumed.returncode == 2
    assert '"error_code": "completed_run_not_resumable"' in resumed.stdout
    assert '"promotion_ready": true' not in resumed.stdout
    assert '"reused_receipt": true' not in resumed.stdout
    assert (run_dir / "adoption-receipt.json").read_bytes() == receipt_bytes

    (run_dir / "adoption-receipt.json").unlink()
    missing_receipt = _run(
        synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True)
    )
    assert missing_receipt.returncode == 2
    assert '"error_code": "completed_run_not_resumable"' in missing_receipt.stdout
    assert not (run_dir / "adoption-receipt.json").exists()
    (run_dir / "adoption-receipt.json").write_bytes(receipt_bytes)

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


def test_localized_config_bound_c3_flows_through_plan_state_receipt_and_report(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer_b0 = _localize_consumer_b0(synthetic_upgrade)
    plan_args = _plan_args(synthetic_upgrade)
    adapter_index = plan_args.index("--c3-adapter-command") + 1
    plan_args[adapter_index] = _localized_c3_adapter_spec()
    planned = _run(
        synthetic_upgrade,
        *plan_args,
        "--changed-path",
        "memorias/sistema/wiki/comandos.md",
        "--changed-path",
        "docs/referencias/releases/rc-sintetico.md",
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    _remember_plan_anchor(synthetic_upgrade, planned)
    preplan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))
    authority = preplan["consumer_c3_authority"]
    authority_sha256 = preplan["consumer_c3_authority_sha256"]
    assert preplan["schema_version"] == "wiki_viva_upgrade_plan.v4"
    assert preplan["selection"]["escalation"] == "consumer_delta"
    assert authority["consumer_B0"] == consumer_b0
    assert authority["authority_sha256"] == authority_sha256
    assert authority["layout"] == {
        "memory_root": "memorias",
        "references_root": "docs/referencias",
    }
    assert [item["path"] for item in authority["exact_markdown_paths"]] == [
        "memorias/sistema/wiki/comandos.md",
        "memorias/passagem-operacional.md",
    ]
    assert authority["release_records"]["root"] == "docs/referencias/releases"

    adopted = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert adopted.returncode == 0, adopted.stdout + adopted.stderr
    execution = json.loads(
        next(
            Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
        ).read_text(encoding="utf-8")
    )
    run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / execution["plan_sha256"][:16]
    )
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (run_dir / "adoption-receipt.json").read_text(encoding="utf-8")
    )
    private_report = json.loads(
        (run_dir / "migration-report.private.json").read_text(encoding="utf-8")
    )
    public_report_text = (run_dir / "migration-report.public.json").read_text(
        encoding="utf-8"
    )
    c3_paths = {item["path"] for item in execution["boundaries"]["C3"]}
    assert {
        "wiki.config.yaml",
        "memorias/sistema/wiki/comandos.md",
        "docs/referencias/releases/rc-sintetico.md",
    }.issubset(c3_paths)
    assert state["schema_version"] == "wiki_viva_upgrade_runner_state.v4"
    assert receipt["schema_version"] == "wiki_viva_upgrade_adoption_receipt.v4"
    assert private_report["schema_version"] == "wiki_viva_upgrade_runner_report.v3"
    assert {
        state["consumer_c3_authority_sha256"],
        receipt["consumer_c3_authority_sha256"],
        private_report["consumer_c3_authority_sha256"],
    } == {authority_sha256}
    assert "memorias/sistema/wiki/comandos.md" not in public_report_text
    assert "docs/referencias/releases/rc-sintetico.md" not in public_report_text


def test_localized_domain_path_selects_configured_content_semantics_delta(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    _localize_consumer_b0(synthetic_upgrade)
    plan = _create_plan(synthetic_upgrade, "memorias/pessoal/dado-real.md")
    assert plan["consumer_c3_authority"]["layout"]["memory_root"] == "memorias"
    assert plan["status"] == "ready_to_mutate"
    assert plan["selection"]["escalation"] == "consumer_delta"
    assert plan["selection"]["unknown_paths"] == []
    assert plan["selection"]["matched_surfaces"] == [
        "consumer_configuration",
        "content_semantics",
    ]
    assert "real_canary" in plan["selection"]["selected_gates"]
    assert "semantic_inventory" in plan["selection"]["selected_gates"]
    assert "visual_profiles" not in plan["selection"]["selected_gates"]


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


def test_boundary_chain_rejects_hidden_intermediate_or_merge_commit(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / "baseline.txt").write_text("baseline\n", encoding="utf-8")
    b0 = _commit_all(consumer, "B0")
    (consumer / "transient.txt").write_text("intermediate\n", encoding="utf-8")
    _commit_all(consumer, "unreviewed intermediate")
    (consumer / "transient.txt").unlink()
    (consumer / "c1.txt").write_text("C1\n", encoding="utf-8")
    c1 = _commit_all(consumer, "C1")
    (consumer / "c2.txt").write_text("C2\n", encoding="utf-8")
    c2 = _commit_all(consumer, "C2")
    (consumer / "c3.txt").write_text("C3\n", encoding="utf-8")
    c3 = _commit_all(consumer, "C3")

    with pytest.raises(
        upgrade_runner.RunnerError,
        match="direct single-parent ancestry chain",
    ):
        upgrade_runner._require_ancestry(consumer, [b0, c1, c2, c3])


def test_pre_mutation_plan_proves_distinct_c1_c2_c3_and_replays_generator(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    consumer = Path(synthetic_upgrade["consumer"])
    kit = Path(synthetic_upgrade["kit"])
    b0 = str(synthetic_upgrade["consumer_b0"])
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    _git(consumer, "checkout", "-q", "-b", "wiki/synthetic-migration")
    portable_entries = upgrade_runner._portable_entries(
        package, kit, package["release"]["source_sha"]
    )
    for relative, entry in portable_entries.items():
        destination = consumer / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry["bytes"])
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    c1 = _commit_all(consumer, "C1 faithful public import")
    generated = consumer / "docs/references/fixtures/demo-wiki/memories/artifact.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated exactly\n", encoding="utf-8")
    c2 = _commit_all(consumer, "C2 regenerated artifacts")
    (consumer / "wiki.config.yaml").write_text(
        "repo_id: synthetic-consumer-v8\n", encoding="utf-8"
    )
    c3 = _commit_all(consumer, "C3 consumer adaptation")
    _git(consumer, "checkout", "-q", "wiki/synthetic-upgrade")

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
    _remember_plan_anchor(synthetic_upgrade, planned)
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
        'python3 -c "import os,sys; from pathlib import Path; '
        "p=Path(os.environ['WIKI_VIVA_KIT_ROOT'])/'.fail-c2-once'; "
        "existed=p.exists(); p.write_text('seen'); "
        "a=Path('docs/references/fixtures/demo-wiki/memories/artifact.txt'); "
        "a.parent.mkdir(parents=True,exist_ok=True); "
        "a.write_text('generated exactly\\n', "
        "encoding='utf-8'); sys.exit(0 if existed else 3)\""
    )
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
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
    _remember_plan_anchor(synthetic_upgrade, planned)
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

    extra_field = copy.deepcopy(mutation_state)
    extra_field["manual_evidence"] = {"status": "passed"}
    mutation_state_path.write_text(json.dumps(extra_field), encoding="utf-8")
    rejected_field = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )
    assert rejected_field.returncode == 2
    assert '"error_code": "stale_mutation_resume_state"' in rejected_field.stdout

    extra_commit = copy.deepcopy(mutation_state)
    extra_commit["commits"]["C2"] = "e" * 40
    mutation_state_path.write_text(json.dumps(extra_commit), encoding="utf-8")
    rejected_commit = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )
    assert rejected_commit.returncode == 2
    assert '"error_code": "stale_mutation_resume_state"' in rejected_commit.stdout

    mutation_state_path.write_text(json.dumps(mutation_state), encoding="utf-8")
    resumed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr


def test_resume_reexecutes_coherently_resealed_passed_gate(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    _create_plan(synthetic_upgrade)
    paused = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_canary=True),
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    execution = json.loads(
        next(
            Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
        ).read_text(encoding="utf-8")
    )
    consumer = Path(synthetic_upgrade["consumer"])
    c3_before = _git(consumer, "rev-parse", "HEAD")
    run_dir = consumer / ".wiki-viva/upgrade/runs" / execution["plan_sha256"][:16]
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    forged = b"coherently resealed fabricated result\n"
    forged_sha256 = hashlib.sha256(forged).hexdigest()
    (run_dir / "logs/audit.log").write_bytes(forged)
    result = state["gate_results"]["audit"]
    result["output_sha256"] = forged_sha256
    process_console = next(
        item
        for item in result["_evidence"]["console"]
        if item.get("capture") == "process_stdout_stderr"
    )
    process_console["sha256"] = canonical_sha256(
        {
            "kind": "captured_process_console",
            "gate_id": "audit",
            "subject_sha": result["subject_sha"],
            "output_sha256": forged_sha256,
        }
    )
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    resumed = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, resume=True),
    )

    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert '"event": "gate_revalidation_required"' in resumed.stderr
    assert '"gate": "audit"' in resumed.stderr
    assert (run_dir / "logs/audit.log").read_bytes() == b"audit\n"
    after = json.loads(state_path.read_text(encoding="utf-8"))
    revalidation = after["gate_results"]["audit"]["_resume_revalidation"]
    assert revalidation == {
        "attempt": 1,
        "previous_output_sha256": forged_sha256,
        "reason": "portable_external_execution_authority_absent",
        "result": "reexecuted",
    }
    assert _git(consumer, "rev-parse", "HEAD") == c3_before
    assert execution["identity"]["consumer_C3"] == c3_before


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

    stale_c3_authority = copy.deepcopy(original)
    stale_c3_authority["consumer_c3_authority_sha256"] = "d" * 64
    state_path.write_text(json.dumps(stale_c3_authority), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "stale_resume_consumer_c3_authority"' in result.stdout

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

    stale_budget = copy.deepcopy(original)
    for key in ("plan_started_at", "canary_completed_at"):
        stale_budget["acceptance_budget"][key] = (
            "2099" + stale_budget["acceptance_budget"][key][4:]
        )
    state_path.write_text(json.dumps(stale_budget), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "stale_acceptance_budget"' in result.stdout

    stale_canary_clock = copy.deepcopy(original)
    canary_gate = next(
        gate_id
        for gate_id, gate_result in stale_canary_clock["gate_results"].items()
        if gate_result["class"] == "canary"
    )
    stale_canary_clock["gate_results"][canary_gate]["_completed_at"] = (
        stale_canary_clock["acceptance_budget"]["plan_started_at"]
    )
    state_path.write_text(json.dumps(stale_canary_clock), encoding="utf-8")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "stale_acceptance_budget"' in result.stdout

    state_path.write_text(json.dumps(original), encoding="utf-8")
    consumer = Path(synthetic_upgrade["consumer"])
    (consumer / "wiki.config.yaml").write_text(
        "repo_id: changed-c3\n", encoding="utf-8"
    )
    _commit_all(consumer, "change C3 after plan")
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert result.returncode == 2
    assert '"error_code": "changed_consumer_C3"' in result.stdout
    assert str(consumer) not in result.stdout
    assert plan["identity"]["consumer_C3"] != _git(consumer, "rev-parse", "HEAD")


def test_plan_to_canary_budget_overrun_blocks_receipt_and_promotion(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1201)
    started_at = started.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    plan_path = Path(synthetic_upgrade["plan"])
    anchor_path = upgrade_runner._acceptance_anchor_path(
        plan_path, plan["acceptance_anchor"]["attempt_identity_sha256"]
    )
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    anchor["plan_started_at"] = started_at
    anchor.pop("anchor_sha256")
    anchor["anchor_sha256"] = canonical_sha256(anchor)
    anchor_raw = upgrade_runner._json_bytes(anchor)
    anchor_path.write_bytes(anchor_raw)
    trusted_anchor = hashlib.sha256(anchor_raw).hexdigest()
    synthetic_upgrade["trusted_acceptance_anchor_sha256"] = trusted_anchor
    plan["acceptance_budget"]["plan_started_at"] = started_at
    plan["acceptance_anchor"]["anchor_sha256"] = anchor["anchor_sha256"]
    plan["acceptance_anchor"]["file_sha256"] = trusted_anchor
    plan["plan_sha256"] = upgrade_runner._plan_digest(plan)
    plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")

    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert result.returncode == 2, result.stdout + result.stderr
    execution_paths = sorted(
        Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
    )
    assert len(execution_paths) == 1
    execution = json.loads(execution_paths[0].read_text(encoding="utf-8"))
    run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / execution["plan_sha256"][:16]
    )
    receipt = json.loads(
        (run_dir / "adoption-receipt.json").read_text(encoding="utf-8")
    )
    private_report = json.loads(
        (run_dir / "migration-report.private.json").read_text(encoding="utf-8")
    )
    public_report = json.loads(
        (run_dir / "migration-report.public.json").read_text(encoding="utf-8")
    )
    assert receipt["schema_version"] == "wiki_viva_upgrade_adoption_receipt.v4"
    assert receipt["status"] == "blocked"
    assert receipt["acceptance_budget"]["status"] == "exceeded"
    assert receipt["acceptance_budget"] == private_report["acceptance_budget"]
    assert public_report["acceptance_budget"] == {
        "schema_version": "wiki_viva_upgrade_acceptance_budget_public.v1",
        "scope": "plan_to_real_canary",
        "limit_seconds": 1200,
        "enforcement": "promotion_blocking",
        "status": "exceeded",
    }
    public_text = json.dumps(public_report, sort_keys=True)
    assert "plan_started_at" not in public_text
    assert "canary_completed_at" not in public_text
    assert "elapsed_milliseconds" not in public_text
    assert private_report["promotion_ready"] is False
    assert public_report["promotion_ready"] is False
    assert (run_dir / "rollback.json").is_file()
    assert "background_suite" in {result["id"] for result in receipt["gate_results"]}
    assert '"status": "blocked"' in result.stdout
    assert '"lane": "lane_b"' in result.stdout
    assert '"contract": "wiki_viva_upgrade_acceptance_budget.v1"' in result.stdout
    assert '"next_action"' in result.stdout
    assert '"promotion_ready": false' in result.stdout


def test_resume_recovers_budget_from_persisted_real_canary_completion(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    _create_plan(synthetic_upgrade)
    paused = _run(
        synthetic_upgrade,
        *_adopt_args(synthetic_upgrade, pause_before_background=True),
    )
    assert paused.returncode == 0, paused.stdout + paused.stderr
    execution = json.loads(
        next(
            Path(synthetic_upgrade["plan"]).parent.glob("execution-plan-*.json")
        ).read_text(encoding="utf-8")
    )
    run_dir = (
        Path(synthetic_upgrade["consumer"])
        / ".wiki-viva/upgrade/runs"
        / execution["plan_sha256"][:16]
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["acceptance_budget"]["status"] == "met"
    expected_completed_at = state["acceptance_budget"]["canary_completed_at"]
    state["acceptance_budget"] = copy.deepcopy(execution["acceptance_budget"])
    state_path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")

    resumed = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade, resume=True))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    recovered = json.loads(state_path.read_text(encoding="utf-8"))
    assert recovered["acceptance_budget"]["status"] == "met"
    assert (
        recovered["acceptance_budget"]["canary_completed_at"] == expected_completed_at
    )
    assert (
        json.loads((run_dir / "adoption-receipt.json").read_text(encoding="utf-8"))[
            "acceptance_budget"
        ]
        == recovered["acceptance_budget"]
    )


def test_scheduler_waits_for_dependencies_before_parallel_gate_wave(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    package["migration"]["gate_policies"]["audit"]["resource_group"] = "consumer_python"
    package["migration"]["gate_policies"]["affected_check"]["depends_on"] = ["audit"]
    package["migration"]["gate_policies"]["affected_check"][
        "resource_group"
    ] = "consumer_python"
    _reseal_package(synthetic_upgrade, package)
    _create_plan(synthetic_upgrade)
    plan = json.loads(Path(synthetic_upgrade["plan"]).read_text(encoding="utf-8"))
    affected = next(
        item for item in plan["gate_catalog"] if item["id"] == "affected_check"
    )
    assert affected["depends_on"] == ["audit"]
    assert affected["resource_group"] == "consumer_python"
    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert result.returncode == 0, result.stdout + result.stderr
    events = [
        json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")
    ]
    audit_completed = next(
        index
        for index, event in enumerate(events)
        if event.get("event") == "gate_completed" and event.get("gate") == "audit"
    )
    affected_started = next(
        index
        for index, event in enumerate(events)
        if event.get("event") == "gate_started"
        and event.get("gate") == "affected_check"
    )
    assert audit_completed < affected_started
    progress = [event for event in events if event.get("event") == "matrix_progress"]
    assert progress
    assert all(
        {"phase", "completed", "total", "elapsed_seconds", "eta_seconds"}.issubset(
            event
        )
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
    kit = Path(synthetic_upgrade["kit"])
    b0 = str(synthetic_upgrade["consumer_b0"])
    package = yaml.safe_load(
        Path(synthetic_upgrade["package"]).read_text(encoding="utf-8")
    )
    _git(consumer, "checkout", "-q", "-b", "wiki/mixed-chain", b0)
    for relative, entry in upgrade_runner._portable_entries(
        package, kit, package["release"]["source_sha"]
    ).items():
        destination = consumer / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(entry["bytes"])
        destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    c1 = _commit_all(consumer, "C1 faithful public import")
    generated = consumer / "docs/references/fixtures/demo-wiki/memories/artifact.txt"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text("generated exactly\n", encoding="utf-8")
    c2 = _commit_all(consumer, "C2 regenerated artifacts")
    (consumer / "wiki_core").mkdir(parents=True, exist_ok=True)
    (consumer / "wiki_core/consumer.py").write_text("VALUE = 1\n", encoding="utf-8")
    c3 = _commit_all(consumer, "mix portable code into C3")
    _git(consumer, "checkout", "-q", "-b", "wiki/mixed-plan", b0)
    mixed = _run(
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
    assert mixed.returncode == 2
    assert '"error_code": "boundary_ownership_mismatch"' in mixed.stdout


def test_resealed_plan_rejects_forged_conceptual_diff_and_unknown_fields(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    original = _create_plan(synthetic_upgrade)
    forged_diff = copy.deepcopy(original)
    forged_diff["status"] = "ready"
    forged_diff["conceptual_diff"]["summary"] = "fabricated operator preview"
    forged_diff["plan_sha256"] = upgrade_runner._plan_digest(forged_diff)
    Path(synthetic_upgrade["plan"]).write_text(
        json.dumps(forged_diff, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rejected_diff = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert rejected_diff.returncode == 2
    assert '"error_code": "stale_or_forged_conceptual_diff"' in rejected_diff.stdout

    forged_shape = copy.deepcopy(original)
    forged_shape["fabricated_evidence"] = {"status": "passed"}
    forged_shape["plan_sha256"] = upgrade_runner._plan_digest(forged_shape)
    Path(synthetic_upgrade["plan"]).write_text(
        json.dumps(forged_shape, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    rejected_shape = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert rejected_shape.returncode == 2
    assert '"error_code": "invalid_plan_shape"' in rejected_shape.stdout


def test_malformed_acceptance_budget_is_rejected_before_consumer_mutation(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    commit_count = _git(consumer, "rev-list", "--count", "HEAD")

    plan["acceptance_budget"].pop("limit_seconds")
    plan["plan_sha256"] = upgrade_runner._plan_digest(plan)
    Path(synthetic_upgrade["plan"]).write_text(json.dumps(plan), encoding="utf-8")

    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))

    assert result.returncode == 2
    assert '"error_code": "invalid_acceptance_budget"' in result.stdout
    assert _git(consumer, "rev-parse", "HEAD") == b0
    assert _git(consumer, "rev-list", "--count", "HEAD") == commit_count
    output_root = Path(synthetic_upgrade["plan"]).parent
    assert not list(output_root.glob("execution-plan-*.json"))
    assert not list(output_root.glob("mutation-state-*.json"))


def test_resealed_fabricated_preflight_cannot_reuse_original_acceptance_anchor(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    result = plan["preflight"]["results"][0]
    fabricated = b"fabricated preflight evidence\n"
    (consumer / result["output_ref"]).write_bytes(fabricated)
    result["output_sha256"] = hashlib.sha256(fabricated).hexdigest()
    result["output_bytes"] = len(fabricated)
    unsigned_preflight = dict(plan["preflight"])
    unsigned_preflight.pop("preflight_sha256")
    plan["preflight"]["preflight_sha256"] = canonical_sha256(unsigned_preflight)
    plan["plan_sha256"] = upgrade_runner._plan_digest(plan)
    Path(synthetic_upgrade["plan"]).write_text(
        json.dumps(plan, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    rejected = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))
    assert rejected.returncode == 2
    failure = json.loads(rejected.stdout)
    assert failure["error_code"] in {
        "acceptance_anchor_attempt_mismatch",
        "invalid_acceptance_anchor",
    }
    assert _git(consumer, "rev-parse", "HEAD") == b0
    output_root = Path(synthetic_upgrade["plan"]).parent
    assert not list(output_root.glob("execution-plan-*.json"))
    assert not list(output_root.glob("mutation-state-*.json"))


def test_plan_clock_cannot_be_reset_after_external_anchor_is_emitted(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    adopt_args = _adopt_args(synthetic_upgrade)

    started = dt.datetime.strptime(
        plan["acceptance_budget"]["plan_started_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=dt.timezone.utc)
    plan["acceptance_budget"]["plan_started_at"] = (
        started + dt.timedelta(minutes=10)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    plan["plan_sha256"] = upgrade_runner._plan_digest(plan)
    Path(synthetic_upgrade["plan"]).write_text(json.dumps(plan), encoding="utf-8")

    result = _run(synthetic_upgrade, *adopt_args)

    assert result.returncode == 2
    assert '"error_code": "stale_acceptance_anchor"' in result.stdout
    assert _git(consumer, "rev-parse", "HEAD") == b0
    output_root = Path(synthetic_upgrade["plan"]).parent
    assert not list(output_root.glob("execution-plan-*.json"))
    assert not list(output_root.glob("mutation-state-*.json"))


def test_coherent_plan_and_anchor_tamper_fails_against_original_external_digest(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    adopt_args = _adopt_args(synthetic_upgrade)
    plan_path = Path(synthetic_upgrade["plan"])
    anchor_path = upgrade_runner._acceptance_anchor_path(
        plan_path, plan["acceptance_anchor"]["attempt_identity_sha256"]
    )
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    started = dt.datetime.strptime(
        anchor["plan_started_at"], "%Y-%m-%dT%H:%M:%S.%fZ"
    ).replace(tzinfo=dt.timezone.utc)
    changed_started = (started + dt.timedelta(minutes=10)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    anchor["plan_started_at"] = changed_started
    anchor.pop("anchor_sha256")
    anchor["anchor_sha256"] = canonical_sha256(anchor)
    changed_anchor_raw = upgrade_runner._json_bytes(anchor)
    anchor_path.write_bytes(changed_anchor_raw)

    plan["acceptance_budget"]["plan_started_at"] = changed_started
    plan["acceptance_anchor"]["anchor_sha256"] = anchor["anchor_sha256"]
    plan["acceptance_anchor"]["file_sha256"] = hashlib.sha256(
        changed_anchor_raw
    ).hexdigest()
    plan["plan_sha256"] = upgrade_runner._plan_digest(plan)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = _run(synthetic_upgrade, *adopt_args)

    assert result.returncode == 2
    assert '"error_code": "untrusted_acceptance_anchor"' in result.stdout
    assert _git(consumer, "rev-parse", "HEAD") == b0
    assert not list(plan_path.parent.glob("execution-plan-*.json"))
    assert not list(plan_path.parent.glob("mutation-state-*.json"))


def test_same_attempt_reuses_first_write_acceptance_clock(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    first = _create_plan(synthetic_upgrade)
    first_digest = synthetic_upgrade["trusted_acceptance_anchor_sha256"]
    first_started_at = first["acceptance_budget"]["plan_started_at"]

    second = _create_plan(synthetic_upgrade)

    assert second["acceptance_budget"]["plan_started_at"] == first_started_at
    assert synthetic_upgrade["trusted_acceptance_anchor_sha256"] == first_digest
    assert second["acceptance_anchor"] == first["acceptance_anchor"]


def test_adopt_never_recreates_a_missing_acceptance_anchor(
    synthetic_upgrade: dict[str, Path | str],
) -> None:
    plan = _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    adopt_args = _adopt_args(synthetic_upgrade)
    plan_path = Path(synthetic_upgrade["plan"])
    anchor_path = upgrade_runner._acceptance_anchor_path(
        plan_path, plan["acceptance_anchor"]["attempt_identity_sha256"]
    )
    anchor_path.unlink()

    result = _run(synthetic_upgrade, *adopt_args)

    assert result.returncode == 2
    assert '"error_code": "missing_private_evidence"' in result.stdout
    assert not anchor_path.exists()
    assert _git(consumer, "rev-parse", "HEAD") == b0
    assert not list(plan_path.parent.glob("mutation-state-*.json"))


@pytest.mark.parametrize(
    "altered_relative",
    [
        "scripts/wiki_upgrade.py",
        "scripts/_common.py",
        "scripts/_git_subject.py",
        "scripts/wiki_toolchain_probe.py",
        "scripts/wiki_node_workspace.py",
        "wiki_core/upgrade_lanes.py",
    ],
)
def test_modified_runner_closure_is_rejected_before_mutation(
    synthetic_upgrade: dict[str, Path | str],
    tmp_path: Path,
    altered_relative: str,
) -> None:
    _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    runtime = tmp_path / "altered-runtime"
    entrypoint = _copy_runner_runtime(runtime)
    altered = runtime / altered_relative
    altered.write_text(
        altered.read_text(encoding="utf-8") + "\n# altered runtime-closure bytes\n",
        encoding="utf-8",
    )
    environment = _relocated_runtime_environment()
    result = subprocess.run(
        [sys.executable, str(entrypoint), *_adopt_args(synthetic_upgrade)],
        cwd=runtime,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )

    assert result.returncode == 2
    assert '"error_code": "toolchain_identity_mismatch"' in result.stdout
    assert _git(consumer, "rev-parse", "HEAD") == b0
    assert not list(
        Path(synthetic_upgrade["plan"]).parent.glob("mutation-state-*.json")
    )


@pytest.mark.parametrize("tool_id", ["python", "browser"])
def test_tampered_capsule_toolchain_is_rejected_before_runtime_probe_or_mutation(
    synthetic_upgrade: dict[str, Path | str],
    tool_id: str,
) -> None:
    _create_plan(synthetic_upgrade)
    consumer = Path(synthetic_upgrade["consumer"])
    b0 = _git(consumer, "rev-parse", "HEAD")
    capsule_path = Path(synthetic_upgrade["capsule"])
    capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
    capsule["toolchain"][tool_id]["version"] += "+altered"
    capsule_path.write_text(
        json.dumps(capsule, sort_keys=True) + "\n", encoding="utf-8"
    )

    result = _run(synthetic_upgrade, *_adopt_args(synthetic_upgrade))

    assert result.returncode == 2
    assert '"error_code": "lane_contract_rejected"' in result.stdout
    assert '"lane": "lane_a"' in result.stdout
    assert '"surface": "release_capsule_or_impact_registry"' in result.stdout
    assert _git(consumer, "rev-parse", "HEAD") == b0
    assert not list(
        Path(synthetic_upgrade["plan"]).parent.glob("mutation-state-*.json")
    )


def test_toolchain_probe_environment_strips_node_and_python_injection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    node_marker = tmp_path / "node-options-executed"
    node_hook = tmp_path / "hostile-node-hook.js"
    node_hook.write_text(
        "require('fs').writeFileSync("
        + json.dumps(str(node_marker))
        + ", 'executed')\n",
        encoding="utf-8",
    )
    python_marker = tmp_path / "pythonpath-executed"
    python_path = tmp_path / "hostile-pythonpath"
    python_path.mkdir()
    (python_path / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(python_marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={node_hook}")
    monkeypatch.setenv("PYTHONPATH", str(python_path))
    monkeypatch.setenv("WIKI_COCKPIT_API_TOKEN", "must-not-cross-probe")

    node = shutil.which("node")
    assert node is not None
    assert (
        upgrade_runner._toolchain_probe_output(
            [node, "-e", "process.stdout.write('node-ok')"], cwd=tmp_path
        )
        == b"node-ok"
    )
    assert (
        upgrade_runner._toolchain_probe_output(
            [sys.executable, "-c", "print('python-ok', end='')"], cwd=tmp_path
        )
        == b"python-ok"
    )
    assert not node_marker.exists()
    assert not python_marker.exists()
    environment = upgrade_runner._toolchain_probe_environment()
    assert "NODE_OPTIONS" not in environment
    assert "PYTHONPATH" not in environment
    assert "WIKI_COCKPIT_API_TOKEN" not in environment


def test_browser_probe_uses_certified_node_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module_root = tmp_path / "apps/wiki-cockpit/node_modules/playwright"
    module_root.mkdir(parents=True)
    (module_root / "package.json").write_text("{}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    class Context:
        node = {"executable": "/certified/node"}
        environment = {"PATH": "/certified/bin"}

    def fake_probe(
        argv: list[str],
        *,
        cwd: Path,
        environment: dict[str, str] | None = None,
    ) -> bytes:
        captured.update(argv=argv, cwd=cwd, environment=environment)
        return json.dumps(
            {
                "schema_version": "wiki_viva_browser_engine_toolchain.v1",
                "browser": "chromium",
                "browser_version": "123.0.0",
                "playwright_version": "1.61.1",
            }
        ).encode("utf-8")

    monkeypatch.setattr(upgrade_runner, "_toolchain_probe_output", fake_probe)
    identity, argv, _raw = upgrade_runner._browser_toolchain_probe(
        kit_root=tmp_path,
        execution_context=Context(),
    )

    assert captured["argv"][0] == "/certified/node"
    assert argv[0] == "node"
    assert "/certified/node" not in argv
    assert captured["environment"] == Context.environment
    assert identity == {
        "name": "playwright-chromium",
        "version": "1.61.1+chromium.123.0.0",
    }


def test_certified_browser_probe_rejects_playwright_outside_kit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outside = tmp_path / "outside/node_modules/playwright"
    outside.mkdir(parents=True)
    (outside / "package.json").write_text("{}\n", encoding="utf-8")
    kit = tmp_path / "empty-kit"
    kit.mkdir()

    class Context:
        node = {"executable": "/certified/node"}
        environment = {"PATH": "/certified/bin"}

    monkeypatch.setattr(
        upgrade_runner, "_playwright_module_root", lambda _root: outside
    )
    with pytest.raises(
        upgrade_runner.RunnerError,
        match="certified Node workspace has no Playwright module",
    ):
        upgrade_runner._browser_toolchain_probe(
            kit_root=kit,
            execution_context=Context(),
        )


def test_byte_equal_runner_closure_identity_is_path_independent(
    synthetic_upgrade: dict[str, Path | str],
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "relocated-runtime"
    relocated = _copy_runner_runtime(runtime)
    environment = _relocated_runtime_environment()

    result = subprocess.run(
        [sys.executable, str(relocated), "--version"],
        cwd=runtime,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "wiki-upgrade " + upgrade_runner._runner_identity_version(ROOT)
    )

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path; "
                "from scripts.wiki_upgrade import _load_artifacts; "
                "\ntry:\n _load_artifacts(Path(sys.argv[1]),Path(sys.argv[2]),"
                "Path(sys.argv[3]),kit_root=Path(sys.argv[4]),"
                "authority_path=Path(sys.argv[5]),"
                "trusted_attestation_sha256=sys.argv[6])\n"
                "except Exception as exc:\n print(type(exc).__name__,repr(exc),"
                "type(exc.__cause__).__name__,repr(exc.__cause__))\n raise\n"
            ),
            str(synthetic_upgrade["package"]),
            str(synthetic_upgrade["capsule"]),
            str(synthetic_upgrade["registry"]),
            str(synthetic_upgrade["kit"]),
            str(synthetic_upgrade["authority"]),
            str(synthetic_upgrade["trusted_attestation_sha256"]),
        ],
        cwd=runtime,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=180,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr


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


def test_upgrade_command_is_versioned_and_only_safe_verifier_is_operator_allowed() -> (
    None
):
    assert is_allowed_argv(
        ["python3", "scripts/wiki_upgrade.py", "verify-rollback-report", "--check"]
    )
    assert not is_allowed_argv(["python3", "scripts/wiki_upgrade.py", "certify"])
    assert not is_allowed_argv(["python3", "scripts/wiki_upgrade.py", "verify-capsule"])
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
    assert command == "python3 scripts/wiki_node_workspace.py run test:e2e:operator"
    assert upgrade_runner._parse_command(command, kit_root=ROOT) == [
        upgrade_runner._active_python_alias(),
        "scripts/wiki_node_workspace.py",
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
    monkeypatch.setenv(
        "WIKI_COCKPIT_EXPECT_SERVER_VERSION",
        values["WIKI_COCKPIT_EXPECT_SERVER_VERSION"],
    )
    monkeypatch.setenv(
        "WIKI_COCKPIT_EXPECT_REPO_ID",
        "https://user:synthetic-secret-value@example.invalid",
    )
    with pytest.raises(upgrade_runner.RunnerError) as caught:
        upgrade_runner._gate_environment(
            tmp_path,
            ROOT,
            "real_canary",
            subject_sha=consumer_sha,
            public_release_sha=public_sha,
            require_operator_environment=True,
        )
    assert caught.value.code == "secret_command_input"
    assert "synthetic-secret-value" not in json.dumps(
        upgrade_runner._failure_payload(caught.value)
    )


def test_two_lane_workflow_handoff_is_retry_safe_for_rerun_failed_jobs() -> None:
    workflow_path = ROOT / ".github/workflows/wiki-upgrade-lanes.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)
    assert "github.run_attempt" not in workflow
    assert (
        "wiki-upgrade-fast-adoption-${{ runner.os }}-${{ github.run_id }}" in workflow
    )
    assert (
        "wiki-upgrade-canary-handoff-${{ runner.os }}-${{ github.run_id }}" in workflow
    )
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


def test_ci_fast_adoption_consumes_exact_upstream_lane_a_bundle(
    tmp_path: Path,
) -> None:
    destination_value = os.environ.get("WIKI_UPGRADE_CI_HANDOFF")
    if not destination_value:
        pytest.skip("CI handoff export is only enabled by the two-lane workflow")
    lane_a_value = os.environ.get("WIKI_UPGRADE_CI_LANE_A")
    if not lane_a_value:
        pytest.fail("CI fast adoption must consume the upstream Lane A bundle")

    from wiki_core.upgrade_lanes import verify_impact_registry

    lane_a_root = Path(lane_a_value).resolve(strict=True)
    manifest = json.loads(
        (lane_a_root / "bundle-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["schema_version"] == "wiki_viva_upgrade_lane_a_bundle.v1"
    manifest_files = manifest["files"]
    assert isinstance(manifest_files, list) and manifest_files
    expected = {item["path"]: item for item in manifest_files}
    assert len(expected) == len(manifest_files)
    observed: dict[str, dict[str, str | int]] = {}
    for path in sorted(lane_a_root.rglob("*")):
        if path.is_symlink():
            pytest.fail(f"Lane A bundle contains a symlink: {path.name}")
        if not path.is_file() or path.name == "bundle-manifest.json":
            continue
        raw = path.read_bytes()
        relative = path.relative_to(lane_a_root).as_posix()
        observed[relative] = {
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    assert observed == expected

    certified_root = lane_a_root / "certified"
    inputs_root = lane_a_root / "inputs"
    capsule = json.loads(
        (certified_root / "release-capsule.json").read_text(encoding="utf-8")
    )
    receipt_raw = (certified_root / "certification-receipt.json").read_bytes()
    certification_receipt = json.loads(receipt_raw)
    package = yaml.safe_load(
        (inputs_root / "upgrade-package.yaml").read_text(encoding="utf-8")
    )
    registry = yaml.safe_load(
        (inputs_root / "impact-registry.yaml").read_text(encoding="utf-8")
    )
    trust = (
        (certified_root / "trusted-attestation-sha256.txt")
        .read_text(encoding="ascii")
        .strip()
    )
    unsigned_receipt = dict(certification_receipt)
    assert unsigned_receipt.pop("receipt_sha256") == canonical_sha256(unsigned_receipt)
    assert capsule["source_sha"] == manifest["source_sha"]
    assert capsule["capsule_sha256"] == manifest["capsule_sha256"]
    assert (
        canonical_sha256(package)
        == capsule["package_sha256"]
        == manifest["package_sha256"]
    )
    assert capsule["portable_tree_sha256"] == manifest["portable_tree_sha256"]
    assert capsule["command_registry_sha256"] == manifest["command_registry_sha256"]
    assert capsule["toolchain_sha256"] == manifest["toolchain_sha256"]
    assert capsule["toolchain"]["python"]["name"].endswith("-resolved")
    assert re.fullmatch(
        r"[A-Za-z0-9._+-]+\+deps\.[0-9a-f]{64}",
        capsule["toolchain"]["python"]["version"],
    )
    assert capsule["toolchain"]["browser"]["name"] == "playwright-chromium"
    assert "+chromium." in capsule["toolchain"]["browser"]["version"]
    assert verify_impact_registry(registry) == manifest["impact_registry_sha256"]
    assert (
        hashlib.sha256(receipt_raw).hexdigest()
        == manifest["certification_receipt_sha256"]
    )
    assert (
        certification_receipt["receipt_sha256"]
        == manifest["certification_receipt_digest"]
    )
    assert certification_receipt["source_sha"] == manifest["source_sha"]
    assert certification_receipt["capsule_sha256"] == manifest["capsule_sha256"]
    assert certification_receipt["package_sha256"] == manifest["package_sha256"]
    assert (
        certification_receipt["portable_tree_sha256"]
        == manifest["portable_tree_sha256"]
    )
    assert (
        certification_receipt["command_registry_sha256"]
        == manifest["command_registry_sha256"]
    )
    assert certification_receipt["toolchain_sha256"] == manifest["toolchain_sha256"]
    assert (
        certification_receipt["attestation_sha256"]
        == trust
        == manifest["trusted_attestation_sha256"]
    )

    consumer = tmp_path / "consumer"
    _init_repo(consumer)
    (consumer / ".gitignore").write_text(".wiki-viva/\n", encoding="utf-8")
    (consumer / "wiki.config.yaml").write_text(
        "repo_id: synthetic-consumer\n", encoding="utf-8"
    )
    consumer_b0 = _commit_all(consumer, "synthetic consumer B0")
    _git(consumer, "checkout", "-q", "-b", "wiki/synthetic-upgrade")
    fixture: dict[str, Path | str] = {
        "kit": inputs_root / "public-kit",
        "consumer": consumer,
        "consumer_b0": consumer_b0,
        "package": inputs_root / "upgrade-package.yaml",
        "capsule": certified_root / "release-capsule.json",
        "registry": inputs_root / "impact-registry.yaml",
        "authority": certified_root / "release-authority.json",
        "trusted_attestation_sha256": trust,
        "plan": consumer / ".wiki-viva/upgrade/plan.json",
    }
    preplan = _create_plan(fixture)
    assert preplan["identity"]["source_sha"] == manifest["source_sha"]
    assert preplan["capsule_sha256"] == manifest["capsule_sha256"]
    assert preplan["identity"]["package_sha256"] == manifest["package_sha256"]
    assert (
        preplan["identity"]["portable_tree_sha256"] == manifest["portable_tree_sha256"]
    )
    assert (
        preplan["identity"]["command_registry_sha256"]
        == manifest["command_registry_sha256"]
    )
    assert preplan["identity"]["toolchain_sha256"] == manifest["toolchain_sha256"]
    assert preplan["impact_registry_sha256"] == manifest["impact_registry_sha256"]
    assert preplan["identity"]["consumer_B0"] == consumer_b0
    assert preplan["acceptance_budget"]["status"] == "pending"

    fast = _run(fixture, *_adopt_args(fixture, pause_before_canary=True))
    assert fast.returncode == 0, fast.stdout + fast.stderr
    assert '"status": "paused_before_canary"' in fast.stdout
    execution_paths = sorted(Path(fixture["plan"]).parent.glob("execution-plan-*.json"))
    assert len(execution_paths) == 1
    execution = json.loads(execution_paths[0].read_text(encoding="utf-8"))
    run_key = execution["plan_sha256"][:16]
    run_dir = consumer / ".wiki-viva/upgrade/runs" / run_key
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "paused_before_canary"
    assert state["capsule_sha256"] == manifest["capsule_sha256"]
    assert state["impact_registry_sha256"] == manifest["impact_registry_sha256"]
    assert state["acceptance_budget"] == execution["acceptance_budget"]
    assert state["acceptance_budget"]["status"] == "pending"
    assert not (run_dir / "adoption-receipt.json").exists()

    destination = Path(destination_value).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(inputs_root, destination, symlinks=True)
    shutil.copytree(certified_root, destination, symlinks=True, dirs_exist_ok=True)
    shutil.copytree(consumer, destination / "consumer", symlinks=True)
    (destination / "trusted-attestation-sha256").write_text(
        trust + "\n", encoding="ascii"
    )
    handoff = {
        "schema_version": "wiki_viva_upgrade_ci_handoff.v3",
        "preplan_sha256": preplan["plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "run_key": run_key,
        "state_sha256": hashlib.sha256(state_path.read_bytes()).hexdigest(),
        "source_sha": manifest["source_sha"],
        "capsule_sha256": manifest["capsule_sha256"],
        "package_sha256": manifest["package_sha256"],
        "portable_tree_sha256": manifest["portable_tree_sha256"],
        "consumer_B0": execution["identity"]["consumer_B0"],
        "consumer_C3": execution["identity"]["consumer_C3"],
        "command_registry_sha256": manifest["command_registry_sha256"],
        "toolchain_sha256": manifest["toolchain_sha256"],
        "impact_registry_sha256": manifest["impact_registry_sha256"],
        "certification_receipt_sha256": manifest["certification_receipt_sha256"],
        "certification_receipt_digest": manifest["certification_receipt_digest"],
        "trusted_attestation_sha256": manifest["trusted_attestation_sha256"],
        "acceptance_budget": state["acceptance_budget"],
        "acceptance_budget_sha256": canonical_sha256(state["acceptance_budget"]),
    }
    (destination / "handoff.json").write_text(
        json.dumps(handoff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_two_lane_workflow_reuses_lane_a_bundle_and_propagates_v2_budget() -> None:
    import inspect

    workflow_path = ROOT / ".github/workflows/wiki-upgrade-lanes.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)

    fast = parsed["jobs"]["fast-adoption"]
    canary = parsed["jobs"]["canary"]
    background = parsed["jobs"]["background-certification"]
    upstream = parsed["jobs"]["upstream-certification"]
    fast_script = "\n".join(str(step.get("run", "")) for step in fast["steps"])
    canary_script = "\n".join(str(step.get("run", "")) for step in canary["steps"])
    background_script = "\n".join(
        str(step.get("run", "")) for step in background["steps"]
    )

    assert "wiki-upgrade-lane-a-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert "lane-a-release.tgz" in workflow
    assert upstream["outputs"]["trusted_attestation_sha256"] == (
        "${{ steps.lane_a_trust.outputs.trusted_attestation_sha256 }}"
    )
    assert "TRUSTED_LANE_A_ATTESTATION_SHA256" in workflow
    assert (
        "needs['upstream-certification'].outputs.trusted_attestation_sha256" in workflow
    )
    assert "trusted_out_of_band" in fast_script
    assert (
        "manifest['trusted_attestation_sha256'] == trusted_out_of_band" in fast_script
    )
    assert "WIKI_UPGRADE_CI_LANE_A" in workflow
    assert "wiki_upgrade.py certify" not in fast_script
    assert "seal_release_capsule" not in fast_script
    assert "seal_release_capsule" not in canary_script
    assert "seal_release_capsule" not in background_script
    lane_b_test_source = inspect.getsource(
        test_ci_fast_adoption_consumes_exact_upstream_lane_a_bundle
    )
    assert "seal_release_capsule" not in lane_b_test_source
    assert "synthetic_upgrade" not in lane_b_test_source
    assert "test_ci_fast_adoption_consumes_exact_upstream_lane_a_bundle" in fast_script
    assert "test_ci_fast_adoption_handoff_is_resumable_runner_state" not in fast_script
    assert "wiki_viva_upgrade_ci_handoff.v3" in canary_script
    assert "wiki_viva_upgrade_ci_handoff.v3" in background_script
    assert "execution-plan-*.json" in canary_script
    assert "execution-plan-*.json" in background_script
    assert '--plan "$PLAN"' in canary_script
    assert '--plan "$PLAN"' in background_script
    for key in (
        "source_sha",
        "capsule_sha256",
        "package_sha256",
        "portable_tree_sha256",
        "consumer_B0",
        "consumer_C3",
        "command_registry_sha256",
        "toolchain_sha256",
        "impact_registry_sha256",
        "certification_receipt_sha256",
        "certification_receipt_digest",
        "trusted_attestation_sha256",
        "canary_completion_anchor_sha256",
    ):
        assert key in canary_script
        assert key in background_script
    assert "acceptance_budget_sha256" in canary_script
    assert "acceptance_budget_sha256" in background_script
    assert "budget['status'] == 'met'" in background_script
    assert "receipt['status'] == 'passed'" in background_script
