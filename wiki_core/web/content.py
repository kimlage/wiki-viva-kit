"""Full-page content payloads for the in-world reader.

The cockpit reads pages inside the 3D shell. This module builds the payload
served by ``GET /api/pages/{id}/content`` and written as static sidecars:
typed frontmatter, the full markdown body, server-resolved internal links,
backlinks and resolved source references. Everything is path-validated
against the configured memory root — the reader never gets a file outside it.
"""

from __future__ import annotations

import hashlib
import datetime as dt
import json
import math
import posixpath
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.web.repository_links import published_blob_links

PAGE_CONTENT_SCHEMA_VERSION = "wiki_web_page_content.v1"

MD_LINK_RE = re.compile(r"(?<!\!)\[([^\]]*)\]\((<[^>\n]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _is_external(href: str) -> bool:
    parsed = urlparse(href)
    return bool(parsed.scheme) or href.startswith("#") or href.startswith("mailto:")


def _resolve_internal(source_rel: str, href: str) -> str | None:
    if _is_external(href):
        return None
    rel = _repository_path(source_rel, href)
    if rel and rel.endswith(".md"):
        return rel
    return None


def _repository_path(source_rel: str, href: str) -> str | None:
    """Lexical Git path: local symlinks cannot redirect a pinned artifact."""
    path = unquote(href.split("#", 1)[0])
    if not path or path.startswith("//") or "\\" in path or any(ord(c) < 32 for c in path):
        return None
    rel = posixpath.normpath(path.lstrip("/") if path.startswith("/")
                            else posixpath.join(posixpath.dirname(source_rel), path))
    return None if rel in {".", ".."} or rel.startswith("../") else rel


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
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("frontmatter contains a non-finite number")
        return value
    if value is None or isinstance(value, (str, int, bool)):
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


def _resolved_links(root: Path, rel: str, body: str, index: dict[str, dict[str, Any]],
                    blobs: dict[str, str] | None = None) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for match in MD_LINK_RE.finditer(body):
        text, href = match.group(1).strip(), match.group(2).strip().removeprefix("<").removesuffix(">")
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        try:
            external = _is_external(href)
            domain = urlparse(href).netloc if external else ""
        except ValueError:
            # Authored URLs are untrusted display data. A malformed authority
            # must neither break the reader nor fall back to a repository path.
            links.append({"kind": "missing", "text": text, "href": href, "target": href})
            continue
        if external:
            if domain:
                links.append({"kind": "external", "text": text, "href": href, "domain": domain})
            continue
        target_rel = _resolve_internal(rel, href)
        target = index.get(target_rel or "")
        if target:
            links.append({"kind": "page", "text": text, "href": href, **_page_brief(target)})
        else:
            blob_path = _repository_path(rel, href)
            url = (blobs or {}).get(blob_path or "")
            if url:
                links.append({"kind": "artifact", "text": text, "href": href, "url": url,
                              "path": blob_path, "domain": "github.com"})
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
    *,
    include_information: bool = False,
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
    try:
        target.relative_to(memory_base)
    except ValueError:
        return {"ok": False, "error": "page outside memory root", "page_id": page_id}
    if not target.is_file():
        return {"ok": False, "error": "page file missing", "page_id": page_id}
    try:
        raw = target.read_bytes()
    except OSError:
        return {"ok": False, "error": "page file missing", "page_id": page_id}
    expected_content_sha = str(page.get("content_sha256") or "")
    actual_content_sha = hashlib.sha256(raw).hexdigest()
    snapshot_id = str(snapshot.get("manifest.json", {}).get("snapshot_id") or "")
    if not expected_content_sha:
        return {
            "ok": False,
            "error": "snapshot has no immutable content hash; refresh required",
            "error_code": "snapshot_content_hash_missing",
            "page_id": page_id,
            "snapshot_id": snapshot_id,
        }
    if actual_content_sha != expected_content_sha:
        # Never combine cached metadata from revision A with a body from B.
        # The dynamic server turns this into HTTP 409 and invalidates its
        # snapshot cache; static sidecar generation fails before promotion.
        return {
            "ok": False,
            "error": "page changed since snapshot; refresh required",
            "error_code": "snapshot_revision_mismatch",
            "page_id": page_id,
            "snapshot_id": snapshot_id,
            "expected_content_sha256": expected_content_sha,
            "actual_content_sha256": actual_content_sha,
        }
    values, body = parse_frontmatter(raw.decode("utf-8", errors="replace"))
    try:
        safe_frontmatter = _json_safe(values)
    except ValueError:
        return {
            "ok": False,
            "error": "page frontmatter contains a non-finite number",
            "error_code": "content_frontmatter_non_finite",
            "page_id": page_id,
            "snapshot_id": snapshot_id,
        }
    # Communication and next-step fields are authored content too. Resolve
    # their links only after verifying the same immutable page bytes.
    link_text = [body]
    for key in ("next_action", "blocker_reason", "completion_receipt", "cancellation_receipt"):
        value = values.get(key)
        if isinstance(value, str):
            link_text.append(value)
    dialogue = values.get("action_dialogue")
    if isinstance(dialogue, list):
        link_text.extend(event["text"] for event in dialogue
                         if isinstance(event, dict) and isinstance(event.get("text"), str))
    information = (_reader_information(root, config, rel, values, body, snapshot)
        if include_information and ("information_requirements" in values or "operational_prerequisite" in body) else None)
    return {
        "ok": True,
        "schema_version": PAGE_CONTENT_SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "page": {**_page_brief(page), "summary": str(page.get("summary") or ""),
                 "summary_truncated": bool(page.get("summary_truncated")),
                 "updated_at": str(page.get("updated_at") or ""),
                 "moc_parent": str(page.get("moc_parent") or "")},
        "frontmatter": safe_frontmatter,
        "body": body,
        "resolved_links": _resolved_links(root, rel, "\n".join(link_text), index,
                                           published_blob_links(root, snapshot.get("git.json", {}))),
        "backlinks": _backlinks(page, graph, index),
        "source_refs": _resolved_sources(page, index),
        **({"information_use": information} if information else {}),
    }


def _reader_information(root, config, path, values, body, snapshot):
    """Passive assessment from exact snapshot pages, never a fetch or a grant.

    This opt-in is only for the human reader/sidecars. Agent context continues
    to authorize each required reference before reading it through its port.
    """
    from wiki_core.information_relations import operational_consumption_edges
    from wiki_core.information_use import bind_verification_coverage, assess_information_use
    def head():
        try:
            return subprocess.check_output(['git','rev-parse','--verify','HEAD'],cwd=root,
                text=True,stderr=subprocess.DEVNULL).strip()
        except (OSError,subprocess.SubprocessError):
            return None
    original_head=head()
    pages=snapshot.get('pages.json',{}).get('pages',[])
    def resolve(ref):
        return sorted({p['path'] for p in pages if p.get('id')==ref or p.get('path')==ref})
    graph={'nodes':{path:values},'documents':{path:body},'edges':[],'errors':[]}
    try:
        graph['edges']=operational_consumption_edges(root,path,values,body,resolve)
        pending=[edge['target'] for edge in graph['edges']]
        targets=set(pending)
        while pending:
            ref=pending.pop()
            matches=resolve(ref)
            if len(matches)!=1:
                graph['errors'].append('information_reference_missing_or_ambiguous')
                continue
            target=matches[0]
            if target in graph['nodes']:continue
            content=build_page_content(root,config,target,snapshot,include_information=False)
            if not content.get('ok'):
                graph['errors'].append(content.get('error_code') or 'information_reference_unreadable')
                continue
            graph['nodes'][target]=content['frontmatter'];graph['documents'][target]=content['body']
            if target in targets or content['frontmatter'].get('page_type')=='claim':
                evidence=content['frontmatter'].get('evidence_refs',[])
                if not isinstance(evidence,list) or any(not isinstance(item,str) for item in evidence):
                    graph['errors'].append('information_evidence_invalid')
                else:pending.extend(evidence)
    except ValueError:
        graph['errors'].append('information_requirement_invalid')
    if not graph['edges'] and not graph['errors']:
        return None
    # Snapshot time is visible and deterministic in static exports. Actual
    # execution evaluates its own current clock and authorized readset again.
    recorded=snapshot.get('manifest.json',{}).get('generated_at')
    try:
        now=dt.datetime.fromisoformat(str(recorded).replace('Z','+00:00'))
        if now.tzinfo is None:raise ValueError('timezone missing')
    except ValueError:
        now=dt.datetime.now(dt.timezone.utc)
    qualified=bind_verification_coverage(root,graph)
    # Coverage reads Git and source bytes independently. They must still be
    # the exact snapshot revisions whose metadata is about to be presented.
    for ref in graph['nodes']:
        current=build_page_content(root,config,ref,snapshot,include_information=False)
        if not current.get('ok'):
            qualified['errors'].append(current.get('error_code') or 'information_reference_unreadable')
    if head()!=original_head:
        qualified['errors'].append('snapshot_revision_mismatch')
    result=assess_information_use(qualified,path,now=now)
    return {**result,'assessed_at':now.isoformat(),'permission_granted':False}


def write_content_sidecars(
    root: Path,
    config: WikiConfig,
    snapshot: dict[str, dict[str, Any]],
    out_dir: Path,
) -> dict[str, Path]:
    """Write one deterministic ``content/{slug}.{hash}.json`` per page."""
    content_dir = out_dir / "content"
    content_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for page in snapshot.get("pages.json", {}).get("pages", []):
        page_id = str(page.get("id") or page.get("path") or "")
        if not page_id:
            continue
        payload = build_page_content(root, config, page_id, snapshot, include_information=True)
        if not payload.get("ok"):
            raise ValueError(
                f"cannot write content sidecar for {page_id!r}: "
                f"{payload.get('error') or 'unknown content error'}"
            )
        target = content_dir / sidecar_name(page_id)
        target.write_text(
            json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[page_id] = target
    return written
