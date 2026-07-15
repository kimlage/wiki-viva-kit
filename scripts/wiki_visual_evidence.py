#!/usr/bin/env python3
"""Capture and verify public-synthetic visual evidence for one exact release.

The command deliberately owns the preview server and launches the repository's
installed Playwright Chromium.  It never accepts arbitrary routes or an
already-running server, so a screenshot cannot be relabelled as evidence for a
different source checkout.  Output is create-once and must live outside the
source repository or below an ignored path.

Reverification proves bytes, dimensions, source, package and live toolchain;
it cannot prove that a browser produced a file.  Release authority exists only
when a trusted workflow runs ``capture`` and externally attests the exact
output passed to certification.  No local or test-only flag promotes a bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki_core.release_receipt import (
    ReleaseReceiptError,
    visual_evidence_file_metadata,
)
from wiki_core.git_safety import (
    GitSafetyError,
    require_safe_local_config,
    resolved_git_executable,
    sanitized_git_argv,
    sanitized_git_environment,
)
from wiki_core.node_workspace import (
    NodeWorkspaceError,
    certified_execution_context,
    certified_preview_process,
    run_script,
)
from wiki_core.process_safety import ProcessSafetyError, run_bounded_process
from wiki_core.upgrade import validate_upgrade_package
from wiki_core.upgrade_lanes import (
    VISUAL_PROFILE_CONTRACTS,
    canonical_json,
    canonical_sha256,
    load_mapping,
)


MANIFEST_SCHEMA_VERSION = "wiki_visual_evidence_manifest.v1"
CAPTURE_SCHEMA_VERSION = "wiki_visual_evidence_capture.v2"
CAPTURE_METHOD = "playwright_served_public_synthetic"
MANIFEST_REF = "visual-manifest.json"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_BROWSER_PROBE_OUTPUT_BYTES = 1024 * 1024
MAX_CAPTURE_PROCESS_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_CAPTURE_PROCESS_INPUT_BYTES = 4 * 1024 * 1024
MAX_PERCENT_DECODE_ROUNDS = 3
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
PRIVATE_TOKEN_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:private|consumer|real)(?:$|[^a-z0-9])",
    re.IGNORECASE,
)
SECRET_QUERY_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|password|secret|session|signature|token|api[-_]?key)",
    re.IGNORECASE,
)


PROFILE_SPECS: dict[str, dict[str, Any]] = {
    profile: {**dict(spec), "mobile": profile == "mobile"}
    for profile, spec in VISUAL_PROFILE_CONTRACTS.items()
}


class VisualEvidenceError(ValueError):
    """Fail-closed visual evidence contract error."""


_NODE_AUTHORITY_ENV = "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY"
_NODE_AUTHORITY_SHA_ENV = "WIKI_VIVA_NODE_WORKSPACE_AUTHORITY_SHA256"
_NODE_SOURCE_SHA_ENV = "WIKI_VIVA_NODE_WORKSPACE_SOURCE_SHA"


def _node_workspace_binding(source_root: Path, *, source_sha: str | None = None):
    authority = os.environ.get(_NODE_AUTHORITY_ENV)
    authority_sha256 = os.environ.get(_NODE_AUTHORITY_SHA_ENV)
    carried_source_sha = os.environ.get(_NODE_SOURCE_SHA_ENV)
    if (
        not authority
        or not authority_sha256
        or not carried_source_sha
        or (source_sha is not None and source_sha != carried_source_sha)
    ):
        raise VisualEvidenceError(
            "visual evidence requires the exact capsule-bound Node workspace authority"
        )
    try:
        return certified_execution_context(
            source_root,
            Path(authority),
            authority_sha256,
            source_sha=carried_source_sha,
        )
    except (OSError, NodeWorkspaceError) as exc:
        raise VisualEvidenceError(
            "the capsule-bound Node workspace authority could not be verified"
        ) from exc


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run_git(root: Path, arguments: Sequence[str], *, label: str) -> bytes:
    try:
        executable = resolved_git_executable()
        result = run_bounded_process(
            sanitized_git_argv(arguments, executable=executable),
            cwd=root,
            env=sanitized_git_environment(executable=executable),
            timeout=60,
            output_limit=MAX_GIT_OUTPUT_BYTES,
            stderr=subprocess.DEVNULL,
            popen_factory=subprocess.Popen,
        )
    except (GitSafetyError, OSError, ProcessSafetyError) as exc:
        raise VisualEvidenceError(f"{label} could not be proved from Git") from exc
    if result.returncode != 0:
        raise VisualEvidenceError(f"{label} could not be proved from Git")
    return result.output


def _verify_source(source_root: Path, source_sha: str) -> Path:
    if SHA_RE.fullmatch(source_sha) is None:
        raise VisualEvidenceError("source_sha must be one full lowercase Git SHA")
    try:
        source = source_root.resolve(strict=True)
    except OSError as exc:
        raise VisualEvidenceError("source_root does not exist") from exc
    if (
        not source.is_dir()
        or source_root.is_symlink()
        or _path_has_symlink(Path(os.path.abspath(source_root.expanduser())))
    ):
        raise VisualEvidenceError("source_root must be one real directory")
    try:
        require_safe_local_config(source)
    except GitSafetyError as exc:
        raise VisualEvidenceError(
            "source Git configuration contains executable policy"
        ) from exc
    top = (
        _run_git(source, ["rev-parse", "--show-toplevel"], label="source root")
        .decode("utf-8", "strict")
        .strip()
    )
    if Path(top).resolve() != source:
        raise VisualEvidenceError("source_root must be the exact Git repository root")
    resolved = (
        _run_git(
            source,
            ["rev-parse", "--verify", f"{source_sha}^{{commit}}"],
            label="source commit",
        )
        .decode("ascii", "strict")
        .strip()
    )
    head = (
        _run_git(source, ["rev-parse", "HEAD"], label="source HEAD")
        .decode("ascii", "strict")
        .strip()
    )
    if resolved != source_sha or head != source_sha:
        raise VisualEvidenceError(
            "source_root must be checked out at the exact source_sha"
        )
    if _run_git(
        source,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        label="source cleanliness",
    ):
        raise VisualEvidenceError("source_root must be clean before visual capture")
    return source


def _package_contract(
    package: Mapping[str, Any], *, source_sha: str, strict: bool = True
) -> tuple[list[str], str]:
    if strict:
        errors = validate_upgrade_package(dict(package))
        if errors:
            raise VisualEvidenceError(
                "upgrade package is not semantically valid for visual capture"
            )
    release = package.get("release")
    migration = package.get("migration")
    profiles = (
        migration.get("visual_profiles") if isinstance(migration, Mapping) else None
    )
    if (
        not isinstance(release, Mapping)
        or release.get("source_sha") != source_sha
        or not isinstance(profiles, list)
        or not profiles
        or len(profiles) != len(set(profiles))
        or any(
            not isinstance(profile, str) or ID_RE.fullmatch(profile) is None
            for profile in profiles
        )
    ):
        raise VisualEvidenceError(
            "package source_sha and visual_profiles must be exact and unique"
        )
    unsupported = sorted(set(profiles) - set(PROFILE_SPECS))
    if unsupported:
        raise VisualEvidenceError(
            "package declares a visual profile without a versioned capture contract"
        )
    return [str(profile) for profile in profiles], canonical_sha256(package)


def _canonical_relative_path(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value.startswith(("/", "~"))
        or "\\" in value
        or "//" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise VisualEvidenceError(f"{label} must be one canonical relative path")
    return value


def _public_demo_route(value: object, *, label: str = "route") -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise VisualEvidenceError(f"{label} must be a bounded public demo route")
    views = [value]
    current = value
    for _ in range(MAX_PERCENT_DECODE_ROUNDS):
        if re.search(r"%[0-9A-Fa-f]{2}", current) is None:
            break
        try:
            decoded = urllib.parse.unquote_to_bytes(current).decode("utf-8", "strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise VisualEvidenceError(
                f"{label} contains invalid percent encoding"
            ) from exc
        if decoded == current:
            break
        views.append(decoded)
        current = decoded
    if re.search(r"%[0-9A-Fa-f]{2}", current) is not None:
        raise VisualEvidenceError(f"{label} exceeds the percent-decoding bound")
    for view in views:
        parsed = urllib.parse.urlsplit(view)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or not (parsed.path == "/demo" or parsed.path.startswith("/demo/"))
            or PRIVATE_TOKEN_RE.search(view)
        ):
            raise VisualEvidenceError(f"{label} is not a public-synthetic /demo route")
        for key, item in urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True, strict_parsing=False
        ):
            if SECRET_QUERY_KEY_RE.search(key) or PRIVATE_TOKEN_RE.search(item):
                raise VisualEvidenceError(
                    f"{label} contains private or credential-shaped query state"
                )
    return value


def _path_has_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if os.path.lexists(current) and current.is_symlink():
            return True
    return False


def _output_path(raw: Path, *, source_root: Path, must_exist: bool) -> Path:
    expanded = raw.expanduser()
    if any(
        part in {"", ".", ".."} for part in expanded.parts if part != expanded.anchor
    ):
        raise VisualEvidenceError("visual output path must be canonical")
    absolute = Path(os.path.abspath(expanded))
    if any(part in {"", ".", ".."} for part in absolute.parts[1:]):
        raise VisualEvidenceError("visual output path must be canonical")
    if _path_has_symlink(absolute):
        raise VisualEvidenceError("visual output path must not traverse a symlink")
    exists = os.path.lexists(absolute)
    if must_exist and not exists:
        raise VisualEvidenceError("visual output directory is missing")
    if not must_exist and exists:
        raise VisualEvidenceError(
            "visual output already exists; evidence is create-once"
        )
    if must_exist and (not absolute.is_dir() or absolute.is_symlink()):
        raise VisualEvidenceError("visual output must be one real directory")
    parent = absolute if must_exist else absolute.parent
    try:
        parent.resolve(strict=True)
    except OSError as exc:
        raise VisualEvidenceError("visual output parent is missing") from exc
    try:
        relative = absolute.relative_to(source_root)
    except ValueError:
        return absolute
    if relative == Path("."):
        raise VisualEvidenceError("visual output cannot be the source repository")
    try:
        executable = resolved_git_executable()
        result = run_bounded_process(
            sanitized_git_argv(
                [
                    "check-ignore",
                    "--no-index",
                    "--quiet",
                    "--",
                    relative.as_posix(),
                ],
                executable=executable,
            ),
            cwd=source_root,
            env=sanitized_git_environment(executable=executable),
            stderr=subprocess.DEVNULL,
            timeout=30,
            output_limit=1024,
            popen_factory=subprocess.Popen,
        )
    except (GitSafetyError, OSError, ProcessSafetyError) as exc:
        raise VisualEvidenceError(
            "visual output Git ignore policy could not be verified"
        ) from exc
    if result.returncode != 0:
        raise VisualEvidenceError(
            "visual output inside the source repository must be gitignored"
        )
    return absolute


def _read_regular(root: Path, relative: object, *, label: str) -> bytes:
    if os.name == "nt":
        raise VisualEvidenceError(
            "visual evidence verification requires descriptor-pinned POSIX reads"
        )
    normalized = _canonical_relative_path(relative, label=f"{label} path")
    parts = Path(normalized).parts
    root = root.resolve(strict=True)
    opened: list[int] = []
    descriptor: int | None = None
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=descriptor,
            )
            opened.append(descriptor)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise VisualEvidenceError(
                f"{label} must be one regular, non-hard-linked file"
            )
        if before.st_size > MAX_FILE_BYTES:
            raise VisualEvidenceError(f"{label} exceeds the evidence size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_FILE_BYTES + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise VisualEvidenceError(f"{label} exceeds the evidence size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_nlink,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise VisualEvidenceError(f"{label} changed while it was read")
        return b"".join(chunks)
    except VisualEvidenceError:
        raise
    except OSError as exc:
        raise VisualEvidenceError(
            f"{label} could not be opened without symlink traversal"
        ) from exc
    finally:
        for handle in reversed(opened):
            try:
                os.close(handle)
            except OSError:
                pass


def _write_exclusive(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise VisualEvidenceError("visual evidence output is not create-once") from exc
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _node_playwright_module(source_root: Path) -> Path:
    candidate = source_root / "apps/wiki-cockpit/node_modules/playwright"
    if not candidate.is_dir() or not (candidate / "package.json").is_file():
        raise VisualEvidenceError(
            "the exact source checkout has no installed Playwright module"
        )
    return candidate.resolve(strict=True)


_BROWSER_PROBE = r"""
const path = require('path');
const moduleRoot = process.argv[1];
const playwright = require(moduleRoot);
const packageJson = require(path.join(moduleRoot, 'package.json'));
(async () => {
  const browser = await playwright.chromium.launch({headless: true});
  const payload = {
    name: 'playwright-chromium',
    version: `${packageJson.version}+chromium.${browser.version()}`
  };
  await browser.close();
  process.stdout.write(JSON.stringify(payload));
})().catch(() => process.exit(2));
""".strip()


def _probe_browser_toolchain(
    source_root: Path, *, source_sha: str | None = None
) -> dict[str, str]:
    module = _node_playwright_module(source_root)
    context = _node_workspace_binding(source_root, source_sha=source_sha)
    try:
        result = run_bounded_process(
            [str(context.node["executable"]), "-e", _BROWSER_PROBE, str(module)],
            cwd=source_root,
            env=context.environment,
            timeout=45,
            output_limit=MAX_BROWSER_PROBE_OUTPUT_BYTES,
            popen_factory=subprocess.Popen,
        )
    except (OSError, ProcessSafetyError) as exc:
        raise VisualEvidenceError("Playwright Chromium toolchain probe failed") from exc
    if result.returncode != 0:
        raise VisualEvidenceError("Playwright Chromium toolchain probe failed")
    try:
        payload = json.loads(result.output.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError(
            "Playwright Chromium probe was not canonical"
        ) from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"name", "version"}
        or payload.get("name") != "playwright-chromium"
        or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", str(payload.get("version") or "")
        )
        is None
    ):
        raise VisualEvidenceError("Playwright Chromium probe was not canonical")
    return {"name": str(payload["name"]), "version": str(payload["version"])}


_CAPTURE_PROGRAM = r"""
const fs = require('fs');
const path = require('path');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const playwright = require(input.playwright_module);
const packageJson = require(path.join(input.playwright_module, 'package.json'));

