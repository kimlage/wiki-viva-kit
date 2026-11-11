from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from wiki_core.traversal import wiki_markdown_files
from wiki_core.config import WikiConfig
from wiki_core.frontmatter import list_values as _fm_list_values
from wiki_core.frontmatter import parse_frontmatter_flat

PAGE_GRAPH_SCHEMA_VERSION = "wiki_page_graph.v1"

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
FRONTMATTER_REF_FIELDS = (
    "source_refs",
    "collection_refs",
    "claims",
    "decisions",
    "actions",
    "evidence_refs",
    "related_pages",
    "consolidated_into",
    "backlinks_expected",
    "moc_parent",
    "owner",
    "roles",
    "responsibilities",
    "assignments",
    "related_holons",
    "supersedes",
    "superseded_by",
    "conflicts_with",
)
DEFAULT_ORPHAN_EXEMPT_TYPES = {
    "root_index",
    "context_hub",
    "ontology_index",
    "dashboard",
    "system_log",
    "source_registry",
    "source_catalog",
    "coverage",
    "operational_rule",
    "ingestion_event",
}
DEFAULT_IMPACT_EXEMPT_TYPES = {
    "root_index",
    "context_hub",
    "ontology_index",
    "dashboard",
    "system_log",
    "source_registry",
    "source_catalog",
    "coverage",
    "operational_rule",
    "ingestion_event",
}


@dataclass(frozen=True)
class PageNode:
    rel: str
    page_id: str
    title: str
    page_type: str
    context: str
    aliases: tuple[str, ...] = ()
    outbound_body_links: tuple[str, ...] = ()
    outbound_frontmatter_refs: tuple[str, ...] = ()
    inbound_links: tuple[str, ...] = ()
    orphan_exempt: bool = False
    visibility: str = ""
    stale_after_days: str = ""
    updated_at: str = ""

    @property
    def outbound_links(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.outbound_body_links) | set(self.outbound_frontmatter_refs)))


