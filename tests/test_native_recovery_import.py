"""Real bootstrap + canonical ZIP recovery in disposable partial native trees."""
import json
from pathlib import Path
import shutil

import pytest

from test_native_complete_import import fixture_tree, import_candidate, probe
from test_native_host_integration import native_candidate, native_source


@pytest.mark.parametrize("identity", ["admin", "worker"])
@pytest.mark.parametrize("damage", ["missing", "incomplete"])
@pytest.mark.parametrize("launcher", ["bootstrap", "bootstrap-missing"])
def test_canonical_recovery_precedes_new_guard_dependency_and_then_keeps_authority(
        tmp_path, import_candidate, identity, damage, launcher):
    env = fixture_tree(tmp_path, import_candidate)
    for path in ("hermes_cli/_early_recovery.py", "hermes_cli/_early_recovery_zip.py", "hermes_cli/update_lock.py"):
        (tmp_path/path).write_text(native_source(import_candidate,path))
    env["WIKI_IMPORT_CASE"]="recovery-"+identity
    if identity=="worker": env["HERMES_KANBAN_TASK"]="task"
    if launcher=="bootstrap-missing": (tmp_path/"hermes_bootstrap.py").unlink()
    expected=(tmp_path/"tools/wiki_native_startup_guard.py").read_bytes()
    shutil.copytree(tmp_path/"tools",tmp_path/"tools.hermes-update-old")
    guard=tmp_path/"tools/wiki_native_startup_guard.py"
    if damage=="missing": guard.unlink()
    else: guard.write_text("def incomplete(\n")
    # Exact native journal contract. The native recovery owns these temporary
    # directories and kernel locks; no installed tree is involved.
    journal=tmp_path/".hermes-update-zip-swap"
    journal.write_text(json.dumps({"phase":"swapping","gen":"0123456789ab",
        "entries":[["tools",True,"",""]],"temps":{}}))
    result=probe(tmp_path,env)
    assert result.get("error","").startswith("RecoveryRelaunch:"),result.get("trace",result)
    assert "native-recovery-journal" in result["events"] and "native-recovery-rename" in result["events"],result
    assert result["events"][-1]=="native-relaunch-requested",result
    assert "startup-guard-read" not in result["events"],result
    assert not any(e.startswith("dotenv:") or e=="external-source" for e in result["events"]),result
    assert not journal.exists() and guard.read_bytes()==expected
    # Fresh native import after the requested relaunch. Recovery is not an
    # authority bypass: the unqualified worker still stops before all loaders.
    result=probe(tmp_path,env)
    if identity=="worker":
        assert result.get("error","").startswith("AuthorityDenied:authority_native_channel_required"),result
        assert not any(e.startswith("dotenv:") or e=="external-source" for e in result["events"]),result
    else:
        assert "error" not in result,result.get("trace",result)
        assert result["imports"]==["hermes_cli.main","model_tools"]
        assert result["marker"]=="fixture-only" and result["external_marker"]=="fixture-only"
        assert result["filter"]==["synthetic-native"] and result["refresh_reapplied"] is True


@pytest.mark.parametrize("identity", ["admin", "worker"])
def test_missing_guard_without_recovery_marker_is_not_ignored(tmp_path, import_candidate, identity):
    env=fixture_tree(tmp_path,import_candidate)
    env["WIKI_IMPORT_CASE"]="recovery-"+identity
    if identity=="worker":env["HERMES_KANBAN_TASK"]="task"
    for path in ("hermes_cli/_early_recovery.py","hermes_cli/_early_recovery_zip.py","hermes_cli/update_lock.py"):
        (tmp_path/path).write_text(native_source(import_candidate,path))
    (tmp_path/"tools/wiki_native_startup_guard.py").unlink()
    result=probe(tmp_path,env)
    assert result.get("error","").startswith("ModuleNotFoundError:"),result
    assert not any(e.startswith("dotenv:") or e=="external-source" for e in result["events"]),result
