#!/usr/bin/env python3
"""Emit public, canonical identities for the upgrade certification toolchain."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _python_payload() -> dict[str, Any]:
    import platform

    entries = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "")
                .strip()
                .lower()
                .replace("_", "-"),
                str(distribution.version).strip(),
            )
            for distribution in metadata.distributions()
            if str(distribution.metadata.get("Name") or "").strip()
            and str(distribution.version).strip()
        }
    )
    dependencies = [
        {"name": name, "version": version} for name, version in entries
    ]
    return {
        "schema_version": "wiki_viva_python_resolved_toolchain.v1",
        "implementation": platform.python_implementation().lower(),
        "python_version": platform.python_version(),
        "dependencies": dependencies,
        "dependencies_sha256": hashlib.sha256(
            _canonical_bytes(dependencies)
        ).hexdigest(),
    }


def _node_playwright_module() -> Path | None:
    candidates = [ROOT / "apps/wiki-cockpit/node_modules/playwright"]
    executable = shutil.which("playwright")
    if executable:
        resolved = Path(executable).resolve()
        for parent in (resolved.parent, *resolved.parents):
            if parent.name == "node_modules":
                candidates.append(parent / "playwright")
                break
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "package.json").is_file():
            return candidate.resolve(strict=True)
    return None


def _browser_payload() -> dict[str, str]:
    module_root = _node_playwright_module()
    if module_root is not None:
        program = (
            "const p=require(process.argv[1]);"
            "const j=require(process.argv[1]+'/package.json');"
            "(async()=>{const b=await p.chromium.launch({headless:true});"
            "const x={schema_version:'wiki_viva_browser_engine_toolchain.v1',"
            "browser:'chromium',browser_version:b.version(),"
            "playwright_version:j.version};await b.close();"
            "process.stdout.write(JSON.stringify(x));})()"
            ".catch((e)=>{process.stderr.write(String(e));process.exit(2);});"
        )
        result = subprocess.run(
            ["node", "-e", program, "./playwright"],
            cwd=module_root.parent,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError("Node Playwright browser probe failed")
        payload = json.loads(result.stdout.decode("utf-8", "strict"))
    else:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            payload = {
                "schema_version": "wiki_viva_browser_engine_toolchain.v1",
                "browser": "chromium",
                "browser_version": browser.version,
                "playwright_version": metadata.version("playwright"),
            }
            browser.close()
    expected = {
        "schema_version",
        "browser",
        "browser_version",
        "playwright_version",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise RuntimeError("Playwright browser probe returned an invalid payload")
    return {key: str(value) for key, value in payload.items()}


def main(argv: list[str]) -> int:
    if argv == ["python"]:
        payload: Any = _python_payload()
    elif argv == ["browser"]:
        payload = _browser_payload()
    else:
        print("usage: wiki_toolchain_probe.py {python|browser}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(_canonical_bytes(payload) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