@dataclass(frozen=True)
class PageGraph:
    root: Path
    memory_root: str
    nodes: dict[str, PageNode]
    aliases: dict[str, str]
    wanted_pages: dict[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class ImpactResult:
    changed_pages: tuple[str, ...]
    affected_pages: tuple[str, ...]
    references: dict[str, tuple[str, ...]]
    removed_pages: tuple[str, ...] = ()
    skipped: str | None = None


def _memory_prefix(config: WikiConfig) -> str:
    return str(config.paths["memory_root"]).rstrip("/") + "/"


def is_context_instruction(rel: str, memory_root: str, known_paths: set[str]) -> bool:
    """Recognize instruction files only in an indexed memory context."""
    prefix = memory_root.rstrip("/") + "/"
    path = Path(rel)
    return (
        rel.startswith(prefix)
        and path.name in {"AGENTS.md", "AGENTS.override.md"}
        and (path.parent / "index.md").as_posix() in known_paths
    )


def _is_external(href: str) -> bool:
    try:
        parsed = urlparse(href)
    except ValueError:
        # Invalid URL authorities are never local page dependencies.
        return True
    return bool(parsed.scheme) or href.startswith("#") or href.startswith("mailto:")


def _repo_rel(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _markdown_files(root: Path, memory_root: str) -> list[Path]:
    base = root / memory_root.rstrip("/")
    if not base.exists():
        return []
    return sorted(p for p in wiki_markdown_files(base, wiki_root=root) if p.is_file())


def parse_frontmatter(path: Path) -> dict[str, Any]:
    """Flat (string-flattening) frontmatter parse for the link graph.

    Thin wrapper over the canonical :func:`wiki_core.frontmatter.parse_frontmatter_flat`.
    Re-exported here because ``closure``, ``quality`` and ``source_config`` import
    it from this module; the graph wraps every read in ``str(...)`` so the flat
    contract is what they expect.
    """
    return parse_frontmatter_flat(path)


def select_page_graph_inputs(inventory: dict, config: WikiConfig) -> dict:
    """Select worktree Markdown candidates without opening their bodies.

    The host must qualify the approved configuration, inventory, actor and
    worktree aliases independently. Known Git-object aliases are refused here;
    worktree metadata alone does not prove the content or absence of an alias.
    Missing tracked/HEAD Markdown is conservatively unavailable. The result is
    not a complete audit or a host admission.
    """
    from wiki_core.audit_r1_inventory import select
    from wiki_core.context_policy import PolicyError, safe_path
    from wiki_core.traversal import is_protected_artifact

    try:
        configured = config.paths['memory_root']
        if not isinstance(configured, str) or not configured:
            raise PolicyError('graph selection unavailable')
        memory_root = safe_path(configured.rstrip('/'), allow_root=True)
        prefix = '' if memory_root == '.' else memory_root + '/'
        physical = inventory['physical']['files']
        head_tree = inventory['trees'][inventory['head']]
        def candidate(path):
            return (path.startswith(prefix) and path.endswith('.md')
                    and not is_protected_artifact(Path(path)))
        missing = set(inventory['missing_tracked']) | (set(head_tree) - set(physical))
        if any(candidate(path) for path in missing):
            raise PolicyError('graph selection unavailable')
        names = sorted(path for path in physical if candidate(path))
        selection = select(inventory, [{'kind': 'worktree', 'path': path} for path in names])
        limits = selection['limits']
        sizes = [entry['size'] for entry in selection['inputs']]
        if (any(size < 0 or size > limits['max_item_bytes'] for size in sizes)
                or sum(sizes) > limits['max_total_bytes']):
            raise PolicyError('graph selection unavailable')
        aliases = set(inventory['denied_oid_aliases'])
        selected = set(names)
        if (any(path in selected and entry['oid'] in aliases for path, entry in head_tree.items())
                or any(entry['path'] in selected and entry['oid'] in aliases
                       for entry in inventory['index'])
                or any(entry['path'] in selected and entry['stage'] != 0
                       for entry in inventory['index'])):
            raise PolicyError('graph selection unavailable')
        plan = {'memory_root': memory_root, 'selection': selection,
                'coverage': 'worktree_graph_markdown_only',
                'configured_root': 'external_not_verified',
                'worktree_content_aliases': 'external_not_verified',
                'bootstrap_and_output_audience': 'external_not_verified',
                'host_admission': 'external_not_verified',
                'global_audit': 'not_performed'}
        plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=True,
                                            separators=(',', ':')).encode()).hexdigest()
        return plan
    except (KeyError, TypeError, AttributeError) as exc:
        raise PolicyError('graph selection unavailable') from exc


def _list_values(value: Any) -> tuple[str, ...]:
    return tuple(_fm_list_values(value))


def _path_from_link(root: Path, source_rel: str, href: str, *, lexical: bool = False) -> str | None:
    href = unquote(href.split("#", 1)[0]).strip()
    if not href or _is_external(href):
        return None
    if lexical:
        # Selected inventory already rejects symlinks; resolve link syntax
        # without consulting paths outside the admitted filesystem snapshot.
        candidate = (href.lstrip('/') if href.startswith('/')
                     else posixpath.join(posixpath.dirname(source_rel), href))
        rel = posixpath.normpath(candidate)
        if rel in ('.', '..') or rel.startswith('../') or rel.startswith('/'):
            return None
    else:
        if href.startswith("/"):
            candidate = root / href.lstrip("/")
        else:
            candidate = (root / source_rel).parent / href
        rel = _repo_rel(root, candidate)
    if rel and rel.endswith(".md"):
        return rel
    return None


def _markdown_body_links(root: Path, source_rel: str, text: str, *, lexical: bool = False) -> tuple[str, ...]:
    out: set[str] = set()
    for match in MARKDOWN_LINK_RE.finditer(text):
        rel = _path_from_link(root, source_rel, match.group(1), lexical=lexical)
        if rel:
            out.add(rel)
    return tuple(sorted(out))


def _frontmatter_refs(values: dict[str, Any], page_id_to_rel: dict[str, str]) -> tuple[str, ...]:
    out: set[str] = set()
    for field_name in FRONTMATTER_REF_FIELDS:
        for raw in _list_values(values.get(field_name)):
            if raw in page_id_to_rel:
                out.add(page_id_to_rel[raw])
            elif raw.endswith(".md"):
                out.add(raw)
            elif "/" in raw and not raw.startswith(("http://", "https://")):
                target = raw.rstrip("/")
                if target.endswith(".md"):
                    out.add(target)
    return tuple(sorted(out))


