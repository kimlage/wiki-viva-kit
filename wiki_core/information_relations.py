"""Occurrence-preserving relation inventory shared by impact and information use.

No page/type exemptions: structural edges do not propagate factual freshness.
Untyped Markdown citations remain conservative dependencies. This report is
private operational evidence (paths/IDs), not a sanitized public export.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import posixpath
from urllib.parse import unquote, urlsplit
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.freshness import freshness_state, is_stale_exempt
from wiki_core.frontmatter import list_values, parse_frontmatter
from wiki_core.graph.page_graph import FRONTMATTER_REF_FIELDS, MARKDOWN_LINK_RE
from wiki_core.markdown_link_roles import parse_role_markdown, project_link_role
from wiki_core.semantic_inventory import (
    RELATION_DIRECTIONS, _authored_pages, _expected_relations, _page_indexes,
)

# These are relation semantics, never exemptions for whole pages or contexts.
STRUCTURAL = frozenset({"moc_parent", "collection_member", "ownership", "participation"})
ASSOCIATION = frozenset({"related_page", "related_holon", "navigation_link", "record_context_reference"})
REFERENCE = frozenset({"source_ref", "markdown_link", "untyped_reference"})
NAVIGATION_HEADINGS = frozenset({"related", "relacionados", "navigation", "navegação"})


def _path_from_link(root: Path, source_rel: str, href: str) -> str | None:
    """Lexical repository link; never follow a symlink while discovering sources."""
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.endswith("/"):
        return None
    path = unquote(parsed.path)
    if "\\" in path or any(ord(c) < 32 for c in path):
        return None
    relative = posixpath.normpath(path.lstrip("/") if path.startswith("/")
                                 else posixpath.join(posixpath.dirname(source_rel), path))
    return relative if relative != ".." and not relative.startswith("../") else None


def _body_occurrences(root: Path, path: str, body: str, navigation_targets: set[str]):
    """Exclude only complete, positively parsed navigation list items.

    Keep the existing conservative link inventory (including uncertain syntax)
    and use CommonMark block/inline structure solely to prove navigation. A
    nested heading cannot change the enclosing section, and a factual occurrence
    elsewhere in the same page is never suppressed by matching endpoints.
    """
    tokens, authored_roles = parse_role_markdown(body)
    sections = []
    navigation_ranges = []
    section = ""
    top_list = None
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0:
            section = tokens[index + 1].content.strip().casefold()
            sections.append((token.map[0], section))
        if token.level == 0 and token.type in {"bullet_list_open", "ordered_list_open"}:
            top_list = token.type
        if token.level == 0 and token.type in {"bullet_list_close", "ordered_list_close"}:
            top_list = None
        if not (token.type == "list_item_open" and token.level == 1
                and top_list == "bullet_list_open" and section in NAVIGATION_HEADINGS):
            continue
        end = index + 1
        while not (tokens[end].type == "list_item_close" and tokens[end].level == 1):
            end += 1
        item = tokens[index + 1:end]
        if [part.type for part in item] != ["paragraph_open", "inline", "paragraph_close"]:
            continue
        depth = 0
        links = 0
        link_only = True
        children = item[1].children or []
        # Existing MOC conventions also declare structural navigation in the
        # body. This is an exact relation label, not arbitrary text before ':';
        # Evidence/Source/Responsibility labels do not receive this treatment.
        explicit_moc = (bool(children) and children[0].type == "text"
                        and children[0].content.strip().casefold()
                        in {"moc:", "parent moc:", "moc pai:"})
        for child in children[1:] if explicit_moc else children:
            if child.type == "link_open":
                depth += 1
                links += 1
            elif child.type == "link_close":
                depth -= 1
            elif depth:
                continue  # Labels may contain formatting; they are still labels.
            elif child.type in {"softbreak", "hardbreak"}:
                continue
            elif child.type != "text" or re.sub(r"[\s,;.·|/()—–-]", "", child.content):
                link_only = False
        if link_only and links and depth == 0:
            navigation_ranges.append((*token.map, explicit_moc,
                                      children[0].content.strip() if explicit_moc else None))

    for match in MARKDOWN_LINK_RE.finditer(body):
        target = _path_from_link(root, path, match.group(1))
        if not target:
            continue
        line = body[:match.start()].count("\n")
        section = next((title for start, title in reversed(sections) if start <= line), "")
        matched = [(explicit, label) for start, end, explicit, label in navigation_ranges
                   if start <= line < end]
        explicit_moc = any(explicit for explicit, _label in matched)
        navigation = bool(matched) and (explicit_moc or target in navigation_targets)
        edge = dict(source=path, target=target,
                   type="navigation_link" if navigation else "markdown_link",
                   direction="directed", basis="markdown_body", path=path, field="body",
                   body_line=line + 1, body_offset=match.start(), section=section,
                   body_relation_label=next((label for explicit, label in matched if explicit), None),
                   classification=("explicit_body_moc_navigation" if navigation and explicit_moc
                                   else "local_typed_navigation_item" if navigation
                                   else "conservative_citation"))
        yield project_link_role(edge, authored_roles.get((match.start(), match.end())))

    # Reference-style links are real dependencies too. Their destination is
    # stored in a definition elsewhere, so the legacy inline regex misses them.
    for token_index, token in enumerate(tokens):
        if token.type != "inline" or token.map is None:
            continue
        for child_index, child in enumerate(token.children or []):
            if child.type != "link_open" or "label" not in child.meta:
                continue
            target = _path_from_link(root, path, child.attrGet("href") or "")
            if not target:
                continue
            # Conservative occurrence location is the entire inline block.
            # Reference-definition edits are separately a whole-page delta.
            edge = dict(source=path, target=target, type="markdown_link",
                       direction="directed", basis="markdown_body", path=path, field="body",
                       body_line=token.map[0] + 1,
                       body_offset=f"commonmark:{token_index}:{child_index}",
                       section=next((title for start, title in reversed(sections)
                                     if start <= token.map[0]), ""),
                       classification="reference_style_citation")
            yield project_link_role(edge, authored_roles.get(child.meta.get("_wiki_body_link_span")))


def authored_graph(root: Path, config: WikiConfig) -> dict[str, Any]:
    """Project the existing semantic-inventory model plus real Markdown body links."""
    pages = _authored_pages(root, config)
    _unique_by_id, by_path, duplicates = _page_indexes(pages)
    # Current duplicates block as integrity errors. Historical duplicates must
    # still be readable when the proposed change repairs them. Resolve ambiguous
    # IDs conservatively to every authored path instead of dropping their edges.
    by_id = {p.page_id: p for p in reversed(pages)}
    paths_by_id: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        paths_by_id[page.page_id].append(page.path)
    # Source emission duplicates the source_ref dependency in the same direction;
    # the inventory's optional event expansion is unnecessary for this closure.
    relations, unresolved = _expected_relations(pages, by_id, by_path, {})
    edges = []
    errors = list(duplicates) + list(unresolved)
    for source, target, kind, direction, basis, _pid, path, field in sorted(relations):
        if direction != RELATION_DIRECTIONS[kind]:
            errors.append(f"{path}: invalid relation direction in {field}")
            continue
        for a in paths_by_id[source]:
            for b in paths_by_id[target]:
                edges.append(dict(source=a, target=b, type=kind, direction=direction,
                                  basis=basis, path=path, field=field))
    node_values={p.path:p.values for p in pages}
    for page in pages:
        file = root / page.path
        if file.is_symlink():
            errors.append(f"{page.path}: symlink memory cannot establish freshness evidence")
        _values, body = parse_frontmatter(file)
        represented = {e["field"] for e in edges if e["path"] == page.path}
        for field in FRONTMATTER_REF_FIELDS:
            if field in represented:
                continue
            targets = set()
            for ref in list_values(page.values.get(field)):
                targets.update([ref] if ref in by_path else paths_by_id.get(ref, []))
            for target in sorted(targets):
                if field == "related_holons":
                    # The authored template-block contract uses this field for
                    # contextual reach (relations/culture), separately from
                    # source_refs/evidence. It does not assert factual support.
                    edges.append(dict(source=page.path, target=target, type="related_holon",
                                      direction="directed", basis="frontmatter", path=page.path,
                                      field=field))
                    continue
                if field == "owner":
                    edges.append(dict(source=target, target=page.path, type="ownership",
                                      direction="directed", basis="frontmatter", path=page.path,
                                      field=field))
                    continue
                # Untyped reachability metadata is not silently discarded.
                edges.append(dict(source=page.path, target=target, type="untyped_reference",
                                  direction="directed", basis="frontmatter", path=page.path,
                                  field=field))
        try:
            edges.extend(operational_consumption_edges(root, page.path, page.values, body,
                lambda ref: [ref] if ref in by_path else paths_by_id.get(ref, [])))
            edges.extend(projection_input_edges(page.path,page.values,node_values,default_context=config.default_context))
        except ValueError as exc:
            errors.append(f"{page.path}: {exc}")
        navigation_targets = {
            e["target"] if e["source"] == page.path else e["source"]
            for e in edges if e["path"] == page.path
            and e["type"] in STRUCTURAL | {"related_page", "related_holon"}
            and page.path in {e["source"], e["target"]}
        }
        for occurrence in _body_occurrences(root, page.path, body, navigation_targets):
            if occurrence["type"] != "operational_prerequisite":
                edges.append(occurrence)
    return {"documents": {p.path: (root / p.path).read_bytes().decode("utf-8") for p in pages},
            "nodes": {p.path: p.values for p in pages}, "edges": edges,
            "errors": sorted(set(errors))}


def semantic_equal(before: Any, after: Any) -> bool:
    """Do not let bool/number coercion conceal a changed declared fact."""
    if type(before) is not type(after):return False
    if isinstance(before,dict):
        return len(before)==len(after) and all(any(semantic_equal(k,other) and semantic_equal(v,value)
            for other,value in after.items()) for k,v in before.items())
    if isinstance(before,(list,tuple)):
        return len(before)==len(after) and all(semantic_equal(a,b) for a,b in zip(before,after))
    if isinstance(before,(set,frozenset)):
        return len(before)==len(after) and all(any(semantic_equal(a,b) for b in after) for a in before)
    return before==after


def projection_input_edges(consumer: str, values: dict, nodes: dict, *, default_context: str = '') -> list[dict]:
    """Compact producer inputs include candidates excluded by a display filter.

    Selectors only inspect the already loaded wiki. They grant no read, fetch,
    execution or verification capability and store no per-page hash registry.
    """
    declarations=values.get('projection_inputs',[])
    if not isinstance(declarations,list) or len(declarations)>32:
        raise ValueError('invalid projection inputs')
    edges=[]
    for declaration in declarations:
        known={'page_types','paths','fields','contexts','path_prefix','title_fallback','path_depth','file_names',
            'exclude_names','exclude_paths','status_excludes','status_exclude_prefixes','action_state_excludes','missing_fields'}
        if (not isinstance(declaration,dict) or 'fields' not in declaration or
            ('page_types' in declaration)==('paths' in declaration) or set(declaration)-known):
            raise ValueError('invalid projection input selector')
        for key in ('page_types','fields','contexts'):
            items=declaration.get(key,[])
            if (not isinstance(items,list) or len(items)>128
                or any(not (item is None and key=='page_types') and (not isinstance(item,str)
                    or not re.fullmatch(r'[a-z][a-z0-9_-]*',item)) for item in items)
                or len(set(items))!=len(items)):
                raise ValueError('invalid projection input fields')
        if not declaration['fields']:raise ValueError('empty projection input fields')
        if 'paths' in declaration:
            refs=declaration['paths']
            if set(declaration)-{'paths','fields'} or not isinstance(refs,list) or not refs or len(refs)>128:
                raise ValueError('invalid explicit projection inputs')
            for ref in refs:
                if (not isinstance(ref,str) or not ref or urlsplit(ref).scheme or ref.startswith('/') or
                    '\\' in ref or '..' in ref.split('/') or any(ord(c)<32 for c in ref) or posixpath.normpath(ref)!=ref):
                    raise ValueError('invalid projection input path')
                if ref!=consumer:
                    edges.append(dict(source=consumer,target=ref,type='projection',direction='directed',
                        basis='frontmatter',path=consumer,field='projection_inputs',
                        consumed_fields=sorted(declaration['fields']),produced_fields=['body','collection']))
            continue
        fallback=declaration.get('title_fallback',False)
        if type(fallback) is not bool and fallback!='blank':raise ValueError('invalid projection title fallback')
        depth=declaration.get('path_depth')
        if depth is not None and (type(depth) is not int or not 1<=depth<=32):raise ValueError('invalid projection path depth')
        for key in ('file_names','exclude_names','exclude_paths','status_excludes','status_exclude_prefixes','action_state_excludes','missing_fields'):
            items=declaration.get(key,[])
            if not isinstance(items,list) or len(items)>128 or any(not isinstance(item,str) or any(ord(c)<32 for c in item) for item in items):
                raise ValueError('invalid projection selection predicate')
        prefix=declaration.get('path_prefix','')
        if not isinstance(prefix,str) or (prefix and (prefix in {'.','..'} or prefix.startswith('/') or '..' in prefix.split('/') or '\\' in prefix
            or any(ord(c)<32 for c in prefix) or posixpath.normpath(prefix)!=prefix.rstrip('/'))):
            raise ValueError('invalid projection path prefix')
        if depth is not None and not prefix:raise ValueError('projection path depth requires a prefix')
        for name in declaration.get('file_names',[])+declaration.get('exclude_names',[]):
            if not name or '/' in name or '\\' in name or name in {'.','..'}:raise ValueError('invalid projection file name')
        if any(not p for p in declaration.get('status_exclude_prefixes',[])):
            raise ValueError('empty projection status prefix')
        for path,node in sorted(nodes.items()):
            if (path==consumer or (declaration['page_types'] and node.get('page_type') not in declaration['page_types'])
                or (declaration.get('contexts') and (node.get('context') or default_context) not in declaration['contexts'])
                or (prefix and not path.startswith(prefix.rstrip('/')+'/'))
                or (depth is not None and len(path[len(prefix.rstrip('/'))+1:].split('/'))!=depth)
                or (declaration.get('file_names') and posixpath.basename(path) not in declaration['file_names'])
                or path in declaration.get('exclude_paths',[]) or posixpath.basename(path) in declaration.get('exclude_names',[])
                or any(field in node for field in declaration.get('missing_fields',[]))
                or str(node.get('action_state') or '').strip() in declaration.get('action_state_excludes',[])):continue
            if node.get('status'):
                from wiki_core.action_state import normalize_status_label
                status=normalize_status_label(node['status'])
                if status in declaration.get('status_excludes',[]) or any(status.startswith(p) for p in declaration.get('status_exclude_prefixes',[])):continue
            fields=set(declaration['fields']) | {'page_type'}
            if declaration.get('contexts'):fields.add('context')
            title=str(node.get('title') or '').strip() if fallback=='blank' else node.get('title')
            if fallback and 'title' in fields and not title:fields.add('body')
            edges.append(dict(source=consumer,target=path,type='projection',direction='directed',
                basis='frontmatter',path=consumer,field='projection_inputs',
                consumed_fields=sorted(fields),produced_fields=['body','collection']))
    return edges



def dependency_edges(graph: dict, *, origin: str = "current") -> tuple[list[dict], list[dict]]:
    """One occurrence-preserving normalization for audit, freshness and readers.

    Structural/context/review edges remain in the inventory. They are not
    assertions that the dependent consumes every fact on the linked page.
    Multiple relations between the same endpoints are deliberately retained.
    """
    dependencies, contextual = [], []
    for raw in graph['edges']:
        edge = {**raw, 'origin': origin}
        kind = edge['type']
        if kind in STRUCTURAL | ASSOCIATION | {'review_record'}:
            contextual.append({**edge, 'reason': 'noncurrent_information_relation'})
            continue
        a, b = edge['source'], edge['target']
        prerequisite, dependent = (b, a) if kind in REFERENCE | {'operational_prerequisite', 'projection_state', 'projection', 'historical_support'} else (a, b)
        dependencies.append({**edge, 'prerequisite': prerequisite, 'dependent': dependent,
                             'consumed_fields': edge.get('consumed_fields') or edge.get('requirement', {}).get('fields') or (['action_state'] if kind == 'projection_state' else ['*']),
                             'produced_fields': edge.get('produced_fields') or (['body', 'collection'] if kind == 'projection_state' else ['*']),
                             'temporal_use': edge.get('requirement', {}).get('temporal') or ('current' if kind == 'operational_prerequisite' else 'as_observed' if kind == 'historical_support' else 'unspecified')})
    return dependencies, contextual


def information_requirements(values: dict, resolve) -> list[dict]:
    """Normalize authored current/historical consumption into the same edges.

    A requirement describes an intended use, not an exception to PR review or
    proof that the source is verified. Unknown fields/targets fail closed.
    """
    raw = values.get('information_requirements', [])
    if not isinstance(raw, list) or len(raw) > 64:
        raise ValueError('information_requirements must be a bounded list')
    result = []
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) != {'target', 'fields', 'temporal', 'max_age_days'}:
            raise ValueError('information requirement needs target, fields, temporal, max_age_days')
        if (not isinstance(entry['target'], str) or not isinstance(entry['fields'], list)
                or not entry['fields'] or len(entry['fields']) > 32
                or any(not isinstance(f, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', f) for f in entry['fields'])
                or len(set(entry['fields'])) != len(entry['fields'])
                or entry['temporal'] not in {'current', 'historical'}
                or type(entry['max_age_days']) is not int or not 0 <= entry['max_age_days'] <= 3650):
            raise ValueError('invalid information requirement selector or temporal use')
        targets = resolve(entry['target'])
        if len(targets) != 1:
            raise ValueError('information requirement target is missing or ambiguous')
        result.append({**entry, 'target': targets[0]})
    return result


def operational_consumption_edges(root: Path, path: str, values: dict, body: str, resolve) -> list[dict]:
    """The same operational declarations feed readers, agents and admission."""
    edges = [dict(source=path, target=r['target'], type='operational_prerequisite',
                  direction='directed', basis='frontmatter', path=path,
                  field='information_requirements', requirement=r)
             for r in information_requirements(values, resolve)]
    edges.extend(edge for edge in _body_occurrences(root, path, body, set())
                 if edge['type'] == 'operational_prerequisite')
    return edges
