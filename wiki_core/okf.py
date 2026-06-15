from __future__ import annotations

import datetime as dt
import html
import json
import posixpath
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

from wiki_core.frontmatter import list_values, parse_frontmatter, split_frontmatter
from wiki_core.ids import slugify

OKF_VERSION = "0.1"
OKF_EXPORT_SCHEMA_VERSION = "wiki_okf_export.v1"
OKF_IMPORT_SCHEMA_VERSION = "wiki_okf_import_preview.v1"
OKF_VISUALIZATION_SCHEMA_VERSION = "wiki_okf_visualization.v1"

RESERVED_FILENAMES = {"index.md", "log.md"}
MARKDOWN_LINK_RE = re.compile(r"(\[[^\]]+\]\()([^)]+)(\))")
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_DATE_HEADING_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)


@dataclass(frozen=True)
class OKFExportResult:
    schema_version: str
    okf_version: str
    source_root: str
    bundle_root: str
    concept_count: int
    reserved_concept_count: int
    index_count: int
    warnings: list[str]


@dataclass(frozen=True)
class OKFCheckResult:
    okf_version: str
    bundle_root: str
    markdown_count: int
    concept_count: int
    reserved_count: int
    broken_links: int
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class OKFImportConcept:
    concept_id: str
    okf_type: str
    title: str
    source_path: str
    suggested_page_id: str
    suggested_page_type: str
    suggested_output_path: str


@dataclass(frozen=True)
class OKFImportPreview:
    schema_version: str
    okf_version: str
    bundle_root: str
    context: str
    concept_count: int
    concepts: list[OKFImportConcept]
    warnings: list[str]


@dataclass(frozen=True)
class OKFVisualizationResult:
    schema_version: str
    bundle_root: str
    output_path: str
    concepts: int
    edges: int
    bytes: int


def _repo_rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    values, body = parse_frontmatter(path)
    return _jsonable(values), body


def _first_heading(body: str) -> str:
    match = HEADING_RE.search(body)
    return match.group(1).strip() if match else ""


def _description(values: dict[str, Any], body: str) -> str:
    for key in ("description", "purpose", "summary"):
        value = str(values.get(key) or "").strip()
        if value:
            return value.replace("\n", " ")
    for block in body.split("\n\n"):
        text = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if text and not text.startswith(("#", "|", "```", "-", "*", ">")):
            return text[:240]
    return ""


def _timestamp(values: dict[str, Any]) -> str | None:
    raw = values.get("timestamp") or values.get("updated_at") or values.get("last_updated")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if DATE_RE.fullmatch(text):
        return f"{text}T00:00:00Z"
    return text


def _resource(values: dict[str, Any]) -> str | None:
    for key in ("resource", "source_uri", "url", "original_url"):
        value = str(values.get(key) or "").strip()
        if value:
            return value
    refs = list_values(values.get("source_refs"))
    for ref in refs:
        if ref.startswith(("http://", "https://")):
            return ref
    return None


def _title(values: dict[str, Any], body: str, rel: str) -> str:
    return (
        str(values.get("title") or "").strip()
        or _first_heading(body)
        or Path(rel).with_suffix("").name.replace("-", " ").title()
    )


def _reserved_export_rel(source_rel: str) -> str:
    stem = source_rel.removesuffix(".md").replace("/", "__")
    if stem == "index":
        stem = "root-index"
    return f"_wiki_viva_reserved/{slugify(stem)}.md"


def _is_reserved(rel: str) -> bool:
    return Path(rel).name.lower() in RESERVED_FILENAMES


def _concept_export_rel(source_rel: str) -> str:
    return _reserved_export_rel(source_rel) if _is_reserved(source_rel) else source_rel


