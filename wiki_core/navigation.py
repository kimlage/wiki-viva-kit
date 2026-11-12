"""Git-proven physical page relocation; discovery never grants read/write authority.

There is no alias registry. An unchanged document can retain a reference it
actually contained when the old target existed. Relocation requires a unique
explicit page_id, continuous Git ancestry and byte-identical moves. Deletion,
copy ambiguity and a simultaneous move/rewrite cannot establish identity.
"""
from __future__ import annotations

import hashlib
import posixpath
import re
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from wiki_core.config import load_config
from wiki_core.context_policy import UniqueLoader, safe_path
from wiki_core.frontmatter import FRONTMATTER_RE
from wiki_core.git_env import local_git_tree
from wiki_core.graph.page_graph import MARKDOWN_LINK_RE
from wiki_core.markdown_link_roles import parse_role_markdown
from wiki_core.traversal import require_wiki_boundaries, require_wiki_path, wiki_markdown_files


def document(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        values = yaml.load(match[1], Loader=UniqueLoader)
    except yaml.YAMLError:
        raise ValueError('invalid navigation document') from None
    if not isinstance(values, dict):
        raise ValueError('invalid navigation document')
    return values, text[match.end():]


def link_path(source: str, href: str) -> str | None:
    if href.startswith('<') and href.endswith('>'):
        href = href[1:-1]
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path = unquote(parsed.path)
    if '\\' in path or any(ord(c) < 32 for c in path):
        return None
    relative = posixpath.normpath(path.lstrip('/') if path.startswith('/') else
                                 posixpath.join(posixpath.dirname(source), path))
    try:
        return safe_path(relative)
    except ValueError:
        return None


def inline_links(body: str):
    """Only actual, uniquely located CommonMark inline links; never code/images."""
    tokens, _ = parse_role_markdown(body)
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans = set()
    for token in tokens:
        if token.type != 'inline' or token.map is None or not token.content:
            continue
        start, end = (offsets[n] for n in token.map)
        block = body[start:end]
        relative = block.find(token.content)
        if relative < 0 or block.find(token.content, relative + 1) >= 0:
            continue
        for child in token.children or []:
            span = child.meta.get('_wiki_link_span') if child.type == 'link_open' else None
            if span:
                spans.add((start + relative + span[0], start + relative + span[1]))
    return [m for m in MARKDOWN_LINK_RE.finditer(body) if m.span() in spans]


def dated_records(body: str):
    """Exact H2 records, excluding only blank separators between records."""
    tokens, _ = parse_role_markdown(body)
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    starts = [offsets[t.map[0]] for t in tokens if t.type == 'heading_open' and t.tag == 'h2']
    if not starts:
        return None
    records = []
    for start, stop in zip(starts, [*starts[1:], len(body)]):
        if not re.match(r'## \[\d{4}-\d{2}-\d{2}[^\r\n]*\][ \t]', body[start:]):
            return None
        core = body[start:stop].rstrip('\r\n')
        suffix = body[start + len(core):stop]
        newline = '\r\n' if suffix.startswith('\r\n') else '\n' if suffix.startswith('\n') else ''
        records.append((start, start + len(core) + len(newline), core + newline))
    return body[:starts[0]], records


def preserved_records(before: str, after: str):
    """An injective, ordered mapping of complete records, never substrings."""
    old, new = dated_records(before), dated_records(after)
    if old is None or new is None or old[0] != new[0]:
        return None
    mapping, last = [], -1
    for start, end, record in old[1]:
        matches = [(i, offset) for i, (offset, _, value) in enumerate(new[1]) if value == record]
        if len(matches) != 1 or matches[0][0] <= last:
            return None
        last, offset = matches[0]
        mapping.append((start, offset, end))
    return mapping


def record_metadata(history, source, before, destination, after, revision):
    """Only log update time and independently proved structural grouping."""
    from wiki_core.information_relations import semantic_equal
    old, new = document(before)[0], document(after)[0]
    if not semantic_equal({k: v for k, v in old.items() if k not in {'updated_at', 'moc_parent'}},
                          {k: v for k, v in new.items() if k not in {'updated_at', 'moc_parent'}}):
        return False
    return (semantic_equal(old.get('moc_parent'), new.get('moc_parent')) or
            _hierarchy_reframing(history, old, new, destination, revision, source))


class NavigationHistory:
    """One invocation's local Git readset. No network, writes or global cache."""
    def __init__(self, root: Path, *, git_root: Path | None = None, revision: str | None = None):
        self.root = root
        self.git_root = git_root or root
        self.revision = revision
        self.trees: dict[str, dict[str, tuple[str, str]]] = {}
        self.blobs: dict[str, str] = {}
        self.identities: dict[tuple, dict[str, list[str]]] = {}
        self.page_ids: dict[str, str | None] = {}
        self.origins: dict[str, list[str]] = {}
        self.last_proof: dict | None = None
        self.readset: dict[str, tuple[str, int, str]] = {}
        self.folder_policies: dict[str, object] = {}
        self.record_maps: dict[tuple[str, str], list | None] = {}

    @cached_property
    def prefix(self):
        return str(load_config(self.root).paths['memory_root']).rstrip('/') + '/'

    def git(self, *args: str) -> bytes:
        return local_git_tree(self.git_root, *args)

    @cached_property
    def head(self):
        return self.git('rev-parse', '--verify', (self.revision or 'HEAD') + '^{commit}').decode().strip()

    @cached_property
    def object_format(self):
        return self.git('rev-parse', '--show-object-format').decode().strip()

    @cached_property
    def parents(self):
        # One bounded DAG read per invocation, reused by source and target
        # lineages. Missing/truncated ancestry still fails closed.
        rows = self.git('rev-list', '--parents', '--topo-order', '--max-count=4096', self.head).decode().splitlines()
        return {parts[0]: parts[1:] for row in rows if (parts := row.split())}

    def tree(self, revision: str):
        if revision not in self.trees:
            entries = {}
            for row in self.git('ls-tree', '-r', '-z', revision).split(b'\0'):
                if row:
                    meta, path = row.split(b'\t', 1)
                    mode, kind, oid = meta.decode().split()
                    if kind == 'blob':
                        entries[path.decode('utf-8')] = (mode, oid)
            self.trees[revision] = entries
        return self.trees[revision]

    def text(self, revision: str, path: str) -> str | None:
        entry = self.tree(revision).get(path)
        if not entry or entry[0] not in {'100644', '100755'}:
            return None
        oid = entry[1]
        if oid not in self.blobs:
            self.blobs[oid] = self.git('cat-file', 'blob', oid).decode('utf-8')
        return self.blobs[oid]

    def ids(self, revision: str):
        tree = self.tree(revision)
        pages = tuple((path, entry) for path, entry in tree.items()
                      if path.startswith(self.prefix) and path.endswith('.md'))
        if pages not in self.identities:
            result = {}
            for path, (mode, oid) in pages:
                if mode not in {'100644', '100755'}:
                    continue
                if oid not in self.page_ids:
                    page_id = document(self.text(revision, path))[0].get('page_id')
                    self.page_ids[oid] = page_id if isinstance(page_id, str) and page_id else None
                if self.page_ids[oid]:
                    result.setdefault(self.page_ids[oid], []).append(path)
            self.identities[pages] = result
        return self.identities[pages]

    @cached_property
    def current_ids(self):
        result = {}
        for path in wiki_markdown_files(self.root / self.prefix, wiki_root=self.root):
            values, _ = document(path.read_bytes().decode('utf-8'))
            page_id = values.get('page_id')
            if isinstance(page_id, str) and page_id:
                result.setdefault(page_id, []).append(path.relative_to(self.root).as_posix())
        return result

    @cached_property
    def moves(self):
        """Only exact moves can taint a reoccupied path; no similarity aliases."""
        rows = self.git('log', '--format=', '--name-status', '-z', '--diff-filter=R',
                        '--find-renames=100%', '-m', self.head, '--', self.prefix).split(b'\0')
        result = []
        index = 0
        while index < len(rows):
            status = rows[index].strip()
            index += 1
            if not status:
                continue
            if status != b'R100' or index + 1 >= len(rows):
                raise ValueError('invalid navigation rename history')
            result.append((rows[index].decode('utf-8'), rows[index + 1].decode('utf-8')))
            index += 2
        return result

    @cached_property
    def former_paths(self):
        return {before for before, _ in self.moves}

    @cached_property
    def moved_paths(self):
        return {after for _, after in self.moves}

    def existing_reference_safe(self, source: str, text: str, ref: str, *, href: bool = False,
                                body_offset: int | None = None) -> bool:
        """A new occupant must not silently steal an unchanged historical link."""
        try:
            target = link_path(source, ref) if href else safe_path(ref)
            if not target:
                return True
            # Metadata discovery is not the repository reader's grant. Do not
            # open a current non-page target merely to validate its existence.
            path = self.root / safe_path(target)
            require_wiki_boundaries(self.root, files=(path,))
            if not path.exists() or not target.endswith('.md'):
                return True
            if not (self.git_root / '.git').exists():
                return True
            # A relative href's base is part of its meaning. Even when the
            # interpreted destination exists, an exact source move may have
            # silently changed the target. A newly authored blob at the new
            # location can establish its own reference; the old blob cannot.
            moved_source = href and (source in self.moved_paths or (
                source not in self.tree(self.head) and
                bool(self.ids(self.head).get(document(text)[0].get('page_id')))))
            if target not in self.former_paths and not moved_source:
                return True
            return self.resolve(source, text, ref, href=href, _occupied=True, body_offset=body_offset) == target
        except (ValueError, OSError, UnicodeError, yaml.YAMLError):
            return False

    def continuous(self, revision: str, old: str, page_id: str, canonical: str) -> bool:
        """Follow a surviving identity backwards, with exact bytes at each move.

        Same-path factual revisions are ordinary Git history. Changing paths
        needs the same blob and mode; disappearance cannot be resurrection.
        Merge parents are followed explicitly, including after promotion.
        """
        current = require_wiki_path(self.root, canonical)
        if not current.is_file() or self.current_ids.get(page_id) != [canonical]:
            return False
        raw = current.read_bytes()
        if document(raw.decode('utf-8'))[0].get('page_id') != page_id:
            return False
        self.readset[canonical] = (hashlib.sha256(raw).hexdigest(), current.stat().st_mode & 0o111, page_id)
        locations = self.ids(self.head).get(page_id, [])
        if len(locations) != 1:
            return False
        location = locations[0]
        if location != canonical:
            if (require_wiki_path(self.root, location).exists()
                    or self.text(self.head, location) != raw.decode('utf-8')
                    or self.tree(self.head)[location][0] != ('100755' if current.stat().st_mode & 0o111 else '100644')):
                return False
        pending = [(self.head, location)]
        visited = set()
        while pending:
            commit, path = pending.pop()
            if (commit, path) in visited:
                continue
            visited.add((commit, path))
            if len(visited) > 4096:
                raise ValueError('navigation ancestry limit exceeded')
            if commit == revision:
                if path == old:
                    return True
                continue
            if commit not in self.parents:
                raise ValueError('navigation ancestry limit exceeded')
            for parent in self.parents[commit]:
                candidates = self.ids(parent).get(page_id, [])
                if len(candidates) != 1:
                    continue
                before = candidates[0]
                if before == path or (self.tree(parent)[before] == self.tree(commit)[path]
                                      and path not in self.tree(parent) and before not in self.tree(commit)):
                    pending.append((parent, before))
        return False

    def confirm(self) -> bool:
        """Recheck selected identities and Git HEAD immediately before a write."""
        try:
            if self.git('rev-parse', '--verify', 'HEAD^{commit}').decode().strip() != self.head:
                return False
            current = NavigationHistory(self.root).current_ids
            for ref, (digest, executable, page_id) in self.readset.items():
                path = require_wiki_path(self.root, ref)
                if (current.get(page_id) != [ref] or path.stat().st_mode & 0o111 != executable
                        or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                    return False
            return bool(self.readset)
        except (ValueError, OSError, UnicodeError, yaml.YAMLError):
            return False

    def _record_origins(self, source: str, text: str, values: dict, body: str, ref: str, body_offset: int):
        """Map a unique preserved dated record, including newest-first logs.

        All old records and their order survive exactly. New records cannot
        lend their occurrences an older origin, even with the same literal URL.
        """
        for revision in self.parents:
            locations = self.ids(revision).get(values['page_id'], [])
            if len(locations) != 1:
                continue
            origin = locations[0]
            old_text = self.text(revision, origin)
            _, old_body = document(old_text)
            mapping = self.record_map(old_body, body)
            if old_text == text or mapping is None:
                continue
            matched = [(a, b, end) for a, b, end in mapping if b <= body_offset < b + end - a]
            if len(matched) != 1:
                continue
            start, current_start, end = matched[0]
            old_offset = start + body_offset - current_start
            if not any(m.start() == old_offset and m[1] == ref for m in inline_links(old_body)):
                continue
            relevant = {revision}
            for commit in reversed(self.parents):
                if any(parent in relevant for parent in self.parents[commit]):
                    relevant.add(commit)
            preserved = self.head in relevant
            for commit in relevant:
                paths = self.ids(commit).get(values['page_id'], [])
                if len(paths) != 1:
                    preserved = False
                    break
                at_commit = self.text(commit, paths[0])
                if (self.record_map(old_body, document(at_commit)[1]) is None
                        or not record_metadata(self, origin, old_text, paths[0], at_commit, commit)):
                    preserved = False
                    break
            if not preserved or not record_metadata(self, origin, old_text, source,
                                                     text, self.head):
                yield revision, origin, old_text, {'invalid_record_lineage': True}
                continue
            yield revision, origin, old_text, dict(body_offset=old_offset,
                current_body_offset=body_offset, record_start=start, record_end=end,
                current_record_start=current_start)

    def record_map(self, before: str, after: str):
        key = before, after
        if key not in self.record_maps:
            self.record_maps[key] = preserved_records(before, after)
        return self.record_maps[key]

    def resolve(self, source: str, text: str, ref: str, *, href: bool = False, _occupied: bool = False,
                body_offset: int | None = None) -> str | None:
        """Prove a committed document or an exact preserved dated occurrence."""
        try:
            self.last_proof = None
            safe_path(source)
            require_wiki_path(self.root, source)
            target = link_path(source, ref) if href else safe_path(ref)
            if (not source.startswith(self.prefix) or not target or not target.endswith('.md')
                    or (require_wiki_path(self.root, target).exists() and not _occupied)):
                return None  # a current path is never an alias
            values, body = document(text)
            if not isinstance(values.get('page_id'), str) or not values['page_id']:
                return None
            if href:
                occurrences = [m for m in inline_links(body) if m[1] == ref
                               and (body_offset is None or m.start() == body_offset)]
                if not occurrences:
                    return None
            elif not (any(ref == item for field in _PATH_FIELDS
                         for item in (values.get(field, []) if isinstance(values.get(field), list)
                                      else [values.get(field)])) or any(
                    isinstance(req, dict) and req.get('temporal') == 'historical'
                    and not req.get('query') and req.get('target') == ref
                    for req in values.get('information_requirements', []))):
                return None
            # Compute the repository's native object ID without writing objects.
            raw = text.encode('utf-8')
            oid = hashlib.new(self.object_format, b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            if oid not in self.origins:
                self.origins[oid] = [self.head, *self.git('log', '--format=%H', '--find-object=' + oid, self.head).decode().split()]
            revisions = self.origins[oid]
            if len(revisions) > 4096:
                return None
            resolutions = {}
            invalid_lineage = False
            origins_with_proof = []
            for revision in dict.fromkeys(revisions):
                # A moved record may retain its bytes and original relative hrefs.
                origins = [p for p, entry in self.tree(revision).items()
                           if entry[0] in {'100644', '100755'} and entry[1] == oid]
                if len(origins) != 1:
                    continue
                origin = origins[0]
                source_id = values.get('page_id')
                if not self.continuous(revision, origin, source_id, source):
                    invalid_lineage = True
                    continue
                origins_with_proof.append((revision, origin, text, {}))
            # A changed whole-document blob is never claimed as an old preimage.
            # Only an individually located, preserved record may use this path.
            if href and len(occurrences) == 1 and re.search(r'(?m)^## \[\d{4}-\d{2}-\d{2}', body):
                origins_with_proof.extend(self._record_origins(source, text, values, body, ref, occurrences[0].start()))
            for revision, origin, origin_text, occurrence_proof in origins_with_proof:
                if (occurrence_proof.get('invalid_record_lineage')
                        or not self.continuous(revision, origin, values['page_id'], source)):
                    invalid_lineage = True
                    continue
                old = link_path(origin, ref) if href else safe_path(ref)
                old_text = self.text(revision, old) if old else None
                if old_text is None:
                    continue
                page_id = document(old_text)[0].get('page_id')
                if not page_id or self.ids(revision).get(page_id) != [old]:
                    continue
                candidates = self.current_ids.get(page_id, [])
                if len(candidates) == 1 and self.continuous(revision, old, page_id, candidates[0]):
                    resolutions[candidates[0]] = dict(source_revision=revision, source_path=origin,
                        historical_target=old, target=candidates[0], page_id=page_id,
                        **({'occurrence': occurrence_proof} if occurrence_proof else {}))
                else:
                    invalid_lineage = True
            # find-object reports global blob-count events, including unrelated
            # copies. They cannot renew a source's earlier, broken target lineage.
            if len(resolutions) == 1 and not invalid_lineage:
                self.last_proof = next(iter(resolutions.values()))
                return next(iter(resolutions))
            return None
        except (ValueError, OSError, UnicodeError, yaml.YAMLError, TypeError, AttributeError):
            return None


# Only existing path-reference fields, never identity, authority or history.
_PATH_FIELDS = frozenset({'source_refs', 'source_ref', 'evidence_refs', 'related_pages',
    'consolidated_into', 'backlinks_expected', 'moc_parent', 'collection_refs'})


def _hierarchy_reframing(history: NavigationHistory, old: dict, new: dict, destination: str,
                   revision: str, source: str) -> bool:
    """A committed physical index is a distinct hierarchy node, never an alias.

    This predicate qualifies C3 stages and preserved log metadata. It conveys no
    owner/route authority and cannot admit a general frontmatter edit.
    """
    def hub(ref):
        ref = safe_path(ref)
        paths = [ref] if ref in history.tree(revision) else history.ids(revision).get(ref, [])
        if len(paths) != 1 or not paths[0].startswith(history.prefix):
            raise ValueError('invalid hierarchy hub')
        path = paths[0]
        require_wiki_path(history.root, path)
        values, _ = document(history.text(revision, path))
        page_id = values.get('page_id')
        if (not page_id
                or history.ids(revision).get(page_id) != [path]):
            raise ValueError('invalid hierarchy hub')
        return path, values
    if old.get('page_type') != new.get('page_type'):
        return False
    parent_path, parent = hub(old.get('moc_parent'))
    child_path, child = hub(new.get('moc_parent'))
    if parent['page_id'] == child['page_id'] or parent_path == child_path:
        return False
    authority = ('owner_kind', 'owner_ref', 'visibility', 'gate', 'sensitive_data_policy')
    if any(parent.get(k) != child.get(k) for k in authority):
        return False
    # Preserve the existing narrow explicit-hub contract. Other physical
    # indexes require the actual folder entry/inheritance contract below.
    if (old.get('page_type') == 'action' and parent.get('page_type') == child.get('page_type') == 'context_hub'
            and child.get('moc_parent') and hub(child['moc_parent'])[0] == parent_path
            and old.get('context') == new.get('context') == parent.get('context') == child.get('context')
            and parent.get('sources_policy') == child.get('sources_policy')
            and destination.startswith(posixpath.dirname(child_path) + '/')):
        return True
    from wiki_core.context_packet import inspect_folder_context
    from wiki_core.context_policy import _folder_policy_at, within
    if revision not in history.folder_policies:
        history.folder_policies[revision] = _folder_policy_at(history.git_root, revision)
    policy = history.folder_policies[revision]
    context = policy.owner_of(destination)
    # Editorial labels and curation are not ACLs. Nor is a common human owner
    # a cross-context write grant. This structural route stays within one
    # effective physical write boundary; normal host preflight still applies.
    if policy.owner_of(source) != context:
        return False
    def inspect(ref):
        require_wiki_path(history.root, ref)
        text = history.text(revision, ref)
        if text is None:
            raise ValueError('physical hierarchy document unavailable')
        return text
    for path in (source, destination, parent_path, child_path):
        if (policy.owner_of(path) != context or not policy._permits_unqualified(context, 'read', path)
                or (path in (source, destination) and not policy._permits_unqualified(context, 'write', path))):
            return False
        inspect_folder_context(policy, context, posixpath.dirname(path),
                               policy._context_indexes.get(context), inspect)
    def hierarchy(path, values):
        visited = set()
        while True:
            if path in visited or len(visited) > 64:
                return False
            visited.add(path)
            if (values.get('page_type') not in {'context_hub', 'root_index'}
                    and posixpath.basename(path) not in {'index.md', 'README.md'}):
                return False
            if not values.get('moc_parent'):
                return True
            ancestor, metadata = hub(values['moc_parent'])
            # An index cannot skip an existing nearer physical index and
            # declare an unrelated editorial group as its physical parent.
            indexes = [p for p in history.tree(revision) if p.startswith(history.prefix)
                       and posixpath.basename(p) in {'index.md', 'README.md'}
                       and posixpath.dirname(p) != posixpath.dirname(path)
                       and within(posixpath.dirname(path), posixpath.dirname(p))]
            nearest = sorted(indexes, key=lambda p: (-len(posixpath.dirname(p)),
                             posixpath.basename(p) != 'index.md'))
            if (posixpath.dirname(ancestor) == posixpath.dirname(path)
                    or not within(posixpath.dirname(path), posixpath.dirname(ancestor))
                    or policy.owner_of(ancestor) != context
                    or (nearest and ancestor != nearest[0])):
                return False
            inspect(ancestor)
            path, values = ancestor, metadata
    return (destination.startswith(posixpath.dirname(child_path) + '/')
            and hierarchy(parent_path, parent) and hierarchy(child_path, child))


def structural_navigation(history: NavigationHistory, source: str, before: str, after: str,
                          *, destination: str | None = None, hierarchy_revision: str | None = None) -> bool:
    """Every delta must retarget a proven reference to its canonical identity.

    No prose, labels, fragments, role digests, dates, ownership or historical
    fields can change. This predicate is not a grant to access a destination.
    """
    from wiki_core.information_relations import semantic_equal
    try:
        old, old_body = document(before)
        new, new_body = document(after)
        if not old.get('page_id') or set(old) != set(new):
            return False
        old_match, new_match = FRONTMATTER_RE.match(before), FRONTMATTER_RE.match(after)
        if not old_match or not new_match:
            return False
        nodes = dict((k.value, v) for k, v in yaml.compose(old_match[1], Loader=UniqueLoader).value)
        replacements = []
        for field in old:
            if semantic_equal(old[field], new[field]):
                continue
            if field not in _PATH_FIELDS:
                return False
            a, b = old[field], new[field]
            scalar_nodes = nodes[field].value if isinstance(nodes[field], yaml.SequenceNode) else [nodes[field]]
            if isinstance(a, str) and isinstance(b, str):
                a, b = [a], [b]
            if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
                return False
            for x, y, node in zip(a, b, scalar_nodes):
                if x != y:
                    if not isinstance(x, str) or not isinstance(y, str):
                        return False
                    reframe = (field == 'moc_parent' and hierarchy_revision is not None
                               and isinstance(old[field], str)
                               and _hierarchy_reframing(history, old, new, destination or source, hierarchy_revision, source))
                    if not reframe and history.resolve(source, before, x) != y:
                        return False
                if x != y:
                    start, end = node.start_mark.index, node.end_mark.index
                    raw = old_match[1][start:end]
                    quote = raw[0] if raw[:1] in {"'", '"'} else ''
                    if raw != quote + x + quote or (quote and quote in y):
                        return False
                    replacements.append((old_match.start(1) + start, old_match.start(1) + end, quote + y + quote))
        expected_prefix = before[:old_match.end()]
        for start, end, value in sorted(replacements, reverse=True):
            expected_prefix = expected_prefix[:start] + value + expected_prefix[end:]
        if expected_prefix != after[:new_match.end()]:
            return False
        old_links, new_links = inline_links(old_body), inline_links(new_body)
        if len(old_links) != len(new_links):
            return False
        cursor_a = cursor_b = 0
        for a, b in zip(old_links, new_links):
            if old_body[cursor_a:a.start(1)] != new_body[cursor_b:b.start(1)]:
                return False
            x, y = a[1], b[1]
            if (x == y and link_path(source, x) != link_path(destination or source, y)
                    and not history.existing_reference_safe(destination or source, before, y,
                        href=True, body_offset=a.start())):
                return False
            if x != y:
                # Historical typed declarations must remain byte-for-byte,
                # rather than becoming stale markers after a path rewrite.
                if a.span() in parse_role_markdown(old_body)[1]:
                    return False
                if (urlsplit(x).fragment != urlsplit(y).fragment or urlsplit(x).query != urlsplit(y).query
                        or history.resolve(source, before, x, href=True) != link_path(destination or source, y)):
                    return False
            cursor_a, cursor_b = a.end(1), b.end(1)
        return old_body[cursor_a:] == new_body[cursor_b:]
    except (ValueError, OSError, UnicodeError, yaml.YAMLError, AttributeError, TypeError):
        return False
