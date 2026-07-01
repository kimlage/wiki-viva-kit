from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from wiki_core.closure import build_ingestion_closure_report
from wiki_core.config import WikiConfig, load_config
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph import build_page_graph
from wiki_core.paths import WikiPaths
from wiki_core.quality import build_quality_report
from wiki_core.web.commands import build_action_cards
from wiki_core.web.git_ops import build_git_state
from wiki_core.web.schemas import SNAPSHOT_FILES, WEB_GATE_SCHEMA_VERSION, WEB_SNAPSHOT_SCHEMA_VERSION

H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _repo_commit(root: Path) -> str | None:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _title(values: dict[str, Any], body: str, fallback: str) -> str:
    explicit = str(values.get("title") or "").strip()
    if explicit:
        return explicit
    match = H1_RE.search(body)
    if match:
        return match.group(1).strip()
    return str(values.get("page_id") or fallback)


def _summary(body: str) -> str:
    lines: list[str] = []
    in_code = False
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith(("#", "|", "---", "<!--")):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        lines.append(line)
        if len(" ".join(lines)) > 240:
            break
    text = " ".join(lines)
    return text[:260].rstrip()


def _freshness_state(values: dict[str, Any], *, today: dt.date | None = None) -> str:
    updated = str(values.get("updated_at") or values.get("date") or "").strip()
    if not updated:
        return "unknown"
    try:
        updated_date = dt.date.fromisoformat(updated[:10])
    except ValueError:
        return "unknown"
    try:
        window = int(values.get("stale_after_days") or 0)
    except (TypeError, ValueError):
        window = 0
    if window <= 0:
        return "unknown"
    return "stale" if ((today or _today()) - updated_date).days > window else "fresh"


def _page_id(values: dict[str, Any], rel: str) -> str:
    return str(values.get("page_id") or rel).strip()


def _markdown_pages(root: Path, config: WikiConfig) -> list[Path]:
    memory_root = root / config.paths["memory_root"]
    if not memory_root.exists():
        return []
    return sorted(path for path in memory_root.rglob("*.md") if path.is_file())


def _page_record(root: Path, path: Path, config: WikiConfig, *, today: dt.date | None = None) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    values, body = parse_frontmatter(path)
    source_refs = list_values(values.get("source_refs"))
    return {
        "id": _page_id(values, rel),
        "path": rel,
        "title": _title(values, body, rel),
        "page_type": str(values.get("page_type") or ""),
        "context": str(values.get("context") or config.default_context),
        "visibility": str(values.get("visibility") or config.default_visibility),
        "status": str(values.get("status") or ""),
        "updated_at": str(values.get("updated_at") or ""),
        "stale_after_days": str(values.get("stale_after_days") or ""),
        "freshness_state": _freshness_state(values, today=today),
        "approved_state": "approved",
        "risk_flags": [],
        "source_refs": source_refs,
        "moc_parent": str(values.get("moc_parent") or ""),
        "summary": _summary(body),
    }


def _pages_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    today = _today()
    pages = [_page_record(root, path, config, today=today) for path in _markdown_pages(root, config)]
    pages.sort(key=lambda item: (str(item["context"]), str(item["title"]), str(item["path"])))
    return {
        "schema_version": "wiki_web_pages.v1",
        "repo_id": config.repo_id,
        "pages": pages,
    }


def _graph_payload(root: Path, config: WikiConfig, pages_payload: dict[str, Any]) -> dict[str, Any]:
    graph = build_page_graph(root, config)
    pages_by_path = {str(page["path"]): page for page in pages_payload["pages"]}
    id_by_path = {
        rel: (node.page_id or rel)
        for rel, node in graph.nodes.items()
    }
    nodes = []
    edges = []
    for rel, node in graph.nodes.items():
        page = pages_by_path.get(rel, {})
        nodes.append(
            {
                "id": id_by_path[rel],
                "path": rel,
                "title": page.get("title") or node.title or node.page_id or rel,
                "page_type": node.page_type,
                "context": node.context or config.default_context,
                "visibility": node.visibility,
                "status": page.get("status") or "",
                "updated_at": node.updated_at,
                "stale_after_days": node.stale_after_days,
                "freshness_state": page.get("freshness_state") or "unknown",
                "approved_state": "approved",
                "risk_flags": page.get("risk_flags") or [],
                "metrics": {
                    "inbound_links": len(node.inbound_links),
                    "outbound_links": len(node.outbound_links),
                    "source_ref_count": len(page.get("source_refs") or []),
                },
            }
        )
        for target in node.outbound_body_links:
            if target in id_by_path:
                edges.append(
                    {
                        "source": id_by_path[rel],
                        "target": id_by_path[target],
                        "type": "markdown_link",
                        "status": "valid",
                        "weight": 1,
                    }
                )
        for target in node.outbound_frontmatter_refs:
            if target in id_by_path:
                edge_type = "moc_parent" if target == page.get("moc_parent") else "source_ref"
                edges.append(
                    {
                        "source": id_by_path[rel],
                        "target": id_by_path[target],
                        "type": edge_type,
                        "status": "valid",
                        "weight": 2 if edge_type == "moc_parent" else 1,
                    }
                )
    return {
        "schema_version": "wiki_web_graph.v1",
        "repo_id": config.repo_id,
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(edges, key=lambda item: (str(item["source"]), str(item["target"]), str(item["type"]))),
        "wanted_pages": {target: list(refs) for target, refs in graph.wanted_pages.items()},
    }


def _section_records(markdown: str) -> list[dict[str, Any]]:
    matches = list(H2_RE.finditer(markdown))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        bullets = [line[2:].strip() for line in body.splitlines() if line.strip().startswith("- ")]
        sections.append({"title": match.group(1).strip(), "body": body, "bullets": bullets})
    return sections