def _all_markdown(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*.md") if path.is_file())


def _is_external_link(href: str) -> bool:
    parsed = urlparse(href)
    return bool(parsed.scheme) or href.startswith(("mailto:", "#"))


def _resolve_source_link(source_rel: str, href: str) -> tuple[str | None, str]:
    href = unquote(href.strip())
    if not href or _is_external_link(href):
        return None, ""
    target, marker, anchor = href.partition("#")
    if not target:
        return None, marker + anchor if marker else ""
    if target.startswith("/"):
        candidate = posixpath.normpath(target.lstrip("/"))
    else:
        candidate = posixpath.normpath(posixpath.join(posixpath.dirname(source_rel), target))
    if candidate in {".", ""}:
        candidate = "index.md"
    if not candidate.endswith(".md"):
        candidate = posixpath.join(candidate, "index.md")
    return candidate, marker + anchor if marker else ""


def _rel_link(from_rel: str, to_rel: str) -> str:
    base = posixpath.dirname(from_rel)
    rel = posixpath.relpath(to_rel, base or ".")
    return rel if rel != "." else posixpath.basename(to_rel)


def _rewrite_links(body: str, source_rel: str, export_rel: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        href = match.group(2)
        target, anchor = _resolve_source_link(source_rel, href)
        if target is None or target not in mapping:
            return match.group(0)
        return f"{match.group(1)}{_rel_link(export_rel, mapping[target])}{anchor}{match.group(3)}"

    return MARKDOWN_LINK_RE.sub(replace, body)


def _okf_frontmatter(values: dict[str, Any], body: str, source_rel: str) -> dict[str, Any]:
    page_type = str(values.get("page_type") or values.get("type") or "Concept").strip()
    out: dict[str, Any] = {
        "type": page_type,
        "title": _title(values, body, source_rel),
    }
    description = _description(values, body)
    if description:
        out["description"] = description
    resource = _resource(values)
    if resource:
        out["resource"] = resource
    tags = list_values(values.get("tags"))
    if tags:
        out["tags"] = tags
    timestamp = _timestamp(values)
    if timestamp:
        out["timestamp"] = timestamp

    for key, value in values.items():
        if key == "type":
            out["x_wiki_viva_original_type"] = value
        elif key not in out:
            out[key] = value

    out["x_wiki_viva_source_path"] = source_rel
    if values.get("page_id"):
        out["x_wiki_viva_page_id"] = values["page_id"]
    if values.get("page_type"):
        out["x_wiki_viva_page_type"] = values["page_type"]
    if values.get("context"):
        out["x_wiki_viva_context"] = values["context"]
    return out


def _write_concept(out_path: Path, frontmatter: dict[str, Any], body: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    out_path.write_text(f"---\n{yaml_text}\n---\n\n{body.lstrip()}", encoding="utf-8")


def _concept_description(path: Path) -> tuple[str, str]:
    values, body = _read_markdown(path)
    title = _title(values, body, path.name)
    return title, _description(values, body)


def _write_indexes(bundle_root: Path) -> int:
    dirs = {bundle_root}
    for md in bundle_root.rglob("*.md"):
        dirs.add(md.parent)
        for parent in md.parents:
            if parent == bundle_root:
                break
            if bundle_root in parent.parents or parent == bundle_root:
                dirs.add(parent)

    count = 0
    for directory in sorted(dirs, key=lambda p: p.relative_to(bundle_root).as_posix()):
        rel_dir = "." if directory == bundle_root else directory.relative_to(bundle_root).as_posix()
        concept_files = sorted(
            p
            for p in directory.glob("*.md")
            if p.name.lower() not in RESERVED_FILENAMES and p.is_file()
        )
        subdirs = sorted(p for p in directory.iterdir() if p.is_dir())
        lines: list[str] = []
        if directory == bundle_root:
            lines.extend(["---", f'okf_version: "{OKF_VERSION}"', "---", ""])
            lines.append("# Wiki Viva OKF Bundle")
        else:
            title = rel_dir.replace("/", " / ")
            lines.append(f"# {title}")
        lines.append("")
        lines.append("## Concepts")
        lines.append("")
        if concept_files:
            for concept in concept_files:
                title, description = _concept_description(concept)
                suffix = f" - {description}" if description else ""
                lines.append(f"* [{title}]({concept.name}){suffix}")
        else:
            lines.append("* No direct concepts.")
        lines.append("")
        lines.append("## Subdirectories")
        lines.append("")
        visible_subdirs = [sub for sub in subdirs if any(sub.rglob("*.md"))]
        if visible_subdirs:
            for subdir in visible_subdirs:
                lines.append(f"* [{subdir.name}]({subdir.name}/index.md)")
        else:
            lines.append("* No subdirectories.")
        lines.append("")
        (directory / "index.md").write_text("\n".join(lines), encoding="utf-8")
        count += 1
    return count


def export_okf_bundle(
    *,
    root: Path,
    source_root: str,
    bundle_root: Path,
    clean: bool = False,
) -> OKFExportResult:
    source_base = root / source_root
    if not source_base.exists():
        raise FileNotFoundError(f"source root not found: {source_root}")
    if clean and bundle_root.exists():
        if bundle_root.resolve() in {root.resolve(), source_base.resolve()}:
            raise ValueError("refusing to clean repo root or source root")
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)

    markdown = _all_markdown(source_base)
    mapping = {
        path.relative_to(source_base).as_posix(): _concept_export_rel(path.relative_to(source_base).as_posix())
        for path in markdown
    }
    warnings: list[str] = []
    reserved_count = 0
    for path in markdown:
        source_rel = path.relative_to(source_base).as_posix()
        export_rel = mapping[source_rel]
        values, body = _read_markdown(path)
        if _is_reserved(source_rel):
            reserved_count += 1
        if not values:
            warnings.append(f"{source_rel}: source page has no parseable frontmatter; exported as Concept")
        rewritten_body = _rewrite_links(body, source_rel, export_rel, mapping)
        frontmatter = _okf_frontmatter(values, rewritten_body, source_rel)
        _write_concept(bundle_root / export_rel, frontmatter, rewritten_body)

    index_count = _write_indexes(bundle_root)
    return OKFExportResult(
        schema_version=OKF_EXPORT_SCHEMA_VERSION,
        okf_version=OKF_VERSION,
        source_root=_repo_rel(root, source_base),
        bundle_root=_repo_rel(root, bundle_root),
        concept_count=len(markdown),
        reserved_concept_count=reserved_count,
        index_count=index_count,
        warnings=warnings,
    )


def _markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def _check_reserved(rel: str, path: Path, errors: list[str], warnings: list[str]) -> None:
    values, body = parse_frontmatter(path)
    filename = path.name.lower()
    if filename == "index.md":
        if rel != "index.md" and values:
            errors.append(f"{rel}: reserved index.md must not contain frontmatter")
        if rel == "index.md" and values and set(values) - {"okf_version"}:
            errors.append(f"{rel}: root index.md frontmatter may only declare okf_version")
        if not HEADING_RE.search(body):
            warnings.append(f"{rel}: index.md has no heading")
    elif filename == "log.md":
        if values:
            errors.append(f"{rel}: reserved log.md must not contain frontmatter")
        if body.strip() and not LOG_DATE_HEADING_RE.search(body):
            warnings.append(f"{rel}: log.md has no ISO date headings")


def _bundle_link_target(bundle_root: Path, source_rel: str, href: str) -> str | None:
    href = unquote(href.strip())
    if not href or _is_external_link(href):
        return None
    target, _marker, _anchor = href.partition("#")
    if not target:
        return None
    if target.startswith("/"):
        candidate = bundle_root / target.lstrip("/")
    else:
        candidate = (bundle_root / source_rel).parent / target
    try:
        rel = candidate.resolve().relative_to(bundle_root.resolve()).as_posix()
    except ValueError:
        return None
    if not rel.endswith(".md"):
        rel = posixpath.join(rel, "index.md")
    return rel


def check_okf_bundle(bundle_root: Path) -> OKFCheckResult:
    errors: list[str] = []
    warnings: list[str] = []
    if not bundle_root.exists():
        errors.append(f"bundle root not found: {bundle_root}")
        return OKFCheckResult(OKF_VERSION, str(bundle_root), 0, 0, 0, 0, errors, warnings)

    files = _markdown_files(bundle_root)
    known = {path.relative_to(bundle_root).as_posix() for path in files}
    concept_count = 0
    reserved_count = 0
    broken = 0
    for path in files:
        rel = path.relative_to(bundle_root).as_posix()
        if path.name.lower() in RESERVED_FILENAMES:
            reserved_count += 1
            _check_reserved(rel, path, errors, warnings)
            continue

        maybe_values, _body = split_frontmatter(path)
        if maybe_values is None:
            errors.append(f"{rel}: missing frontmatter block")
            values: dict[str, Any] = {}
            body = path.read_text(encoding="utf-8", errors="replace")
        else:
            values, body = _read_markdown(path)
        if not str(values.get("type") or "").strip():
            errors.append(f"{rel}: missing required OKF `type` frontmatter")
        concept_count += 1

        for match in MARKDOWN_LINK_RE.finditer(body):
            target = _bundle_link_target(bundle_root, rel, match.group(2))
            if target and target not in known:
                warnings.append(f"{rel}: broken internal link -> {target}")
                broken += 1

    return OKFCheckResult(
        okf_version=OKF_VERSION,
        bundle_root=str(bundle_root),
        markdown_count=len(files),
        concept_count=concept_count,
        reserved_count=reserved_count,
        broken_links=broken,
        errors=errors,
        warnings=warnings,
    )


def _concepts(bundle_root: Path) -> list[tuple[str, Path, dict[str, Any], str]]:
    concepts: list[tuple[str, Path, dict[str, Any], str]] = []
    for path in _markdown_files(bundle_root):
        rel = path.relative_to(bundle_root).as_posix()
        if path.name.lower() in RESERVED_FILENAMES:
            continue
        values, body = _read_markdown(path)
        concepts.append((rel, path, values, body))
    return concepts


def preview_okf_import(
    *,
    bundle_root: Path,
    context: str,
    memory_root: str,
    default_visibility: str,
    today: str | None = None,
) -> OKFImportPreview:
    today = today or dt.date.today().isoformat()
    warnings = check_okf_bundle(bundle_root).warnings
    concepts: list[OKFImportConcept] = []
    for rel, _path, values, body in _concepts(bundle_root):
        concept_id = rel.removesuffix(".md")
        okf_type = str(values.get("type") or "Concept")
        page_type = str(
            values.get("x_wiki_viva_page_type")
            or values.get("page_type")
            or slugify(okf_type).replace("-", "_")
            or "context_note"
        )
        title = _title(values, body, rel)
        page_id = str(
            values.get("x_wiki_viva_page_id")
            or values.get("page_id")
            or f"okf-{slugify(concept_id)}"
        )
        output_path = f"{memory_root.rstrip('/')}/okf-import/{rel}"
        concepts.append(
            OKFImportConcept(
                concept_id=concept_id,
                okf_type=okf_type,
                title=title,
                source_path=rel,
                suggested_page_id=page_id,
                suggested_page_type=page_type,
                suggested_output_path=output_path,
            )
        )
    return OKFImportPreview(
        schema_version=OKF_IMPORT_SCHEMA_VERSION,
        okf_version=OKF_VERSION,
        bundle_root=str(bundle_root),
        context=context,
        concept_count=len(concepts),
        concepts=concepts,
        warnings=warnings,
    )


def import_preview_to_dict(preview: OKFImportPreview) -> dict[str, Any]:
    data = asdict(preview)
    data["concepts"] = [asdict(item) for item in preview.concepts]
    return data


def _visualization_payload(bundle_root: Path) -> dict[str, Any]:
    concepts = _concepts(bundle_root)
    known = {rel for rel, _path, _values, _body in concepts}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    for rel, _path, values, body in concepts:
        nodes.append(
            {
                "id": rel,
                "title": _title(values, body, rel),
                "type": str(values.get("type") or "Concept"),
                "description": _description(values, body),
                "tags": list_values(values.get("tags")),
                "body": body,
            }
        )
        for match in MARKDOWN_LINK_RE.finditer(body):
            target = _bundle_link_target(bundle_root, rel, match.group(2))
            if target in known:
                edges.append({"source": rel, "target": target})
    return {"nodes": nodes, "edges": edges}


def generate_okf_visualization(bundle_root: Path, output_path: Path, *, name: str | None = None) -> OKFVisualizationResult:
    payload = _visualization_payload(bundle_root)
    title = name or bundle_root.name or "OKF bundle"
    data = json.dumps(payload, ensure_ascii=False)
    escaped_title = html.escape(title)
    html_text = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{escaped_title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; color: #172026; }}
header {{ padding: 16px 20px; border-bottom: 1px solid #d8dee4; }}
main {{ display: grid; grid-template-columns: 340px 1fr; min-height: calc(100vh - 66px); }}
aside {{ border-right: 1px solid #d8dee4; padding: 16px; overflow: auto; }}
section {{ padding: 20px; overflow: auto; }}
input {{ box-sizing: border-box; width: 100%; padding: 9px; margin-bottom: 12px; border: 1px solid #b6c2cf; }}
.node {{ display: block; width: 100%; text-align: left; border: 0; border-bottom: 1px solid #eef1f4; padding: 10px 0; background: white; cursor: pointer; }}
.node strong {{ display: block; }}
.node span {{ color: #5f6b76; font-size: 12px; }}
.meta {{ color: #5f6b76; }}
.edge {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
pre {{ white-space: pre-wrap; background: #f6f8fa; padding: 12px; overflow: auto; }}
</style>
<header>
  <h1>{escaped_title}</h1>
  <div class="meta"><span id="counts"></span></div>
</header>
<main>
  <aside>
    <input id="search" placeholder="Search title, type, tags, path">
    <div id="nodes"></div>
  </aside>
  <section>
    <h2 id="detail-title">Select a concept</h2>
    <p id="detail-meta" class="meta"></p>
    <p id="detail-description"></p>
    <h3>Links</h3>
    <div id="detail-links"></div>
    <h3>Markdown Body</h3>
    <pre id="detail-body"></pre>
  </section>
</main>
<script>
const bundle = {data};
const byId = new Map(bundle.nodes.map(n => [n.id, n]));
const outEdges = new Map();
const inEdges = new Map();
for (const e of bundle.edges) {{
  if (!outEdges.has(e.source)) outEdges.set(e.source, []);
  if (!inEdges.has(e.target)) inEdges.set(e.target, []);
  outEdges.get(e.source).push(e.target);
  inEdges.get(e.target).push(e.source);
}}
document.getElementById("counts").textContent = `${{bundle.nodes.length}} concepts, ${{bundle.edges.length}} links`;
function renderList() {{
  const q = document.getElementById("search").value.toLowerCase();
  const wrap = document.getElementById("nodes");
  wrap.innerHTML = "";
  for (const n of bundle.nodes) {{
    const hay = [n.id, n.title, n.type, ...(n.tags || [])].join(" ").toLowerCase();
    if (q && !hay.includes(q)) continue;
    const btn = document.createElement("button");
    btn.className = "node";
    btn.innerHTML = `<strong>${{escapeHtml(n.title)}}</strong><span>${{escapeHtml(n.type)}} · ${{escapeHtml(n.id)}}</span>`;
    btn.onclick = () => showNode(n.id);
    wrap.appendChild(btn);
  }}
}}
function showNode(id) {{
  const n = byId.get(id);
  if (!n) return;
  document.getElementById("detail-title").textContent = n.title;
  document.getElementById("detail-meta").textContent = `${{n.type}} · ${{n.id}}`;
  document.getElementById("detail-description").textContent = n.description || "";
  document.getElementById("detail-body").textContent = n.body || "";
  const links = document.getElementById("detail-links");
  links.innerHTML = "";
  for (const [label, ids] of [["Outgoing", outEdges.get(id) || []], ["Cited by", inEdges.get(id) || []]]) {{
    const h = document.createElement("h4");
    h.textContent = label;
    links.appendChild(h);
    if (!ids.length) {{
      const p = document.createElement("p");
      p.className = "meta";
      p.textContent = "None";
      links.appendChild(p);
      continue;
    }}
    for (const target of ids) {{
      const a = document.createElement("button");
      a.className = "node edge";
      a.textContent = target;
      a.onclick = () => showNode(target);
      links.appendChild(a);
    }}
  }}
}}
function escapeHtml(s) {{
  return String(s || "").replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}}[c]));
}}
document.getElementById("search").addEventListener("input", renderList);
renderList();
if (bundle.nodes[0]) showNode(bundle.nodes[0].id);
</script>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return OKFVisualizationResult(
        schema_version=OKF_VISUALIZATION_SCHEMA_VERSION,
        bundle_root=str(bundle_root),
        output_path=str(output_path),
        concepts=len(payload["nodes"]),
        edges=len(payload["edges"]),
        bytes=len(html_text.encode("utf-8")),
    )
