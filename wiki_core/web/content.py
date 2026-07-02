"""Full-page content payloads for the in-world reader.

The cockpit reads pages inside the 3D shell. This module builds the payload
served by ``GET /api/pages/{id}/content`` and written as static sidecars:
typed frontmatter, the full markdown body, server-resolved internal links,
backlinks and resolved source references. Everything is path-validated
against the configured memory root — the reader never gets a file outside it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter

PAGE_CONTENT_SCHEMA_VERSION = "wiki_web_page_content.v1"

MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _is_external(href: str) -> bool:
    parsed = urlparse(href)
    return bool(parsed.scheme) or href.startswith("#") or href.startswith("mailto:")


def _repo_rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _resolve_internal(root: Path, source_rel: str, href: str) -> str | None:
    href = unquote(href.split("#", 1)[0]).strip()
    if not href or _is_external(href):
        return None
    candidate = root / href.lstrip("/") if href.startswith("/") else (root / source_rel).parent / href
    rel = _repo_rel(root, candidate)
    if rel and rel.endswith(".md"):
        return rel
    return None


def sidecar_name(page_id: str) -> str:
    """Deterministic, filesystem-safe sidecar file name for a page id.

    Mirrored in the cockpit frontend (fnv-1a 32-bit) so static deployments
    can address content without a server.
    """
    value = 0x811C9DC5
    for byte in page_id.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    slug = re.sub(r"[^a-z0-9._-]+", "-", page_id.lower()).strip("-")[:60] or "page"
    return f"{slug}.{value:08x}.json"


def _json_safe(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _page_brief(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_id": str(page.get("id") or ""),
        "path": str(page.get("path") or ""),
        "title": str(page.get("title") or page.get("id") or ""),
        "context": str(page.get("context") or ""),
        "page_type": str(page.get("page_type") or ""),
        "freshness_state": str(page.get("freshness_state") or "unknown"),
        "approved_state": str(page.get("approved_state") or "approved"),
    }


def _page_index(pages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for page in pages:
        for key in (str(page.get("id") or ""), str(page.get("path") or "")):
            if key:
                index.setdefault(key, page)
    return index


def _resolved_links(root: Path, rel: str, body: str, index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in MD_LINK_RE.finditer(body):
        text, href = match.group(1).strip(), match.group(2).strip()
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        if _is_external(href):
            domain = urlparse(href).netloc
            if domain:
                links.append({"kind": "external", "text": text, "href": href, "domain": domain})
            continue
        target_rel = _resolve_internal(root, rel, href)
        target = index.get(target_rel or "")
        if target:
            links.append({"kind": "page", "text": text, "href": href, **_page_brief(target)})
        else:
            links.append({"kind": "missing", "text": text, "href": href, "target": target_rel or href})
    return links


def _backlinks(page: dict[str, Any], graph: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {str(page.get("id") or ""), str(page.get("path") or "")}
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for edge in graph.get("edges", []):
        if str(edge.get("target")) not in keys:
            continue
        source = index.get(str(edge.get("source")))
        if not source:
            continue
        dedupe = (str(source.get("id")), str(edge.get("type")))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        out.append({**_page_brief(source), "relation": str(edge.get("type") or "markdown_link")})
    return sorted(out, key=lambda item: (item["relation"], item["title"], item["page_id"]))


def _resolved_sources(page: dict[str, Any], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ref in page.get("source_refs") or []:
        ref_text = str(ref)
        target = index.get(ref_text)
        if target:
            out.append({"ref": ref_text, "resolved": True, **_page_brief(target)})
        else:
            out.append({"ref": ref_text, "resolved": False})
    return out


def build_page_content(
    root: Path,
    config: WikiConfig,
    page_id: str,
    snapshot: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build the reader payload for one page, or an ``ok: False`` error record."""
    pages = snapshot.get("pages.json", {}).get("pages", [])
    graph = snapshot.get("graph.json", {})
    index = _page_index(pages)
    page = index.get(page_id) or index.get(unquote(page_id))
    if not page:
        return {"ok": False, "error": "unknown page", "page_id": page_id}
    rel = str(page.get("path") or "")
    memory_root = str(config.paths["memory_root"]).rstrip("/")
    target = (root / rel).resolve()
    memory_base = (root / memory_root).resolve()
    if not str(target).startswith(str(memory_base) + "/") and target != memory_base:
        return {"ok": False, "error": "page outside memory root", "page_id": page_id}
    if not target.is_file():
        return {"ok": False, "error": "page file missing", "page_id": page_id}
    values, body = parse_frontmatter(target)
    return {
        "ok": True,
        "schema_version": PAGE_CONTENT_SCHEMA_VERSION,
        "page": {**_page_brief(page), "summary": str(page.get("summary") or ""),
                 "summary_truncated": bool(page.get("summary_truncated")),
                 "updated_at": str(page.get("updated_at") or ""),
                 "moc_parent": str(page.get("moc_parent") or "")},
        "frontmatter": _json_safe(values),
        "body": body,
        "resolved_links": _resolved_links(root, rel, body, index),
        "backlinks": _backlinks(page, graph, index),
        "source_refs": _resolved_sources(page, index),
    }


def write_content_sidecars(
    root: Path,
    config: WikiConfig,
    snapshot: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Path]:
    """Write one deterministic ``content/{slug}.{hash}.json`` per page."""
    import json

    content_dir = out_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for page in snapshot.get("pages.json", {}).get("pages", []):
        page_id = str(page.get("id") or page.get("path") or "")
        if not page_id:
            continue
        payload = build_page_content(root, config, page_id, snapshot)
        target = content_dir / sidecar_name(page_id)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[page_id] = target
    return written