def _aliases(values: dict[str, Any]) -> tuple[str, ...]:
    aliases = list(_list_values(values.get("aliases")))
    title = values.get("title")
    if isinstance(title, str) and title.strip():
        aliases.insert(0, title.strip())
    return tuple(dict.fromkeys(aliases))


def build_page_graph(root: Path, config: WikiConfig, *, reads=None) -> PageGraph:
    """Build the graph from the filesystem or an already-admitted reader.

    Supplying a reader does not qualify its selection, authority, metadata or
    coverage; those remain the caller's responsibility. An unavailable body
    propagates the reader's error instead of silently omitting a page.
    """
    memory_root = _memory_prefix(config)
    if reads is None:
        files = _markdown_files(root, memory_root)
    else:
        files = sorted(reads.markdown(root / memory_root.rstrip('/'), root))
        reads.require_files(files)

    frontmatter_by_rel: dict[str, dict[str, Any]] = {}
    selected_texts: dict[str, str] = {}
    page_id_to_rel: dict[str, str] = {}
    for path in files:
        rel = path.relative_to(root).as_posix()
        if reads is None:
            values = parse_frontmatter(path)
        else:
            text = reads.read_text(path, errors='replace')
            selected_texts[rel] = text
            values = parse_frontmatter_flat(text)
        frontmatter_by_rel[rel] = values
        page_id = str(values.get("page_id") or "").strip()
        if page_id:
            page_id_to_rel.setdefault(page_id, rel)

    outbound_body: dict[str, tuple[str, ...]] = {}
    outbound_refs: dict[str, tuple[str, ...]] = {}
    wanted: dict[str, set[str]] = {}
    known_rels = set(frontmatter_by_rel)
    for path in files:
        rel = path.relative_to(root).as_posix()
        text = (path.read_text(encoding="utf-8", errors="replace")
                if reads is None else selected_texts[rel])
        body_links = _markdown_body_links(root, rel, text, lexical=reads is not None)
        fm_refs = _frontmatter_refs(frontmatter_by_rel[rel], page_id_to_rel)
        outbound_body[rel] = tuple(link for link in body_links if link in known_rels)
        outbound_refs[rel] = tuple(ref for ref in fm_refs if ref in known_rels)
        for target in set(body_links) | set(fm_refs):
            if target not in known_rels:
                wanted.setdefault(target, set()).add(rel)

    inbound: dict[str, set[str]] = {rel: set() for rel in known_rels}
    for rel in known_rels:
        for target in set(outbound_body[rel]) | set(outbound_refs[rel]):
            inbound.setdefault(target, set()).add(rel)

    nodes: dict[str, PageNode] = {}
    alias_map: dict[str, str] = {}
    for rel, values in frontmatter_by_rel.items():
        aliases = _aliases(values)
        for alias in aliases:
            alias_map.setdefault(alias.lower(), rel)
        nodes[rel] = PageNode(
            rel=rel,
            page_id=str(values.get("page_id") or "").strip(),
            title=str(values.get("title") or "").strip(),
            page_type=str(values.get("page_type") or "").strip(),
            context=str(values.get("context") or "").strip(),
            aliases=aliases,
            outbound_body_links=outbound_body.get(rel, ()),
            outbound_frontmatter_refs=outbound_refs.get(rel, ()),
            inbound_links=tuple(sorted(inbound.get(rel, set()))),
            orphan_exempt=str(values.get("orphan_exempt") or "").lower() in {"true", "yes", "on", "1"},
            visibility=str(values.get("visibility") or "").strip(),
            stale_after_days=str(values.get("stale_after_days") or "").strip(),
            updated_at=str(values.get("updated_at") or "").strip(),
        )
    return PageGraph(
        root=root,
        memory_root=memory_root,
        nodes=dict(sorted(nodes.items())),
        aliases=dict(sorted(alias_map.items())),
        wanted_pages={target: tuple(sorted(refs)) for target, refs in sorted(wanted.items())},
    )


