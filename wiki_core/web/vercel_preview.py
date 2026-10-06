"""Opt-in Vercel Build Output adapter for the committed public demo only.

This does not export a consumer wiki or configure deployment authentication.
There is deliberately no private-data override or account/deployment action.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from wiki_core.output_safety import OUTPUT_OWNER_FILENAME, contained_output_path, write_output_owner
from wiki_core.web.content import PAGE_CONTENT_SCHEMA_VERSION, sidecar_name
from wiki_core.web.snapshot import snapshot_contract_errors


FIXTURE_PATH = Path("apps/wiki-cockpit/public/sample-snapshot/scenarios/walking_skeleton")
RUNTIME_PATH = Path("apps/wiki-cockpit/deploy/vercel/runtime.cjs")
DEFAULT_ROUTE = "/w?projection=2d&page=source-banco-export&map_focus=source-banco-export&reader=1&tour=0"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", "-C", str(root), *args],
            check=True, capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("preview requires a readable Git HEAD") from exc


def _no_symlinks(path: Path) -> None:
    # Check lexical ancestors before resolve(), including links that stay inside
    # the repository. An output must not accidentally follow an owned alias.
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("preview paths cannot contain symlinks")


def _read_regular(path: Path) -> bytes:
    _no_symlinks(path)
    if not path.is_file():
        raise ValueError("preview input must be a regular file")
    return path.read_bytes()


def _fixture(root: Path) -> tuple[str, dict[str, bytes], dict[str, str]]:
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        raise ValueError("invalid preview source HEAD")
    base = root / FIXTURE_PATH
    _no_symlinks(base)
    tracked: dict[str, bytes] = {}
    for entry in _git(root, "ls-tree", "-rz", "--full-tree", head, "--", FIXTURE_PATH.as_posix()).split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, _ = metadata.split()
        name = Path(raw_name.decode()).relative_to(FIXTURE_PATH).as_posix()
        if mode != b"100644" or kind != b"blob" or not re.fullmatch(r"(?:content/)?[A-Za-z0-9_.-]+\.json", name):
            raise ValueError("invalid committed demo fixture entry")
        tracked[name] = _git(root, "show", f"{head}:{FIXTURE_PATH.as_posix()}/{name}")
    if not tracked or not base.is_dir():
        raise ValueError("committed walking_skeleton fixture is required")
    actual: set[str] = set()
    expected_dirs = {parent.as_posix() for name in tracked for parent in Path(name).parents if parent != Path(".")}
    for path in base.rglob("*"):
        _no_symlinks(path)
        if path.is_file():
            name = path.relative_to(base).as_posix()
            actual.add(name)
            if name not in tracked or _read_regular(path) != tracked[name]:
                raise ValueError("demo fixture differs from Git HEAD")
        elif not path.is_dir() or path.relative_to(base).as_posix() not in expected_dirs:
            raise ValueError("invalid demo fixture directory or file")
    if actual != set(tracked):
        raise ValueError("demo fixture differs from Git HEAD")
    # The normal snapshot generator owns its directory through this tracked
    # marker. Verify it against HEAD above, but it is not a snapshot payload.
    if OUTPUT_OWNER_FILENAME in tracked:
        del tracked[OUTPUT_OWNER_FILENAME]
        actual.remove(OUTPUT_OWNER_FILENAME)
    try:
        payloads = {name: json.loads(data) for name, data in tracked.items()}
        manifest = payloads["manifest.json"]
        if manifest.get("fixture", {}).get("scenario_id") != "walking_skeleton" or manifest.get("fixture", {}).get("fixture_id") != "wiki-viva-demo-v8":
            raise ValueError("only the public synthetic walking_skeleton fixture is supported")
        if set(manifest.get("files", [])) != actual or not manifest.get("content_sidecars"):
            raise ValueError("demo fixture manifest must cover all files and reader sidecars")
        if manifest.get("contract_errors") or snapshot_contract_errors(payloads):
            raise ValueError("demo fixture failed snapshot contracts")
        # The existing snapshot contract checks canonical sha256. Also check
        # its byte lengths; these are canonical JSON lengths, not pretty bytes.
        from wiki_core.web.snapshot import _payload_integrity

        for name, expected in manifest["integrity"].items():
            if _payload_integrity(payloads[name]) != expected:
                raise ValueError("demo fixture failed canonical integrity")
        pages = {page["id"]: page for page in payloads["pages.json"]["pages"]}
        reader: dict[str, str] = {}
        for name, payload in payloads.items():
            if not name.startswith("content/"):
                continue
            page_id = payload.get("page", {}).get("page_id")
            if not isinstance(page_id, str) or page_id not in pages or page_id in reader or payload.get("snapshot_id") != manifest["snapshot_id"]:
                raise ValueError("demo reader sidecar coverage or revision mismatch")
            if (payload.get("ok") is not True or payload.get("schema_version") != PAGE_CONTENT_SCHEMA_VERSION
                or not isinstance(payload.get("body"), str) or name != f"content/{sidecar_name(page_id)}"
                or payload["page"].get("path") != pages[page_id]["path"]
                or payload["page"].get("page_type") != pages[page_id]["page_type"]
                or payload.get("frontmatter", {}).get("page_id") != page_id):
                raise ValueError("demo reader sidecar contract mismatch")
            reader[page_id] = f"/snapshot/{name}"
        if set(reader) != set(pages):
            raise ValueError("demo reader sidecar coverage is incomplete")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid demo snapshot structure") from exc
    return head, tracked, reader


def _frontend(dist: Path) -> dict[str, bytes]:
    _no_symlinks(dist)
    if not dist.is_dir():
        raise ValueError("build the cockpit frontend before preparing the preview")
    payloads = {f"/{name}": _read_regular(dist / name) for name in ("index.html", "favicon.svg")}
    assets = dist / "assets"
    _no_symlinks(assets)
    if not assets.is_dir():
        raise ValueError("frontend assets directory is required")
    for asset in sorted(assets.iterdir()):
        if not re.fullmatch(r"[A-Za-z0-9_.~-]+\.(?:js|css)", asset.name):
            raise ValueError("frontend assets accept direct JavaScript and CSS files only")
        payloads[f"/assets/{asset.name}"] = _read_regular(asset)
    if not any(name.endswith(".js") for name in payloads):
        raise ValueError("frontend JavaScript assets are required")
    # Vite copies public/ to dist. Never import its snapshot/config/other roots;
    # only the reviewed Git fixture and generated read-only config are bundled.
    return payloads


def write_vercel_preview(root: Path, out_dir: Path, *, frontend_dist: Path | None = None) -> dict[str, Any]:
    """Create a new immutable, synthetic-only prebuilt output without deploying."""

    root = Path(root).absolute()
    out_dir = Path(out_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    _no_symlinks(root)
    _no_symlinks(out_dir)
    target = contained_output_path(root, out_dir)
    if target.exists():
        raise ValueError("preview output must be a new directory; existing outputs are immutable")
    try:
        head, fixture, reader = _fixture(root)
        payloads = _frontend(Path(frontend_dist) if frontend_dist is not None else root / "apps/wiki-cockpit/dist")
        runtime = _read_regular(root / RUNTIME_PATH)
    except OSError as exc:
        raise ValueError("could not read preview inputs") from exc
    manifest = json.loads(fixture["manifest.json"])
    snapshot_id = manifest["snapshot_id"]
    payloads.update({f"/snapshot/{name}": data for name, data in fixture.items()})
    payloads["/wiki-cockpit.config.json"] = _json_bytes({
        "api_base": "", "snapshot_base": "/snapshot", "repo_label": "Wiki Viva Kit synthetic preview",
        "mode": "static", "codex": {"enabled": False},
        "features": {"takezo_easter_egg": False, "takezo_companion": False},
    })
    payloads["/files/synthetic-note.txt"] = b"Synthetic attachment: no consumer or account data.\n"
    if len(payloads) > 256 or any(len(data) > 20 * 1024 * 1024 for data in payloads.values()) or sum(map(len, payloads.values())) > 50 * 1024 * 1024:
        raise ValueError("preview exceeds the runtime's payload count or size limits")
    def content_type(name: str) -> str:
        return {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8"}[Path(name).suffix]

    catalog = {name: {"sha256": _sha(data), "bytes": len(data), "content_type": content_type(name)} for name, data in sorted(payloads.items())}
    release = _json_bytes({
        "schema_version": "wiki_vercel_preview.v1", "source_head": head,
        "snapshot_id": snapshot_id, "synthetic_fixture": "walking_skeleton",
        "files": catalog, "reader": reader,
        "downloads": {"synthetic-note": {"uri": "/files/synthetic-note.txt", "filename": "synthetic-note.txt"}},
        "default_route": DEFAULT_ROUTE,
    })
    release_sha = _sha(release)
    receipt = {
        "schema_version": "wiki_vercel_preview_receipt.v1", "source_head": head,
        "source_tree": _git(root, "rev-parse", f"{head}^{{tree}}").decode().strip(),
        "snapshot_id": snapshot_id, "synthetic_fixture": "walking_skeleton",
        "manifest_sha256": release_sha, "runtime_sha256": _sha(runtime),
        "payload_count": len(payloads), "files": catalog,
        "protection": "Vercel Authentication for all deployments must be verified before deployment; not configured by this tool",
    }
    # Validate/freeze everything first. Stage in the target's parent and promote
    # once; never replace an existing output or clean an arbitrary directory.
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".wiki-vercel-preview-", dir=target.parent))
    try:
        output = stage / ".vercel/output"
        function = output / "functions/wiki.func"
        bundle = function / "bundle"
        bundle.mkdir(parents=True)
        for name, data in payloads.items():
            path = bundle / name.lstrip("/")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (bundle / "release-manifest.json").write_bytes(release)
        (function / "runtime.cjs").write_bytes(runtime)
        (function / "index.cjs").write_text(
            "const { createHandler } = require('./runtime.cjs');\n"
            f"module.exports = createHandler(require('node:path').join(__dirname, 'bundle'), '{release_sha}');\n",
            encoding="utf-8",
        )
        (function / ".vc-config.json").write_bytes(_json_bytes({
            "runtime": "nodejs22.x", "handler": "index.cjs", "launcherType": "Nodejs",
            "shouldAddHelpers": False, "maxDuration": 10,
        }))
        (output / "config.json").write_bytes(_json_bytes({"version": 3, "routes": [{"src": "/(.*)", "dest": "/wiki"}]}))
        (stage / "preview-receipt.json").write_bytes(_json_bytes(receipt))
        write_output_owner(stage, kind="vercel_synthetic_preview", repo_id="wiki-viva-demo")
        if target.exists():
            raise ValueError("preview output appeared during preparation")
        stage.rename(target)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {"output": target, "receipt": target / "preview-receipt.json", "source_head": head,
            "snapshot_id": snapshot_id, "payload_count": len(payloads), "manifest_sha256": release_sha}
