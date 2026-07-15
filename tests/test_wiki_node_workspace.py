from __future__ import annotations

import concurrent.futures
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

import wiki_core.node_workspace as workspace


ROOT = Path(__file__).resolve().parents[1]
PICOCOLORS = {
    "version": "1.1.1",
    "resolved": "https://registry.npmjs.org/picocolors/-/picocolors-1.1.1.tgz",
    "integrity": (
        "sha512-xceH2snhtb5M9liqDsmEw56le376mTZkEX/jEb/RxNFyegNul7eNslCXP9FDj/"
        "Lcu0X8KEyMceP2ntpaHrDEVA=="
    ),
    "dev": True,
    "license": "ISC",
}


@dataclass(frozen=True)
class SyntheticAuthority:
    root: Path
    authority_path: Path
    authority: dict[str, object]
    authority_sha256: str
    source_sha: str


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _initialize_git_source(root: Path) -> str:
    (root / ".gitignore").write_text(
        f"/{workspace.NODE_MODULES_RELATIVE.as_posix()}\n", encoding="utf-8"
    )
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
            "GIT_AUTHOR_NAME": "Synthetic Fixture",
            "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
            "GIT_COMMITTER_NAME": "Synthetic Fixture",
        }
    )
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=root,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "add", "--all"],
        cwd=root,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture"],
        cwd=root,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _synthetic_workspace(
    root: Path,
    *,
    build_command: str = "node -e \"process.stdout.write('ok')\"",
) -> SyntheticAuthority:
    app = root / workspace.WORKSPACE_RELATIVE
    app.mkdir(parents=True)
    npm = workspace.resolved_npm_authority()
    scripts = {
        name: "node -e \"process.stdout.write('ok')\""
        for name in workspace.ALLOWED_SCRIPTS
    }
    scripts["build"] = build_command
    scripts["preview"] = "vite preview --host 127.0.0.1"
    package = {
        "name": "wiki-viva-public-synthetic-node-workspace",
        "version": "1.0.0",
        "private": True,
        "packageManager": f"npm@{npm['version']}",
        "scripts": scripts,
        "devDependencies": {"picocolors": "1.1.1"},
    }
    package_lock = {
        "name": package["name"],
        "version": package["version"],
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": package["name"],
                "version": package["version"],
                "devDependencies": {"picocolors": "1.1.1"},
            },
            "node_modules/picocolors": PICOCOLORS,
        },
    }
    _write_json(app / "package.json", package)
    _write_json(app / "package-lock.json", package_lock)
    policy = workspace.build_policy(root)
    (root / workspace.MANIFEST_RELATIVE).write_bytes(workspace.serialize_policy(policy))
    source_sha = _initialize_git_source(root)
    authority_path = root.parent / f"{root.name}.node-authority.json"
    receipt = workspace.capture_authority(root, authority_path, source_sha=source_sha)
    authority = workspace.load_authority(authority_path)
    assert receipt["authority_sha256"] == workspace.authority_identity_sha256(authority)
    return SyntheticAuthority(
        root=root,
        authority_path=authority_path,
        authority=authority,
        authority_sha256=str(receipt["authority_sha256"]),
        source_sha=source_sha,
    )


