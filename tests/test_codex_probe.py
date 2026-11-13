from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from wiki_core.config import WikiConfig, load_config
from wiki_core.web.codex_probe import probe_codex, probe_codex_for


def _make_shim(path: Path, *, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _runnable_codex(tmp_path: Path) -> Path:
    return _make_shim(tmp_path / "codex", body='#!/bin/sh\necho "codex-cli 0.99.0"\n')


def _broken_codex(tmp_path: Path) -> Path:
    # Mirrors the observed real failure: npm wrapper present, native binary gone.
    return _make_shim(tmp_path / "codex", body='#!/bin/sh\necho "spawn codex ENOENT" >&2\nexit 1\n')


def _auth_home(tmp_path: Path, payload: dict | None) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    if payload is not None:
        (home / "auth.json").write_text(json.dumps(payload), encoding="utf-8")
    return home


def test_probe_absent(tmp_path: Path) -> None:
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(tmp_path / "does-not-exist"), codex_home=home)
    assert record["installed"] is False
    assert record["usable"] is False
    assert "not installed" in record["reason"].lower()
    # Auth can be present even when the binary is missing — reported honestly.
    assert record["authed"] is True


def test_probe_installed_unauthed(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, None)  # no auth.json
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["installed"] is True
    assert record["runnable"] is True
    assert record["authed"] is False
    assert record["usable"] is False
    assert "login" in record["reason"].lower()


def test_probe_authed_usable(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["usable"] is True
    assert record["installed"] is True
    assert record["runnable"] is True
    assert record["authed"] is True
    assert record["auth_mode"] == "chatgpt"
    assert record["version"] == "codex-cli 0.99.0"
    assert record["reason"] == ""


def test_probe_installed_but_broken(tmp_path: Path) -> None:
    binary = _broken_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["installed"] is True
    assert record["runnable"] is False
    assert record["usable"] is False
    assert "not runnable" in record["reason"].lower()


def test_probe_apikey_auth_mode(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"OPENAI_API_KEY": "sk-test"})
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["authed"] is True
    assert record["auth_mode"] == "apikey"
    assert record["usable"] is True


def test_probe_disabled_short_circuits(tmp_path: Path, monkeypatch) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    def forbidden_auth_read(*args, **kwargs):
        raise AssertionError("disabled adapter must not inspect credentials")
    monkeypatch.setattr("wiki_core.web.codex_probe._probe_auth", forbidden_auth_read)
    record = probe_codex(binary=str(binary), codex_home=home, enabled=False)
    assert record["enabled"] is False
    assert record["usable"] is False
    assert "off" in record["reason"].lower()
    # Disabled means we never even claim runnable — pure opt-out.
    assert record["runnable"] is False


def test_probe_corrupt_auth_json_is_unauthed(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{ not json", encoding="utf-8")
    record = probe_codex(binary=str(binary), codex_home=home)
    assert record["authed"] is False
    assert record["usable"] is False


def test_probe_for_config_respects_binary_and_enabled(tmp_path: Path) -> None:
    binary = _runnable_codex(tmp_path)
    home = _auth_home(tmp_path, {"auth_mode": "chatgpt", "tokens": {"access_token": "x"}})
    os.environ["CODEX_HOME"] = str(home)
    try:
        enabled_cfg = WikiConfig(codex={"enabled": True, "binary": str(binary)})
        record = probe_codex_for(enabled_cfg)
        assert record["usable"] is True

        disabled_cfg = WikiConfig(codex={"enabled": False, "binary": str(binary)})
        record = probe_codex_for(disabled_cfg)
        assert record["usable"] is False
        assert record["enabled"] is False
    finally:
        os.environ.pop("CODEX_HOME", None)


@pytest.mark.parametrize("env_value,configured,expected", [
    ("env-binary", "config-binary", "env-binary"),
    ("", "config-binary", "config-binary"),
    (None, "config-binary", "config-binary"),
    (None, "", "codex"),
])
def test_probe_and_runner_share_binary_precedence(tmp_path, monkeypatch, env_value, configured, expected):
    from wiki_core.web.codex_jobs import JobRunner
    import wiki_core.web.codex_probe as module

    if env_value is None:
        monkeypatch.delenv("WIKI_CODEX_BINARY", raising=False)
    else:
        monkeypatch.setenv("WIKI_CODEX_BINARY", env_value)
    monkeypatch.setattr(module, "probe_codex", lambda **kwargs: kwargs)
    config = WikiConfig(repo_id="synthetic", codex={"enabled": True, "binary": configured})
    runner = JobRunner(tmp_path, config, autostart=False, reconcile_retained=False)
    assert Path(runner.codex_cmd[0]).name == expected
    assert probe_codex_for(config)["binary"] == runner.codex_cmd[0]
    # Explicit test/host injection retains its established priority.
    injected = JobRunner(tmp_path, config, codex_cmd=["explicit-shim"], autostart=False, reconcile_retained=False)
    assert injected.codex_cmd == ["explicit-shim"]


@pytest.mark.parametrize("via_path", [False, True])
def test_relative_binary_is_identical_for_probe_and_real_job(tmp_path, monkeypatch, via_path):
    from wiki_core.web.codex_jobs import JobRunner
    import wiki_core.web.codex_probe as module

    operator = tmp_path / "operator"
    wiki = tmp_path / "wiki"
    operator.mkdir()
    wiki.mkdir()
    for directory, marker in ((operator, "operator"), (wiki, "wrong-wiki")):
        _make_shim(directory / "codex", body=f'#!/bin/sh\necho "{marker}"\n')
    monkeypatch.chdir(operator)
    monkeypatch.setenv("WIKI_CODEX_BINARY", "codex" if via_path else "./codex")
    if via_path:
        monkeypatch.setenv("PATH", ".")
    monkeypatch.setattr(module, "_probe_auth", lambda _: (True, "synthetic"))
    config = WikiConfig(repo_id="synthetic", codex={"enabled": True, "binary": "ignored"})
    assert probe_codex_for(config)["version"] == "operator"
    runner = JobRunner(wiki, config, autostart=False, reconcile_retained=False)
    log = tmp_path / "log.jsonl"
    status, cancelled = runner._run_codex("synthetic", runner.codex_cmd, "", log)
    assert status == 0 and not cancelled
    assert log.read_text().strip() == "operator"


def test_config_loads_codex_block(tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        "repo_id: t\ncodex:\n  enabled: false\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.codex_enabled is False
    # Default binary survives a partial override.
    assert config.codex.get("binary") == "codex"


@pytest.mark.parametrize("enabled", [True, False])
def test_config_default_codex_enabled(enabled: bool, tmp_path: Path) -> None:
    (tmp_path / "wiki.config.yaml").write_text(
        f"repo_id: t\ncodex:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8"
    )
    assert load_config(tmp_path).codex_enabled is enabled