def _operations_payload(root: Path, config: WikiConfig) -> dict[str, Any]:
    paths = WikiPaths(root, config)
    values: dict[str, Any] = {}
    body = ""
    if paths.operation_page.exists():
        values, body = parse_frontmatter(paths.operation_page)
    return {
        "schema_version": "wiki_web_operations.v1",
        "repo_id": config.repo_id,
        "path": config.paths["operation_page"],
        "title": _title(values, body, "Operations"),
        "updated_at": str(values.get("updated_at") or ""),
        "stale_after_days": str(values.get("stale_after_days") or ""),
        "freshness_state": _freshness_state(values),
        "sections": _section_records(body),
    }


def _sources_payload(pages_payload: dict[str, Any]) -> dict[str, Any]:
    sources = [
        page
        for page in pages_payload["pages"]
        if str(page.get("page_type") or "").startswith("source")
        or "/sources/" in str(page.get("path") or "")
    ]
    return {"schema_version": "wiki_web_sources.v1", "sources": sources}


def _decisions_payload(pages_payload: dict[str, Any]) -> dict[str, Any]:
    decisions = [page for page in pages_payload["pages"] if page.get("page_type") == "decision"]
    return {"schema_version": "wiki_web_decisions.v1", "decisions": decisions}


def _freshness_payload(pages_payload: dict[str, Any], config: WikiConfig) -> dict[str, Any]:
    pages = pages_payload["pages"]
    counts = {"fresh": 0, "stale": 0, "unknown": 0}
    by_context: dict[str, dict[str, int]] = {}
    stale_pages: list[dict[str, str]] = []
    for page in pages:
        state = str(page.get("freshness_state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
        context = str(page.get("context") or config.default_context)
        by_context.setdefault(context, {"fresh": 0, "stale": 0, "unknown": 0})
        by_context[context][state] = by_context[context].get(state, 0) + 1
        if state == "stale":
            stale_pages.append(
                {"path": str(page["path"]), "title": str(page["title"]), "context": context}
            )
    return {
        "schema_version": "wiki_web_freshness.v1",
        "summary": counts,
        "by_context": dict(sorted(by_context.items())),
        "stale_pages": sorted(stale_pages, key=lambda item: item["path"]),
    }


def _gates_payload() -> dict[str, Any]:
    commands = (
        ("wiki_audit", ["python3", "scripts/wiki_audit.py", "--check"]),
        ("methodology_coverage", ["python3", "scripts/wiki_check_methodology_coverage.py", "--check"]),
        ("operation_compile", ["python3", "scripts/wiki_operation_compile.py", "--check"]),
        ("input_stage", ["python3", "scripts/wiki_input_stage.py", "--check"]),
        ("pytest", ["python3", "-m", "pytest", "tests/"]),
    )
    return {
        "schema_version": WEB_GATE_SCHEMA_VERSION,
        "status": "not_run",
        "gates": [
            {"id": gate_id, "status": "not_run", "argv": argv}
            for gate_id, argv in commands
        ],
    }


def _commands_payload(actions_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wiki_web_commands.v1",
        "commands": [
            command
            for action in actions_payload["actions"]
            for command in action.get("commands", [])
        ],
    }


def _safe_quality(root: Path, config: WikiConfig) -> dict[str, Any]:
    try:
        report = build_quality_report(root, config)
    except Exception as exc:  # pragma: no cover - defensive snapshot surface
        return {"schema_version": "wiki_quality_report.v1", "error": str(exc)}
    return report


def _safe_ingestion(root: Path, config: WikiConfig) -> dict[str, Any]:
    try:
        return build_ingestion_closure_report(root, config)
    except Exception as exc:  # pragma: no cover - defensive snapshot surface
        return {"schema_version": "wiki_ingestion_closure.v1", "error": str(exc)}


def build_snapshot(
    root: Path,
    config: WikiConfig | None = None,
    *,
    mode: str = "static",
    generated_at: str | None = None,
) -> dict[str, dict[str, Any]]:
    config = config or load_config(root)
    generated_at = generated_at or _utc_now()
    git_payload = build_git_state(root, config)
    manifest = {
        "schema_version": WEB_SNAPSHOT_SCHEMA_VERSION,
        "repo": {
            "repo_id": config.repo_id,
            "language": config.language,
            "memory_root": config.paths["memory_root"],
            "default_branch": git_payload.get("default_branch") or "main",
            "branch_prefix": config.approval.get("branch_prefix", "wiki/"),
        },
        "generated_at": generated_at,
        "source_commit": _repo_commit(root),
        "mode": mode,
        "files": list(SNAPSHOT_FILES),
    }
    pages = _pages_payload(root, config)
    actions = build_action_cards(config)
    payloads = {
        "manifest.json": manifest,
        "operations.json": _operations_payload(root, config),
        "graph.json": _graph_payload(root, config, pages),
        "pages.json": pages,
        "sources.json": _sources_payload(pages),
        "actions.json": actions,
        "decisions.json": _decisions_payload(pages),
        "freshness.json": _freshness_payload(pages, config),
        "gates.json": _gates_payload(),
        "git.json": git_payload,
        "ingestion.json": _safe_ingestion(root, config),
        "quality.json": _safe_quality(root, config),
        "commands.json": _commands_payload(actions),
    }
    return payloads


def write_snapshot(
    root: Path,
    out_dir: Path,
    config: WikiConfig | None = None,
    *,
    clean: bool = False,
    mode: str = "static",
) -> dict[str, Path]:
    payloads = build_snapshot(root, config, mode=mode)
    if clean and out_dir.exists():
        for path in out_dir.glob("*.json"):
            path.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, payload in payloads.items():
        target = out_dir / name
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written[name] = target
    return written