def unreachable_pages(graph: PageGraph, root_page: str) -> tuple[str, ...]:
    if root_page not in graph.nodes:
        return tuple(graph.nodes)
    seen = {root_page}
    queue: deque[str] = deque([root_page])
    while queue:
        rel = queue.popleft()
        for target in graph.nodes[rel].outbound_links:
            if target not in seen and target in graph.nodes:
                seen.add(target)
                queue.append(target)
    return tuple(sorted(set(graph.nodes) - seen))


def orphan_pages(graph: PageGraph, exempt_types: set[str] | None = None) -> tuple[str, ...]:
    exempt = DEFAULT_ORPHAN_EXEMPT_TYPES | (exempt_types or set())
    out: list[str] = []
    for rel, node in graph.nodes.items():
        if node.page_type in exempt or node.orphan_exempt:
            continue
        if not node.inbound_links:
            out.append(rel)
    return tuple(sorted(out))


def min_outbound_violations(
    graph: PageGraph, *, minimum: int, exempt_types: set[str] | None = None
) -> tuple[str, ...]:
    exempt = DEFAULT_ORPHAN_EXEMPT_TYPES | (exempt_types or set())
    out: list[str] = []
    for rel, node in graph.nodes.items():
        if node.page_type in exempt or node.orphan_exempt:
            continue
        if len(node.outbound_links) < minimum:
            out.append(rel)
    return tuple(sorted(out))


def compute_impact(
    graph: PageGraph,
    changed_paths: set[str],
    *,
    exempt_types: set[str] | None = None,
    base_graph: PageGraph | None = None,
) -> ImpactResult:
    """Compute current and deletion impact against one explicit review base.

    A removed page is absent from the current graph by definition.  When an
    exact ``base_graph`` is supplied, keep that page in the changed set and use
    the base graph's resolved backlinks to identify surviving pages that must
    be reviewed.  Callers that collect Git deletions must therefore provide the
    matching base graph instead of silently treating a removal as no impact.
    """

    exempt = DEFAULT_IMPACT_EXEMPT_TYPES | (exempt_types or set())
    current_changed_pages = {
        path
        for path in changed_paths
        if path in graph.nodes and graph.nodes[path].page_type not in exempt
    }
    removed_pages = {
        path
        for path in changed_paths
        if path not in graph.nodes
        and base_graph is not None
        and path in base_graph.nodes
        and base_graph.nodes[path].page_type not in exempt
    }
    changed_pages = current_changed_pages | removed_pages
    if not changed_pages:
        return ImpactResult(
            changed_pages=(),
            affected_pages=(),
            references={},
            removed_pages=(),
        )
    references: dict[str, list[str]] = {}
    affected: set[str] = set()
    for rel, node in graph.nodes.items():
        if rel in changed_pages or node.page_type in exempt:
            continue
        hits = set(node.outbound_links) & changed_pages
        if removed_pages and base_graph is not None:
            base_node = base_graph.nodes.get(rel)
            if base_node is not None:
                hits.update(set(base_node.outbound_links) & removed_pages)
        if hits:
            affected.add(rel)
            references[rel] = sorted(hits)
    return ImpactResult(
        changed_pages=tuple(sorted(changed_pages)),
        affected_pages=tuple(sorted(affected)),
        references={rel: tuple(targets) for rel, targets in sorted(references.items())},
        removed_pages=tuple(sorted(removed_pages)),
    )


def graph_to_dict(graph: PageGraph) -> dict[str, Any]:
    return {
        "schema_version": PAGE_GRAPH_SCHEMA_VERSION,
        "memory_root": graph.memory_root,
        "pages": [
            {
                "path": node.rel,
                "page_id": node.page_id,
                "page_type": node.page_type,
                "context": node.context,
                "title": node.title,
                "aliases": list(node.aliases),
                "outbound_body_links": list(node.outbound_body_links),
                "outbound_frontmatter_refs": list(node.outbound_frontmatter_refs),
                "inbound_links": list(node.inbound_links),
                "orphan_exempt": node.orphan_exempt,
                "visibility": node.visibility,
                "updated_at": node.updated_at,
                "stale_after_days": node.stale_after_days,
            }
            for node in graph.nodes.values()
        ],
        "aliases": graph.aliases,
        "wanted_pages": {target: list(refs) for target, refs in graph.wanted_pages.items()},
    }