function relativeRoute(value) {
  const url = new URL(value);
  return `${url.pathname}${url.search}${url.hash}`;
}

(async () => {
  const browser = await playwright.chromium.launch({headless: true});
  const captures = [];
  try {
    for (const spec of input.profiles) {
      const context = await browser.newContext({
        viewport: spec.viewport,
        deviceScaleFactor: 1,
        isMobile: spec.mobile,
        hasTouch: spec.mobile,
        locale: 'en-US',
        reducedMotion: 'no-preference'
      });
      const page = await context.newPage();
      const counts = {
        warning_count: 0,
        error_count: 0,
        page_error_count: 0,
        request_count: 0,
        response_error_count: 0,
        request_failed_count: 0
      };
      page.on('console', (message) => {
        if (message.type() === 'warning') counts.warning_count += 1;
        if (message.type() === 'error') counts.error_count += 1;
      });
      page.on('pageerror', () => { counts.page_error_count += 1; });
      page.on('request', () => { counts.request_count += 1; });
      page.on('requestfailed', () => { counts.request_failed_count += 1; });
      page.on('response', (response) => {
        if (response.status() >= 400) counts.response_error_count += 1;
      });
      await page.addInitScript(() => {
        window.localStorage.setItem('wikiCockpitTourDone.v1', '1');
        window.localStorage.setItem('wikiCockpitMissionCard.v1', 'closed');
        window.localStorage.setItem('wiki-cockpit.missionCard', 'closed');
      });
      await page.goto(`${input.base_url}${spec.route}`, {
        waitUntil: 'domcontentloaded',
        timeout: 45000
      });
      await page.locator('.worldWorkspace').waitFor({state: 'visible', timeout: 30000});
      await page.waitForFunction(
        () => !document.querySelector('.worldRouteLoading, .sceneLoading'),
        undefined,
        {timeout: 30000}
      );
      let actionCount = 0;
      if (spec.profile === 'quadrant_collection_two_step') {
        const group = page.locator(
          '[data-world-target-kind="group"][data-world-target-id="family:source"]'
        );
        await group.waitFor({state: 'visible', timeout: 30000});
        await group.click();
        actionCount += 1;
        const summary = page.locator('[data-world-group-summary="family:source"]');
        await summary.waitFor({state: 'visible', timeout: 30000});
        const member = summary.locator('[data-world-member-id]').first();
        await member.waitFor({state: 'visible', timeout: 30000});
        await member.click();
        actionCount += 1;
        await page.waitForFunction(
          () => document.querySelector('.worldWorkspace')?.getAttribute('data-world-center') !== 'root-alex-rivera',
          undefined,
          {timeout: 30000}
        );
      }
      await page.evaluate(async () => {
        const finite = document.getAnimations({subtree: true}).filter(
          (animation) => animation.effect?.getTiming().iterations !== Infinity
        );
        await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
      });
      await page.waitForTimeout(250);
      const state = await page.evaluate(() => {
        const workspace = document.querySelector('.worldWorkspace');
        const scene = document.querySelector('.sceneShell');
        return {
          view: workspace?.getAttribute('data-world-view') || '',
          center: workspace?.getAttribute('data-world-center') || '',
          runtime_mode: workspace?.getAttribute('data-runtime-mode') || '',
          fallback: Boolean(scene?.classList.contains('fallbackMode')),
          canvas_count: scene?.querySelectorAll('canvas').length || 0,
          width: window.innerWidth,
          height: window.innerHeight,
          horizontal_overflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)
        };
      });
      if (state.runtime_mode !== spec.runtime_mode) {
        throw new Error('runtime_mode_contract');
      }
      if (state.view !== spec.view) {
        throw new Error('view_contract');
      }
      if (spec.profile === 'desktop' && (state.fallback || state.canvas_count !== 1)) {
        throw new Error('desktop_profile_contract');
      }
      if (spec.profile === 'mobile' && (state.view !== 'timeline' || state.horizontal_overflow > 1)) {
        throw new Error('mobile_profile_contract');
      }
      if (spec.profile === 'fallback' && (!state.fallback || state.canvas_count !== 0)) {
        throw new Error('fallback_profile_contract');
      }
      if (spec.profile === 'quadrant_collection_two_step' && (state.fallback || state.canvas_count !== 1 || actionCount !== 2)) {
        throw new Error('quadrant_collection_two_step_contract');
      }
      if (state.width !== spec.viewport.width || state.height !== spec.viewport.height) {
        throw new Error('viewport_contract');
      }
      await page.screenshot({path: spec.image_path, type: 'png', fullPage: false, animations: 'disabled'});
      captures.push({
        profile: spec.profile,
        requested_route: spec.route,
        route: relativeRoute(page.url()),
        viewport: spec.viewport,
        view: state.view,
        runtime_mode: state.runtime_mode,
        action_count: actionCount,
        state: spec.state,
        console_summary: {
          warning_count: counts.warning_count,
          error_count: counts.error_count,
          page_error_count: counts.page_error_count
        },
        network_summary: {
          request_count: counts.request_count,
          response_error_count: counts.response_error_count,
          request_failed_count: counts.request_failed_count
        }
      });
      await context.close();
    }
    process.stdout.write(JSON.stringify({
      toolchain: {
        name: 'playwright-chromium',
        version: `${packageJson.version}+chromium.${browser.version()}`
      },
      captures
    }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  const allowed = new Set([
    'desktop_profile_contract',
    'mobile_profile_contract',
    'fallback_profile_contract',
    'quadrant_collection_two_step_contract',
    'runtime_mode_contract',
    'view_contract',
    'viewport_contract'
  ]);
  const code = allowed.has(error?.message)
    ? error.message
    : 'chromium_capture_process_failed';
  process.stderr.write(`VISUAL_CAPTURE_ERROR:${code}`);
  process.exit(2);
});
""".strip()


def _capture_profiles(
    *,
    source_root: Path,
    base_url: str,
    output_root: Path,
    profiles: Sequence[str],
    source_sha: str | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    module = _node_playwright_module(source_root)
    context = _node_workspace_binding(source_root, source_sha=source_sha)
    payload_profiles = []
    for profile in profiles:
        spec = PROFILE_SPECS[profile]
        payload_profiles.append(
            {
                "profile": profile,
                "route": spec["route"],
                "viewport": spec["viewport"],
                "view": spec["view"],
                "runtime_mode": spec["runtime_mode"],
                "mobile": spec["mobile"],
                "state": spec["state"],
                "image_path": str(output_root / "images" / f"{profile}.png"),
            }
        )
    payload = {
        "playwright_module": str(module),
        "base_url": base_url,
        "profiles": payload_profiles,
    }
    try:
        result = run_bounded_process(
            [str(context.node["executable"]), "-e", _CAPTURE_PROGRAM],
            cwd=source_root,
            env=context.environment,
            timeout=max(120, 65 * len(profiles)),
            output_limit=MAX_CAPTURE_PROCESS_OUTPUT_BYTES,
            input_bytes=_canonical_bytes(payload),
            input_limit=MAX_CAPTURE_PROCESS_INPUT_BYTES,
            popen_factory=subprocess.Popen,
        )
    except (OSError, ProcessSafetyError) as exc:
        raise VisualEvidenceError("real Chromium visual capture failed") from exc
    if result.returncode != 0:
        try:
            safe_error = result.output.decode("ascii", "strict").strip()
        except UnicodeDecodeError:
            safe_error = ""
        match = re.fullmatch(r"VISUAL_CAPTURE_ERROR:([a-z][a-z0-9_]{1,63})", safe_error)
        reason = match.group(1) if match else "chromium_capture_process_failed"
        raise VisualEvidenceError(f"real Chromium visual capture failed ({reason})")
    try:
        response = json.loads(result.output.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("Chromium capture output was not canonical") from exc
    if (
        not isinstance(response, dict)
        or set(response) != {"toolchain", "captures"}
        or not isinstance(response.get("toolchain"), dict)
        or not isinstance(response.get("captures"), list)
    ):
        raise VisualEvidenceError("Chromium capture output was not canonical")
    return dict(response["toolchain"]), [dict(item) for item in response["captures"]]


def _capture_record(
    *,
    profile: str,
    source_sha: str,
    package_sha256: str,
    toolchain: Mapping[str, str],
    observation: Mapping[str, Any],
    image: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "profile": profile,
        "source_sha": source_sha,
        "package_sha256": package_sha256,
        "requested_route": observation["requested_route"],
        "route": observation["route"],
        "viewport": dict(observation["viewport"]),
        "view": observation["view"],
        "runtime_mode": observation["runtime_mode"],
        "browser_toolchain": dict(toolchain),
        "browser_toolchain_sha256": canonical_sha256(toolchain),
        "image": {
            "path": image["path"],
            "sha256": image["sha256"],
            "bytes": image["bytes"],
            "dimensions": image["dimensions"],
        },
        "console_summary": {
            "capture": "sanitized_counts_only",
            **dict(observation["console_summary"]),
            "truncated": False,
        },
        "network_summary": {
            "capture": "sanitized_counts_only",
            **dict(observation["network_summary"]),
            "truncated": False,
        },
        "capture": {
            "method": CAPTURE_METHOD,
            "action_count": observation["action_count"],
            "state": observation["state"],
            "settled": True,
        },
    }


def _write_bundle(
    *,
    output_root: Path,
    profiles: Sequence[str],
    source_sha: str,
    package_sha256: str,
    toolchain: Mapping[str, str],
    observations: Sequence[Mapping[str, Any]],
) -> None:
    by_profile = {str(item.get("profile") or ""): item for item in observations}
    if set(by_profile) != set(profiles) or len(by_profile) != len(observations):
        raise VisualEvidenceError(
            "Chromium did not return one result per visual profile"
        )
    entries: list[dict[str, Any]] = []
    for profile in sorted(profiles):
        observation = by_profile[profile]
        requested_route = _public_demo_route(
            observation.get("requested_route"), label=f"{profile} requested route"
        )
        final_route = _public_demo_route(
            observation.get("route"), label=f"{profile} final route"
        )
        if requested_route != PROFILE_SPECS[profile]["route"]:
            raise VisualEvidenceError(
                "capture route differs from the versioned profile"
            )
        if observation.get("runtime_mode") != PROFILE_SPECS[profile]["runtime_mode"]:
            raise VisualEvidenceError(
                "capture runtime mode differs from the versioned profile"
            )
        if observation.get("view") != PROFILE_SPECS[profile]["view"]:
            raise VisualEvidenceError("capture view differs from the versioned profile")
        image_ref = f"images/{profile}.png"
        try:
            image = visual_evidence_file_metadata(
                output_root, image_ref, label=f"visual image {profile}"
            )
        except (ReleaseReceiptError, OSError, ValueError) as exc:
            raise VisualEvidenceError("Chromium emitted an invalid strict PNG") from exc
        if image["dimensions"] != PROFILE_SPECS[profile]["viewport"]:
            raise VisualEvidenceError(
                "Chromium screenshot dimensions differ from the DPR-1 viewport"
            )
        record = _capture_record(
            profile=profile,
            source_sha=source_sha,
            package_sha256=package_sha256,
            toolchain=toolchain,
            observation=observation,
            image=image,
        )
        record_raw = _canonical_bytes(record)
        _write_exclusive(output_root / "records" / f"{profile}.json", record_raw)
        entries.append(
            {
                "id": profile,
                "path": image_ref,
                "sha256": image["sha256"],
                "bytes": image["bytes"],
                "route": final_route,
                "browser": "chromium",
                "viewport": dict(observation["viewport"]),
                "capture_dimensions": image["dimensions"],
                "state": f"capture-{_sha256(record_raw)}",
                "public_synthetic": True,
            }
        )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "entries": entries,
    }
    _write_exclusive(output_root / MANIFEST_REF, _canonical_bytes(manifest))


_MANIFEST_ENTRY_FIELDS = {
    "id",
    "path",
    "sha256",
    "bytes",
    "route",
    "browser",
    "viewport",
    "capture_dimensions",
    "state",
    "public_synthetic",
}
_RECORD_FIELDS = {
    "schema_version",
    "profile",
    "source_sha",
    "package_sha256",
    "requested_route",
    "route",
    "viewport",
    "view",
    "runtime_mode",
    "browser_toolchain",
    "browser_toolchain_sha256",
    "image",
    "console_summary",
    "network_summary",
    "capture",
}


def _nonnegative_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _verify_record(
    *,
    visual_root: Path,
    profile: str,
    entry: Mapping[str, Any],
    source_sha: str,
    package_sha256: str,
    toolchain: Mapping[str, str],
) -> tuple[str, str]:
    record_ref = f"records/{profile}.json"
    raw = _read_regular(visual_root, record_ref, label=f"capture record {profile}")
    try:
        record = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("capture record is not valid UTF-8 JSON") from exc
    if (
        not isinstance(record, dict)
        or set(record) != _RECORD_FIELDS
        or raw != _canonical_bytes(record)
        or record.get("schema_version") != CAPTURE_SCHEMA_VERSION
        or record.get("profile") != profile
        or record.get("source_sha") != source_sha
        or record.get("package_sha256") != package_sha256
        or record.get("browser_toolchain") != dict(toolchain)
        or record.get("browser_toolchain_sha256") != canonical_sha256(toolchain)
        or entry.get("state") != f"capture-{_sha256(raw)}"
    ):
        raise VisualEvidenceError("capture record identity or canonical digest differs")
    requested_route = _public_demo_route(
        record.get("requested_route"), label=f"{profile} requested route"
    )
    route = _public_demo_route(record.get("route"), label=f"{profile} route")
    spec = PROFILE_SPECS[profile]
    if (
        requested_route != spec["route"]
        or route != entry.get("route")
        or record.get("viewport") != spec["viewport"]
        or record.get("view") != spec["view"]
        or record.get("runtime_mode") != spec["runtime_mode"]
        or entry.get("viewport") != spec["viewport"]
    ):
        raise VisualEvidenceError(
            "capture route, view, runtime mode or viewport differs from the profile"
        )
    image = record.get("image")
    if not isinstance(image, dict) or set(image) != {
        "path",
        "sha256",
        "bytes",
        "dimensions",
    }:
        raise VisualEvidenceError("capture image binding fields are invalid")
    try:
        actual_image = visual_evidence_file_metadata(
            visual_root, image.get("path"), label=f"visual image {profile}"
        )
    except (ReleaseReceiptError, OSError, ValueError) as exc:
        raise VisualEvidenceError(
            "visual image failed strict PNG verification"
        ) from exc
    if (
        actual_image != image
        or image.get("dimensions") != spec["viewport"]
        or entry.get("path") != image["path"]
        or entry.get("sha256") != image["sha256"]
        or entry.get("bytes") != image["bytes"]
        or entry.get("capture_dimensions") != spec["viewport"]
        or entry.get("browser") != "chromium"
        or entry.get("public_synthetic") is not True
    ):
        raise VisualEvidenceError("visual image must equal its declared DPR-1 viewport")
    console = record.get("console_summary")
    network = record.get("network_summary")
    capture = record.get("capture")
    if (
        not isinstance(console, dict)
        or set(console)
        != {
            "capture",
            "warning_count",
            "error_count",
            "page_error_count",
            "truncated",
        }
        or console.get("capture") != "sanitized_counts_only"
        or any(
            not _nonnegative_integer(console.get(key))
            for key in ("warning_count", "error_count", "page_error_count")
        )
        or console.get("error_count") != 0
        or console.get("page_error_count") != 0
        or console.get("truncated") is not False
    ):
        raise VisualEvidenceError("console summary is not complete and error-free")
    if (
        not isinstance(network, dict)
        or set(network)
        != {
            "capture",
            "request_count",
            "response_error_count",
            "request_failed_count",
            "truncated",
        }
        or network.get("capture") != "sanitized_counts_only"
        or any(
            not _nonnegative_integer(network.get(key))
            for key in ("request_count", "response_error_count", "request_failed_count")
        )
        or network.get("request_count", 0) < 1
        or network.get("response_error_count") != 0
        or network.get("request_failed_count") != 0
        or network.get("truncated") is not False
    ):
        raise VisualEvidenceError("network summary is not complete and error-free")
    if (
        not isinstance(capture, dict)
        or set(capture) != {"method", "action_count", "state", "settled"}
        or capture.get("method") != CAPTURE_METHOD
        or capture.get("action_count") != spec["action_count"]
        or capture.get("state") != spec["state"]
        or capture.get("settled") is not True
    ):
        raise VisualEvidenceError("capture method/state differs from the profile")
    return str(image["path"]), record_ref


def _verify_inventory(visual_root: Path, expected_files: set[str]) -> None:
    actual_files: set[str] = set()
    for current, directories, files in os.walk(visual_root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            if candidate.is_symlink():
                raise VisualEvidenceError(
                    "visual evidence inventory contains a symlink"
                )
        for name in files:
            candidate = current_path / name
            metadata = candidate.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise VisualEvidenceError(
                    "visual evidence inventory contains a hardlink or special file"
                )
            actual_files.add(candidate.relative_to(visual_root).as_posix())
    if actual_files != expected_files:
        raise VisualEvidenceError(
            "visual evidence inventory contains missing or undeclared files"
        )


def verify_visual_evidence(
    *,
    visual_root: Path,
    package: Mapping[str, Any],
    source_sha: str,
    source_root: Path,
    manifest_ref: str = MANIFEST_REF,
    browser_probe: Callable[[Path], Mapping[str, str]] = _probe_browser_toolchain,
    strict_package: bool = True,
) -> dict[str, Any]:
    """Structurally verify a bundle; never mint productive provenance."""

    source = _verify_source(source_root, source_sha)
    root = _output_path(visual_root, source_root=source, must_exist=True)
    profiles, package_sha256 = _package_contract(
        package, source_sha=source_sha, strict=strict_package
    )
    toolchain = dict(browser_probe(source))
    if set(toolchain) != {"name", "version"}:
        raise VisualEvidenceError("browser toolchain identity fields are invalid")
    manifest_relative = _canonical_relative_path(manifest_ref, label="visual manifest")
    manifest_raw = _read_regular(root, manifest_relative, label="visual manifest")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VisualEvidenceError("visual manifest is not valid UTF-8 JSON") from exc
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "entries"}
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest_raw != _canonical_bytes(manifest)
        or not isinstance(manifest.get("entries"), list)
    ):
        raise VisualEvidenceError(
            "visual manifest fields or canonical bytes are invalid"
        )
    entries = manifest["entries"]
    ids = [entry.get("id") if isinstance(entry, Mapping) else None for entry in entries]
    if ids != sorted(profiles):
        raise VisualEvidenceError(
            "visual manifest must exactly cover sorted package visual_profiles"
        )
    expected_files = {manifest_relative}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != _MANIFEST_ENTRY_FIELDS:
            raise VisualEvidenceError(
                f"visual manifest entry {index} fields are invalid"
            )
        profile = str(entry["id"])
        image_ref, record_ref = _verify_record(
            visual_root=root,
            profile=profile,
            entry=entry,
            source_sha=source_sha,
            package_sha256=package_sha256,
            toolchain=toolchain,
        )
        expected_files.update({image_ref, record_ref})
    _verify_inventory(root, expected_files)
    return {
        "schema_version": "wiki_visual_evidence_verification.v1",
        "status": "verified",
        "source_sha": source_sha,
        "package_sha256": package_sha256,
        "browser_toolchain_sha256": canonical_sha256(toolchain),
        "visual_manifest_ref": manifest_relative,
        "visual_manifest_sha256": _sha256(manifest_raw),
        "visual_manifest_entry_count": len(entries),
        "visual_profiles": sorted(profiles),
        "trust": {
            "capture_provenance": "not_proven_by_reverification",
            "productive_authority": False,
            "release_authority": "requires_external_capture_attestation",
        },
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _build(source_root: Path, *, source_sha: str) -> None:
    try:
        authority = os.environ.get(_NODE_AUTHORITY_ENV)
        authority_sha256 = os.environ.get(_NODE_AUTHORITY_SHA_ENV)
        carried_source_sha = os.environ.get(_NODE_SOURCE_SHA_ENV)
        if not authority or not authority_sha256 or carried_source_sha != source_sha:
            raise VisualEvidenceError(
                "visual evidence requires the exact capsule-bound Node workspace authority"
            )
        result = run_script(
            source_root,
            "build",
            [],
            Path(authority),
            authority_sha256,
            source_sha=source_sha,
        )
    except (OSError, NodeWorkspaceError) as exc:
        raise VisualEvidenceError("exact-source cockpit build failed") from exc
    if result.receipt.get("exit_code") != 0:
        raise VisualEvidenceError("exact-source cockpit build failed")


def _node_workspace_bindings(source_sha: str) -> tuple[Path, str]:
    authority = os.environ.get(_NODE_AUTHORITY_ENV)
    authority_sha256 = os.environ.get(_NODE_AUTHORITY_SHA_ENV)
    carried_source_sha = os.environ.get(_NODE_SOURCE_SHA_ENV)
    if not authority or not authority_sha256 or carried_source_sha != source_sha:
        raise VisualEvidenceError(
            "visual evidence requires the exact capsule-bound Node workspace authority"
        )
    return Path(authority), authority_sha256


def _await_preview(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 30
    url = f"http://127.0.0.1:{port}/demo"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise VisualEvidenceError("exact-source preview stopped before readiness")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 400:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    raise VisualEvidenceError("exact-source preview did not become ready")


def _capture(args: argparse.Namespace) -> dict[str, Any]:
    package = load_mapping(args.package)
    source = _verify_source(args.source_root, args.source_sha)
    profiles, package_sha256 = _package_contract(
        package, source_sha=args.source_sha, strict=True
    )
    output = _output_path(args.out_dir, source_root=source, must_exist=False)
    _build(source, source_sha=args.source_sha)
    source = _verify_source(source, args.source_sha)
    port = args.port or _free_port()
    authority, authority_sha256 = _node_workspace_bindings(args.source_sha)
    created = False

    def discard_partial_output() -> None:
        if not created:
            return
        try:
            shutil.rmtree(output, ignore_errors=True)
        except BaseException:
            # Cleanup must never replace the capture failure or user interrupt.
            pass

    try:
        with certified_preview_process(
            source,
            port,
            authority,
            authority_sha256,
            source_sha=args.source_sha,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        ) as preview:
            _await_preview(preview, port)
            output.mkdir(mode=0o700)
            created = True
            (output / "images").mkdir(mode=0o700)
            (output / "records").mkdir(mode=0o700)
            toolchain, observations = _capture_profiles(
                source_root=source,
                base_url=f"http://127.0.0.1:{port}",
                output_root=output,
                profiles=profiles,
                source_sha=args.source_sha,
            )
            _write_bundle(
                output_root=output,
                profiles=profiles,
                source_sha=args.source_sha,
                package_sha256=package_sha256,
                toolchain=toolchain,
                observations=observations,
            )
            verified = verify_visual_evidence(
                visual_root=output,
                package=package,
                source_sha=args.source_sha,
                source_root=source,
                browser_probe=lambda _root: toolchain,
                strict_package=True,
            )
            verified["trust"] = {
                "capture_provenance": "observed_in_this_capture_process",
                "productive_authority": False,
                "release_authority": "requires_external_capture_attestation",
            }
        _verify_source(source, args.source_sha)
        return verified
    except (OSError, NodeWorkspaceError) as exc:
        discard_partial_output()
        raise VisualEvidenceError(
            "exact-source preview authority changed during capture"
        ) from exc
    except BaseException:
        discard_partial_output()
        raise


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    package = load_mapping(args.package)
    return verify_visual_evidence(
        visual_root=args.visual_root,
        package=package,
        source_sha=args.source_sha,
        source_root=args.source_root,
        manifest_ref=args.manifest_ref,
        browser_probe=lambda root: _probe_browser_toolchain(
            root, source_sha=args.source_sha
        ),
        strict_package=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture or verify exact public-synthetic visual evidence"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser(
        "capture", help="build, serve and capture the exact clean source"
    )
    capture.add_argument("--package", type=Path, required=True)
    capture.add_argument("--source-root", type=Path, required=True)
    capture.add_argument("--source-sha", required=True)
    capture.add_argument("--out-dir", type=Path, required=True)
    capture.add_argument("--port", type=int)
    capture.set_defaults(handler=_capture)
    verify = subparsers.add_parser(
        "verify", help="reopen and verify an immutable visual evidence bundle"
    )
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--source-root", type=Path, required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--visual-root", type=Path, required=True)
    verify.add_argument("--manifest-ref", default=MANIFEST_REF)
    verify.set_defaults(handler=_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "capture" and args.port is not None:
        if args.port < 1024 or args.port > 65535:
            parser.error("--port must be between 1024 and 65535")
    try:
        result = args.handler(args)
    except (VisualEvidenceError, ReleaseReceiptError, OSError, ValueError) as exc:
        message = (
            str(exc)
            if isinstance(exc, (VisualEvidenceError, ReleaseReceiptError))
            else "visual evidence operation failed"
        )
        error = {
            "schema_version": "wiki_visual_evidence_command.v1",
            "status": "blocked",
            "error": type(exc).__name__,
            "message": message,
        }
        sys.stderr.buffer.write(_canonical_bytes(error))
        return 2
    sys.stdout.buffer.write(_canonical_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
