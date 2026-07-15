from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import wiki_toolchain_probe as probe
from wiki_core.process_safety import BoundedProcessResult, ProcessSafetyError


def test_node_browser_probe_uses_bounded_descendant_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "node_modules" / "playwright"
    module.mkdir(parents=True)
    (module / "package.json").write_text("{}\n", encoding="utf-8")
    node = tmp_path / "bin" / "node"
    node.parent.mkdir()
    node.write_text("synthetic\n", encoding="utf-8")
    invocations: list[tuple[list[str], dict[str, object]]] = []
    payload = {
        "schema_version": "wiki_viva_browser_engine_toolchain.v1",
        "browser": "chromium",
        "browser_version": "128.0.0",
        "playwright_version": "1.61.1",
    }

    def bounded(argv, **kwargs):  # type: ignore[no-untyped-def]
        invocations.append((list(argv), dict(kwargs)))
        return BoundedProcessResult(
            returncode=0,
            output=json.dumps(payload, sort_keys=True).encode("utf-8"),
        )

    monkeypatch.setattr(probe, "_node_playwright_module", lambda: module)
    monkeypatch.setattr(probe.shutil, "which", lambda name: str(node))
    monkeypatch.setattr(probe, "run_bounded_process", bounded)

    assert probe._browser_payload() == payload
    assert len(invocations) == 1
    argv, options = invocations[0]
    assert argv[0] == str(node.resolve())
    assert options["timeout"] == 30
    assert options["output_limit"] == 1024 * 1024
    assert options["popen_factory"] is probe.subprocess.Popen


def test_node_browser_probe_maps_process_safety_failure_without_masking_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "node_modules" / "playwright"
    module.mkdir(parents=True)
    (module / "package.json").write_text("{}\n", encoding="utf-8")
    node = tmp_path / "node"
    node.write_text("synthetic\n", encoding="utf-8")
    monkeypatch.setattr(probe, "_node_playwright_module", lambda: module)
    monkeypatch.setattr(probe.shutil, "which", lambda name: str(node))
    monkeypatch.setattr(
        probe,
        "run_bounded_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ProcessSafetyError("timeout", "synthetic timeout")
        ),
    )
    with pytest.raises(RuntimeError, match="Node Playwright browser probe failed"):
        probe._browser_payload()

    failure = KeyboardInterrupt("synthetic interrupt")
    monkeypatch.setattr(
        probe,
        "run_bounded_process",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(KeyboardInterrupt) as captured:
        probe._browser_payload()
    assert captured.value is failure
