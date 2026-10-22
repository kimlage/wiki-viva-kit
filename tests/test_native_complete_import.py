"""Complete pinned module imports, including top-level effects, in an isolated process."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_native_host_integration import native_candidate, native_modules, native_source, stack
from wiki_core import native_host as nh


@pytest.fixture(scope="module")
def import_candidate(native_candidate):
    override = os.environ.get("WIKI_NATIVE_IMPORT_BUILDER")
    if not override: return native_candidate
    spec = importlib.util.spec_from_file_location("complete_import_baseline", override)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.candidate(Path(os.environ["WIKI_HERMES_KERNEL_SOURCE"]))


def fixture_tree(tmp_path, candidate):
    for path, (_, source) in candidate.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    for path in ("hermes_cli/__init__.py", "hermes_bootstrap.py", "hermes_cli/env_loader.py",
                 "hermes_cli/plugins.py", "agent/secret_scope.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(native_source(candidate, path))
    shutil.copyfile(Path(__file__).parent / "fixtures/hermes_native_import_probe.py", tmp_path / "probe.py")
    home = tmp_path / "home"
    home.mkdir()
    for path in (home / ".env", home / ".op.env", tmp_path / ".env"):
        path.write_text("SYNTHETIC_IMPORT_MARKER=fixture-only\n")
    (home / "config.yaml").write_text("synthetic fixture config only\n")
    return {"PATH": os.defpath, "HOME": str(tmp_path), "HERMES_HOME": str(home),
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def probe(tmp_path, env):
    result = subprocess.run([sys.executable, str(tmp_path / "probe.py")], env=env,
        cwd=tmp_path, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("identity", ["missing", "forged"])
def test_full_import_denies_missing_channel_before_dotenv_or_plugins(tmp_path, import_candidate, identity):
    env = fixture_tree(tmp_path, import_candidate)
    env.update(WIKI_IMPORT_CASE="missing", HERMES_KANBAN_TASK="task")
    if identity=="forged": env["HERMES_WIKI_NATIVE_CHANNEL"]=str(tmp_path/"unverified.sock")
    result = probe(tmp_path, env)
    code="authority_native_channel_required" if identity=="missing" else "authority_native_channel_unverified"
    assert result.get("error", "").startswith("AuthorityDenied:"+code), result
    assert not any(e.startswith("dotenv:") or e == "external-source" for e in result["events"]), result


@pytest.mark.parametrize("case", ["public", "public-admitted", "public-reload"])
def test_full_import_public_admission_does_not_enable_secrets_or_refresh(tmp_path, import_candidate, stack, case):
    env = fixture_tree(tmp_path, import_candidate)
    env.update(WIKI_IMPORT_CASE=case, HERMES_KANBAN_TASK="task")
    launch = asyncio.run(stack.authenticated(lambda: nh.prepare_worker("task", "board-a")))
    launch.configure(env)
    proc = subprocess.Popen([sys.executable, str(tmp_path / "probe.py")], env=env,
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    launch.spawned(proc.pid)
    stack.update("UPDATE tasks SET worker_pid=?,worker_started_at='start-a'", (proc.pid,))
    stack.update("UPDATE task_runs SET worker_pid=?,worker_started_at='start-a'", (proc.pid,))
    stack.host.registered("task", proc.pid, "start-a")
    try:
        stdout, stderr = proc.communicate(timeout=20)
        assert proc.returncode == 0, stderr
        result = json.loads(stdout.splitlines()[-1])
        assert "error" not in result, result.get("trace", result)
        assert result["imports"] == ["hermes_cli.main", "model_tools"]
        assert result["filter"] == ["synthetic-native"]
        assert result["deep_holds"] == ["authority_account_enforcement_required"] * 5, result
        assert result["refresh_reapplied"] is False, result
        assert result["marker"] is None and result["external_cache"] == 0, result
        assert result["external_marker"] is None, result
        assert not any(e.startswith("dotenv:") or e == "external-source" for e in result["events"]), result
    finally:
        if proc.poll() is None: proc.kill(); proc.wait()
        launch.close()


def test_full_native_admin_import_preserves_dotenv_external_sources_and_filter(tmp_path, import_candidate):
    env = fixture_tree(tmp_path, import_candidate)
    env["WIKI_IMPORT_CASE"] = "admin"
    result = probe(tmp_path, env)
    assert "error" not in result, result.get("trace", result)
    assert result["imports"] == ["hermes_cli.main", "model_tools"]
    assert result["marker"] == "fixture-only" and result["external_cache"] == 1, result
    assert result["external_marker"] == "fixture-only", result
    assert "dotenv:.env" in result["events"] and "external-source" in result["events"], result
    assert result["filter"] == ["synthetic-native"]
    assert result["refresh_reapplied"] is True, result