def _copy_workspace(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _verify(subject: Path, fixture: SyntheticAuthority) -> dict[str, object]:
    return workspace.verify_workspace(
        subject,
        fixture.authority_path,
        fixture.authority_sha256,
        source_sha=fixture.source_sha,
    )


def _materialize(subject: Path, fixture: SyntheticAuthority) -> dict[str, object]:
    return workspace.materialize(
        subject,
        fixture.authority_path,
        fixture.authority_sha256,
        source_sha=fixture.source_sha,
    )


def _run(
    subject: Path,
    fixture: SyntheticAuthority,
    script: str,
    arguments: list[str],
) -> workspace.CommandResult:
    return workspace.run_script(
        subject,
        script,
        arguments,
        fixture.authority_path,
        fixture.authority_sha256,
        source_sha=fixture.source_sha,
    )


@pytest.fixture(scope="module")
def synthetic_authority(
    tmp_path_factory: pytest.TempPathFactory,
) -> SyntheticAuthority:
    return _synthetic_workspace(tmp_path_factory.mktemp("node-workspace-authority"))


def test_project_policy_is_current_and_portable() -> None:
    policy = workspace.load_policy(ROOT)
    assert workspace.build_policy(ROOT) == policy
    assert policy["schema_version"] == workspace.POLICY_SCHEMA_VERSION
    assert policy["policy_sha256"]
    assert not ({"node", "npm", "platform", "node_modules"} & set(policy))
    encoded = workspace.serialize_policy(policy).decode("utf-8")
    assert "/Users/" not in encoded
    assert "runtime_tree" not in encoded
    assert "platform_machine" not in encoded


def test_clean_c1_materializes_once_and_is_resumable(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    shutil.rmtree(consumer / workspace.NODE_MODULES_RELATIVE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(
            pool.map(
                lambda _item: _materialize(consumer, synthetic_authority), range(2)
            )
        )
    assert sorted(bool(item["materialized"]) for item in receipts) == [False, True]
    assert all(item["status"] == "verified" for item in receipts)
    assert _verify(consumer, synthetic_authority)["status"] == "verified"


def test_registered_command_receipt_contains_no_host_path(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    result = _run(consumer, synthetic_authority, "build", [])
    encoded = json.dumps(result.receipt, sort_keys=True)
    assert result.receipt["status"] == "passed"
    assert result.output.endswith(b"ok")
    assert result.receipt["npm_toolchain"]["version"].endswith(
        f"workspace.{synthetic_authority.authority_sha256}"
    )
    assert str(tmp_path) not in encoded
    assert "/Users/" not in encoded
    assert "/private/" not in encoded


def test_authority_is_mandatory_and_all_bindings_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    with pytest.raises(workspace.NodeWorkspaceError) as missing:
        workspace.verify_workspace(consumer)
    assert missing.value.code == "node_workspace_authority_required"

    with pytest.raises(workspace.NodeWorkspaceError) as wrong_digest:
        workspace.verify_workspace(
            consumer,
            synthetic_authority.authority_path,
            "0" * 64,
            source_sha=synthetic_authority.source_sha,
        )
    assert wrong_digest.value.code == "node_workspace_authority_sha256_mismatch"

    with pytest.raises(workspace.NodeWorkspaceError) as missing_source:
        workspace.verify_workspace(
            consumer,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
        )
    assert missing_source.value.code == "node_workspace_source_required"

    with pytest.raises(workspace.NodeWorkspaceError) as wrong_source:
        workspace.verify_workspace(
            consumer,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha="b" * 40,
        )
    assert wrong_source.value.code == "node_workspace_source_mismatch"


def test_authority_payload_is_path_free_external_and_first_write(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    raw = synthetic_authority.authority_path.read_text(encoding="utf-8")
    assert synthetic_authority.authority_path.parent == synthetic_authority.root.parent
    assert synthetic_authority.authority_path.stat().st_mode & 0o777 == 0o600
    assert str(synthetic_authority.root) not in raw
    assert "/Users/" not in raw
    assert "runtime_root" not in raw
    assert "launcher_dir" not in raw
    with pytest.raises(workspace.NodeWorkspaceError) as existing:
        workspace.capture_authority(
            synthetic_authority.root,
            synthetic_authority.authority_path,
            source_sha=synthetic_authority.source_sha,
        )
    assert existing.value.code == "node_workspace_authority_target_exists"

    inside = synthetic_authority.root / "authority.json"
    with pytest.raises(workspace.NodeWorkspaceError) as inside_subject:
        workspace.capture_authority(
            synthetic_authority.root, inside, source_sha=synthetic_authority.source_sha
        )
    assert inside_subject.value.code == "node_workspace_authority_target_inside_subject"


def test_capture_requires_clean_exact_git_head_before_install(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_calls = 0

    def forbidden_install(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal install_calls
        install_calls += 1
        raise AssertionError("npm install must not run before Git source verification")

    monkeypatch.setattr(workspace, "_install", forbidden_install)

    dirty = _copy_workspace(synthetic_authority.root, tmp_path / "dirty")
    (dirty / "untracked.txt").write_text("untracked", encoding="utf-8")
    with pytest.raises(workspace.NodeWorkspaceError) as dirty_error:
        workspace.capture_authority(
            dirty,
            tmp_path / "dirty-authority.json",
            source_sha=synthetic_authority.source_sha,
        )
    assert dirty_error.value.code == "node_workspace_capture_source_dirty"

    tracked_dirty = _copy_workspace(
        synthetic_authority.root, tmp_path / "tracked-dirty"
    )
    package_path = tracked_dirty / workspace.PACKAGE_RELATIVE
    package_path.write_bytes(package_path.read_bytes() + b"\n")
    with pytest.raises(workspace.NodeWorkspaceError) as tracked_error:
        workspace.capture_authority(
            tracked_dirty,
            tmp_path / "tracked-dirty-authority.json",
            source_sha=synthetic_authority.source_sha,
        )
    assert tracked_error.value.code == "node_workspace_capture_source_dirty"

    wrong_head = _copy_workspace(synthetic_authority.root, tmp_path / "wrong-head")
    with pytest.raises(workspace.NodeWorkspaceError) as head_error:
        workspace.capture_authority(
            wrong_head,
            tmp_path / "wrong-head-authority.json",
            source_sha="b" * 40,
        )
    assert head_error.value.code == "node_workspace_capture_source_mismatch"

    no_git = _copy_workspace(synthetic_authority.root, tmp_path / "no-git")
    shutil.rmtree(no_git / ".git")
    with pytest.raises(workspace.NodeWorkspaceError) as git_error:
        workspace.capture_authority(
            no_git,
            tmp_path / "no-git-authority.json",
            source_sha=synthetic_authority.source_sha,
        )
    assert git_error.value.code == "node_workspace_capture_git_invalid"

    missing_source = _copy_workspace(
        synthetic_authority.root, tmp_path / "missing-source"
    )
    with pytest.raises(workspace.NodeWorkspaceError) as source_error:
        workspace.capture_authority(
            missing_source,
            tmp_path / "missing-source-authority.json",
        )
    assert source_error.value.code == "node_workspace_source_required"
    assert install_calls == 0


def test_policy_authority_and_tree_divergence_are_rejected(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "package-drift")
    package = consumer / workspace.PACKAGE_RELATIVE
    package.write_bytes(package.read_bytes() + b"\n")
    with pytest.raises(workspace.NodeWorkspaceError, match="differs"):
        _verify(consumer, synthetic_authority)

    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "policy-drift")
    policy_path = consumer / workspace.MANIFEST_RELATIVE
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["policy_sha256"] = "0" * 64
    _write_json(policy_path, policy)
    with pytest.raises(workspace.NodeWorkspaceError, match="stale or incomplete"):
        _verify(consumer, synthetic_authority)

    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "authority-drift")
    changed_authority = dict(synthetic_authority.authority)
    changed_authority["policy_sha256"] = "f" * 64
    changed_sha = workspace.authority_identity_sha256(changed_authority)
    with pytest.raises(workspace.NodeWorkspaceError) as authority_error:
        workspace.verify_workspace(
            consumer,
            changed_authority,
            changed_sha,
            source_sha=synthetic_authority.source_sha,
        )
    assert authority_error.value.code == "node_workspace_authority_mismatch"

    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "tree-drift")
    (consumer / workspace.NODE_MODULES_RELATIVE / "drift").write_text(
        "drift", encoding="utf-8"
    )
    with pytest.raises(workspace.NodeWorkspaceError) as tree_error:
        _verify(consumer, synthetic_authority)
    assert tree_error.value.code == "node_workspace_tree_mismatch"


@pytest.mark.parametrize(
    "relative",
    [
        workspace.PACKAGE_RELATIVE,
        workspace.PACKAGE_LOCK_RELATIVE,
        workspace.MANIFEST_RELATIVE,
    ],
)
def test_portable_node_inputs_reject_hardlink_aliases(
    synthetic_authority: SyntheticAuthority, tmp_path: Path, relative: Path
) -> None:
    consumer = _copy_workspace(
        synthetic_authority.root, tmp_path / relative.name.replace(".", "-")
    )
    os.link(consumer / relative, tmp_path / f"outside-{relative.name}")

    with pytest.raises(workspace.NodeWorkspaceError) as captured:
        if relative == workspace.MANIFEST_RELATIVE:
            workspace.load_policy(consumer)
        else:
            workspace.build_policy(consumer)

    assert captured.value.code == "node_workspace_unsafe_hardlink"


def test_capture_rejects_executable_local_git_configuration_before_install(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    subprocess.run(
        ["git", "config", "--local", "core.fsmonitor", "/tmp/never-run"],
        cwd=consumer,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    install_calls = 0

    def forbidden_install(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal install_calls
        install_calls += 1
        raise AssertionError("install must not run before local Git config audit")

    monkeypatch.setattr(workspace, "_install", forbidden_install)
    with pytest.raises(workspace.NodeWorkspaceError) as captured:
        workspace.capture_authority(
            consumer,
            tmp_path / "unsafe-git-authority.json",
            source_sha=synthetic_authority.source_sha,
        )

    assert captured.value.code == "node_workspace_capture_git_invalid"
    assert install_calls == 0


def test_external_authority_rejects_hardlink_alias(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    authority = tmp_path / "authority.json"
    shutil.copy2(synthetic_authority.authority_path, authority)
    os.link(authority, tmp_path / "authority-alias.json")

    with pytest.raises(workspace.NodeWorkspaceError) as captured:
        workspace.load_authority(authority)

    assert captured.value.code == "node_workspace_unsafe_hardlink"


def test_unknown_script_or_arguments_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    with pytest.raises(workspace.NodeWorkspaceError, match="outside certified policy"):
        _run(consumer, synthetic_authority, "dev", [])
    with pytest.raises(workspace.NodeWorkspaceError, match="outside certified policy"):
        _run(consumer, synthetic_authority, "test", ["--config=untrusted.ts"])


def test_fake_npm_or_node_on_path_is_rejected(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    real_path = os.environ.get("PATH", "")
    fake_npm = tmp_path / "fake-npm/bin"
    fake_npm.mkdir(parents=True)
    (fake_npm / "npm").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_npm / "npm").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_npm) + os.pathsep + real_path)
    with pytest.raises(workspace.NodeWorkspaceError):
        _verify(consumer, synthetic_authority)

    fake_node = tmp_path / "fake-node/runtime/bin"
    fake_node.mkdir(parents=True)
    (fake_node / "node").write_text("#!/bin/sh\necho v22.22.3\n", encoding="utf-8")
    (fake_node / "node").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_node) + os.pathsep + real_path)
    with pytest.raises(workspace.NodeWorkspaceError, match="differs"):
        _verify(consumer, synthetic_authority)


def test_platform_change_is_rejected(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    monkeypatch.setattr(workspace.platform, "machine", lambda: "synthetic-other-arch")
    with pytest.raises(workspace.NodeWorkspaceError, match="differs"):
        _verify(consumer, synthetic_authority)


def test_parent_symlink_and_post_command_dependency_drift_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    escaped = tmp_path / "escaped"
    shutil.copytree(synthetic_authority.root / "apps", escaped)
    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / "apps").symlink_to(escaped, target_is_directory=True)
    with pytest.raises(workspace.NodeWorkspaceError, match="boundary"):
        workspace.build_policy(symlinked)

    drifting = _synthetic_workspace(
        tmp_path / "drifting",
        build_command=(
            "node -e \"require('fs').writeFileSync('node_modules/drift','x')\""
        ),
    )
    with pytest.raises(workspace.NodeWorkspaceError, match="changed the certified"):
        _run(drifting.root, drifting, "build", [])


def test_dependency_symlink_escape_and_broken_target_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    escaping = _copy_workspace(synthetic_authority.root, tmp_path / "escaping")
    dependency_root = escaping / workspace.NODE_MODULES_RELATIVE
    (dependency_root / "escape").symlink_to(os.path.relpath(outside, dependency_root))
    with pytest.raises(workspace.NodeWorkspaceError, match="escaping or broken"):
        _verify(escaping, synthetic_authority)

    broken = _copy_workspace(synthetic_authority.root, tmp_path / "broken")
    (broken / workspace.NODE_MODULES_RELATIVE / "broken").symlink_to("missing-target")
    with pytest.raises(workspace.NodeWorkspaceError, match="escaping or broken"):
        _verify(broken, synthetic_authority)


def test_dependency_hardlink_is_rejected(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "hardlinked")
    dependency_file = (
        consumer / workspace.NODE_MODULES_RELATIVE / "picocolors" / "package.json"
    )
    outside_alias = tmp_path / "outside-alias.json"
    os.link(dependency_file, outside_alias)
    with pytest.raises(workspace.NodeWorkspaceError) as hardlink_error:
        _verify(consumer, synthetic_authority)
    assert hardlink_error.value.code == "node_workspace_unsafe_hardlink"


def test_node_modules_root_symlink_is_rejected_before_install(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_calls = 0
    capture_subject = _synthetic_workspace(tmp_path / "capture-subject")

    def forbidden_install(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal install_calls
        install_calls += 1
        raise AssertionError("npm install must not run for an unsafe tree root")

    monkeypatch.setattr(workspace, "_install", forbidden_install)
    outside = tmp_path / "outside-node-modules"
    outside.mkdir()

    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    shutil.rmtree(consumer / workspace.NODE_MODULES_RELATIVE)
    (consumer / workspace.NODE_MODULES_RELATIVE).symlink_to(
        outside, target_is_directory=True
    )
    with pytest.raises(workspace.NodeWorkspaceError) as materialize_error:
        _materialize(consumer, synthetic_authority)
    assert materialize_error.value.code == "node_workspace_tree_root_unsafe"

    shutil.rmtree(capture_subject.root / workspace.NODE_MODULES_RELATIVE)
    (capture_subject.root / workspace.NODE_MODULES_RELATIVE).symlink_to(
        outside, target_is_directory=True
    )
    with pytest.raises(workspace.NodeWorkspaceError) as capture_error:
        workspace.capture_authority(
            capture_subject.root,
            tmp_path / "unsafe-capture-authority.json",
            source_sha=capture_subject.source_sha,
        )
    assert capture_error.value.code == "node_workspace_tree_root_unsafe"
    assert install_calls == 0


def test_command_environment_drops_host_secrets_and_node_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _synthetic_workspace(
        tmp_path / "subject",
        build_command=(
            'node -e "process.stdout.write(JSON.stringify({'
            "secret:process.env.SECRET_TOKEN||'',"
            "nodeOptions:process.env.NODE_OPTIONS||'',"
            "authority:process.env.WIKI_VIVA_NODE_WORKSPACE_AUTHORITY||'',"
            "cockpitToken:process.env.WIKI_COCKPIT_API_TOKEN||'',"
            "expectedRepo:process.env.WIKI_COCKPIT_EXPECT_REPO_ID||'',"
            "path:process.env.PATH||''}))\""
        ),
    )
    hostile = tmp_path / "host-tools"
    hostile.mkdir()
    monkeypatch.setenv("SECRET_TOKEN", "must-not-reach-node")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/private/host/injection.js")
    monkeypatch.setenv("npm_config_registry", "https://private.invalid/")
    monkeypatch.setenv(
        "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY", "/private/host/authority.json"
    )
    monkeypatch.setenv("WIKI_COCKPIT_API_TOKEN", "must-not-reach-node")
    monkeypatch.setenv("WIKI_COCKPIT_EXPECT_REPO_ID", "public-synthetic")
    monkeypatch.setenv("PATH", str(hostile) + os.pathsep + os.environ["PATH"])

    result = _run(subject.root, subject, "build", [])
    payload = json.loads(result.output.decode("utf-8").splitlines()[-1])
    assert payload["secret"] == ""
    assert payload["nodeOptions"] == ""
    assert payload["authority"] == ""
    assert payload["cockpitToken"] == ""
    assert payload["expectedRepo"] == "public-synthetic"
    assert str(hostile) not in payload["path"]
    assert payload["path"].endswith("/usr/bin:/bin")


def test_materialize_rechecks_static_authority_after_install_error(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    shutil.rmtree(consumer / workspace.NODE_MODULES_RELATIVE)
    original_run = workspace._run_bounded

    def fail_install(*args, **kwargs):  # type: ignore[no-untyped-def]
        argv = list(args[0]) if args else list(kwargs["argv"])
        if "ci" in argv:
            package = consumer / workspace.PACKAGE_RELATIVE
            package.write_bytes(package.read_bytes() + b"\n")
            raise workspace.NodeWorkspaceError(
                "synthetic_install_failure",
                "synthetic install failed",
                next_action="restore the subject",
            )
        return original_run(*args, **kwargs)

    monkeypatch.setattr(workspace, "_run_bounded", fail_install)
    with pytest.raises(workspace.NodeWorkspaceError, match="differs"):
        _materialize(consumer, synthetic_authority)


def test_command_output_limit_still_rechecks_post_command_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = _synthetic_workspace(
        tmp_path / "subject",
        build_command=(
            "node -e \"const fs=require('fs');"
            "fs.appendFileSync('package.json','\\n');"
            "process.stdout.write('x'.repeat(4096))\""
        ),
    )
    monkeypatch.setattr(workspace, "MAX_COMMAND_OUTPUT_BYTES", 1024)
    with pytest.raises(workspace.NodeWorkspaceError, match="differs"):
        _run(subject.root, subject, "build", [])


def test_preview_process_spec_uses_certified_runtime_and_safe_environment(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    spec = workspace.preview_process_spec(
        consumer,
        5205,
        synthetic_authority.authority_path,
        synthetic_authority.authority_sha256,
        source_sha=synthetic_authority.source_sha,
    )
    assert spec.argv[0] == workspace.resolved_node_authority()["executable"]
    assert spec.argv[1] == workspace.resolved_npm_authority()["executable"]
    assert spec.argv[-3:] == ("--port", "5205", "--strictPort")
    assert spec.cwd == consumer
    assert "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY" not in spec.environment
    assert "NODE_OPTIONS" not in spec.environment
    with pytest.raises(workspace.NodeWorkspaceError, match="port"):
        workspace.preview_process_spec(
            consumer,
            80,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha=synthetic_authority.source_sha,
        )


def test_certified_preview_process_controls_group_and_rechecks_tree(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    real_popen = subprocess.Popen
    invocations: list[tuple[list[str], dict[str, object]]] = []

    def recording_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        invocations.append((list(args[0]), dict(kwargs)))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(workspace.subprocess, "Popen", recording_popen)
    with pytest.raises(workspace.NodeWorkspaceError) as post_error:
        with workspace.certified_preview_process(
            consumer,
            5205,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha=synthetic_authority.source_sha,
        ) as process:
            assert process.pid > 0
            (consumer / workspace.NODE_MODULES_RELATIVE / "preview-drift").write_text(
                "drift", encoding="utf-8"
            )
    assert post_error.value.code == "node_workspace_tree_mismatch"
    preview_invocations = [
        options for argv, options in invocations if "preview" in argv
    ]
    assert len(preview_invocations) == 1
    assert preview_invocations[0]["start_new_session"] is True


def test_certified_preview_process_rejects_exit_before_controlled_teardown(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    monkeypatch.setattr(
        workspace,
        "preview_process_spec",
        lambda *_args, **_kwargs: workspace.ProcessSpec(
            argv=("/usr/bin/true",),
            cwd=consumer,
            environment={},
        ),
    )

    with pytest.raises(workspace.NodeWorkspaceError) as captured:
        with workspace.certified_preview_process(
            consumer,
            5205,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha=synthetic_authority.source_sha,
        ) as process:
            assert process.wait(timeout=5) == 0

    assert captured.value.code == "node_workspace_preview_exited"


def test_preview_teardown_error_still_postchecks_and_releases_lock(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    real_lock = workspace._workspace_lock
    real_terminate = workspace._terminate_process_group
    lock_descriptors: list[int] = []

    def recording_lock(root: Path) -> int:
        descriptor = real_lock(root)
        lock_descriptors.append(descriptor)
        return descriptor

    def timed_out_teardown(process: subprocess.Popen[bytes]) -> None:
        real_terminate(process)
        raise subprocess.TimeoutExpired(cmd="certified preview", timeout=5)

    monkeypatch.setattr(workspace, "_workspace_lock", recording_lock)
    monkeypatch.setattr(workspace, "_terminate_process_group", timed_out_teardown)
    monkeypatch.setattr(
        workspace,
        "preview_process_spec",
        lambda *_args, **_kwargs: workspace.ProcessSpec(
            argv=("/bin/sleep", "60"),
            cwd=consumer,
            environment={},
        ),
    )

    with pytest.raises(workspace.NodeWorkspaceError) as captured:
        with workspace.certified_preview_process(
            consumer,
            5205,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha=synthetic_authority.source_sha,
        ):
            (consumer / workspace.NODE_MODULES_RELATIVE / "preview-drift").write_text(
                "drift", encoding="utf-8"
            )

    assert captured.value.code == "node_workspace_tree_mismatch"
    assert len(lock_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(lock_descriptors[0])
    descriptor = real_lock(consumer)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def test_preview_teardown_error_does_not_mask_body_exception(
    synthetic_authority: SyntheticAuthority,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    real_terminate = workspace._terminate_process_group
    body_error = RuntimeError("capture body failed")

    def timed_out_teardown(process: subprocess.Popen[bytes]) -> None:
        real_terminate(process)
        raise subprocess.TimeoutExpired(cmd="certified preview", timeout=5)

    monkeypatch.setattr(workspace, "_terminate_process_group", timed_out_teardown)
    monkeypatch.setattr(
        workspace,
        "preview_process_spec",
        lambda *_args, **_kwargs: workspace.ProcessSpec(
            argv=("/bin/sleep", "60"),
            cwd=consumer,
            environment={},
        ),
    )

    with pytest.raises(RuntimeError) as captured:
        with workspace.certified_preview_process(
            consumer,
            5205,
            synthetic_authority.authority_path,
            synthetic_authority.authority_sha256,
            source_sha=synthetic_authority.source_sha,
        ):
            raise body_error

    assert captured.value is body_error


def test_cli_env_bindings_and_conflicts_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    environment = dict(os.environ)
    environment.update(
        {
            "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY": str(
                synthetic_authority.authority_path
            ),
            "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256": synthetic_authority.authority_sha256,
            "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA": synthetic_authority.source_sha,
        }
    )
    command = [
        sys.executable,
        str(ROOT / "scripts/wiki_node_workspace.py"),
        "--root",
        str(consumer),
        "check",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert (
        json.loads(completed.stdout)["authority_sha256"]
        == synthetic_authority.authority_sha256
    )

    completed = subprocess.run(
        [*command, "--authority", str(tmp_path / "different.json")],
        cwd=ROOT,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 2
    assert (
        json.loads(completed.stderr)["error_code"]
        == "node_workspace_authority_binding_conflict"
    )
    assert str(tmp_path) not in completed.stderr


def test_legacy_manifest_and_serialization_lock_fail_closed(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    legacy = _copy_workspace(synthetic_authority.root, tmp_path / "legacy")
    _write_json(
        legacy / workspace.MANIFEST_RELATIVE,
        {"schema_version": workspace.LEGACY_MANIFEST_SCHEMA_VERSION},
    )
    with pytest.raises(workspace.NodeWorkspaceError) as legacy_error:
        _verify(legacy, synthetic_authority)
    assert legacy_error.value.code == "node_workspace_legacy_manifest_rejected"

    consumer = _copy_workspace(synthetic_authority.root, tmp_path / "consumer")
    lock_key = workspace.hashlib.sha256(
        str(consumer.resolve()).encode("utf-8")
    ).hexdigest()[:24]
    lock_path = (
        Path(tempfile.gettempdir()) / f"wiki-viva-node-workspace-{lock_key}.lock"
    )
    lock_path.unlink(missing_ok=True)
    lock_path.symlink_to(tmp_path / "outside-lock")
    try:
        with pytest.raises(workspace.NodeWorkspaceError, match="lock"):
            _materialize(consumer, synthetic_authority)
    finally:
        lock_path.unlink(missing_ok=True)


def test_timeout_terminates_the_complete_process_group(tmp_path: Path) -> None:
    authority = workspace.resolved_node_authority()
    pid_path = tmp_path / "child.pid"
    program = (
        "const {spawn}=require('child_process');"
        "const fs=require('fs');"
        "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],"
        "{stdio:'ignore'});"
        "fs.writeFileSync(process.argv[1],String(child.pid));"
        "setInterval(()=>{},1000);"
    )
    with pytest.raises(workspace.NodeWorkspaceError, match="synthetic timeout"):
        workspace._run_bounded(
            [str(authority["executable"]), "-e", program, str(pid_path)],
            cwd=tmp_path,
            env={"PATH": str(Path(authority["executable"]).parent)},
            timeout=1,
            output_limit=1024,
            timeout_error=(
                "synthetic_timeout",
                "synthetic timeout",
                "inspect the test",
            ),
            output_error=("synthetic_output", "synthetic output", "inspect the test"),
        )
    child_pid = int(pid_path.read_text(encoding="ascii"))
    for _attempt in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("timed out descendant survived process-group termination")


def test_normal_success_terminates_unref_stdio_ignored_descendant(
    tmp_path: Path,
) -> None:
    authority = workspace.resolved_node_authority()
    pid_path = tmp_path / "child.pid"
    program = (
        "const {spawn}=require('child_process');"
        "const fs=require('fs');"
        "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],"
        "{stdio:'ignore'});"
        "child.unref();"
        "fs.writeFileSync(process.argv[1],String(child.pid));"
        "process.stdout.write('verified');"
    )

    result = workspace._run_bounded(
        [str(authority["executable"]), "-e", program, str(pid_path)],
        cwd=tmp_path,
        env={"PATH": str(Path(authority["executable"]).parent)},
        timeout=5,
        output_limit=1024,
        timeout_error=("synthetic_timeout", "synthetic timeout", "inspect the test"),
        output_error=("synthetic_output", "synthetic output", "inspect the test"),
    )

    assert result.returncode == 0
    assert result.output == b"verified"
    child_pid = int(pid_path.read_text(encoding="ascii"))
    for _attempt in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("successful descendant survived process-group termination")


def test_normal_success_terminates_descendant_holding_stdout_open(
    tmp_path: Path,
) -> None:
    authority = workspace.resolved_node_authority()
    pid_path = tmp_path / "child.pid"
    program = (
        "const {spawn}=require('child_process');"
        "const fs=require('fs');"
        "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],"
        "{stdio:['ignore',1,2]});"
        "child.unref();"
        "fs.writeFileSync(process.argv[1],String(child.pid));"
        "process.stdout.write('verified');"
    )
    started = time.monotonic()

    result = workspace._run_bounded(
        [str(authority["executable"]), "-e", program, str(pid_path)],
        cwd=tmp_path,
        env={"PATH": str(Path(authority["executable"]).parent)},
        timeout=5,
        output_limit=1024,
        timeout_error=("synthetic_timeout", "synthetic timeout", "inspect the test"),
        output_error=("synthetic_output", "synthetic output", "inspect the test"),
    )

    assert time.monotonic() - started < 3
    assert result.returncode == 0
    assert result.output == b"verified"
    child_pid = int(pid_path.read_text(encoding="ascii"))
    for _attempt in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("stdout-holding descendant survived process-group termination")


def test_normal_success_terminates_detached_descendant_outside_parent_pgid(
    tmp_path: Path,
) -> None:
    authority = workspace.resolved_node_authority()
    pid_path = tmp_path / "child.pid"
    program = (
        "const {spawn}=require('child_process');"
        "const fs=require('fs');"
        "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],"
        "{detached:true,stdio:'ignore'});"
        "child.unref();"
        "fs.writeFileSync(process.argv[1],String(child.pid));"
        "process.stdout.write('verified');"
    )

    result = workspace._run_bounded(
        [str(authority["executable"]), "-e", program, str(pid_path)],
        cwd=tmp_path,
        env={"PATH": str(Path(authority["executable"]).parent)},
        timeout=5,
        output_limit=1024,
        timeout_error=("synthetic_timeout", "synthetic timeout", "inspect the test"),
        output_error=("synthetic_output", "synthetic output", "inspect the test"),
    )

    assert result.returncode == 0
    assert result.output == b"verified"
    child_pid = int(pid_path.read_text(encoding="ascii"))
    for _attempt in range(30):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("detached descendant survived marked process-tree termination")


def test_cli_symlink_root_fails_closed_without_path_leak(
    synthetic_authority: SyntheticAuthority, tmp_path: Path
) -> None:
    symlink_root = tmp_path / "symlink-root"
    symlink_root.symlink_to(synthetic_authority.root, target_is_directory=True)
    environment = dict(os.environ)
    environment.update(
        {
            "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY": str(
                synthetic_authority.authority_path
            ),
            "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256": synthetic_authority.authority_sha256,
            "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA": synthetic_authority.source_sha,
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_node_workspace.py"),
            "--root",
            str(symlink_root),
            "check",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stderr)
    assert payload["error_code"] == "node_workspace_root_unsafe"
    assert str(tmp_path) not in completed.stderr
