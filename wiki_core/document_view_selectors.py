"""Exact lexical partitions for explicitly reviewed documentary views.

Selectors prove location and bytes, never independence, truth or freshness.
Unselected material remains common context; no producer/path defaults exist.
"""
from __future__ import annotations

import datetime as dt
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from wiki_core.frontmatter import FRONTMATTER_RE


def _literal_container_prefix(value):
    """Recognize only whitespace, quotes and whitespace-terminated list markers."""
    marker = re.compile(r"(?:[-+*]|[0-9]{1,9}[.)])[ \t]+")
    cursor = 0
    while cursor < len(value):
        if value[cursor] in " \t>":
            cursor += 1
            continue
        match = marker.match(value, cursor)
        if match is None:
            return False
        cursor = match.end()
    return True


def _literal_inline_links(text):
    """Parser-proven, uniquely mapped inline links; no reference/image guesses."""
    from wiki_core.markdown_link_roles import parse_role_markdown
    fm, body = _body(text)
    tokens, _ = parse_role_markdown(body)
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    result = []
    for token in tokens:
        if token.type != "inline" or not token.map or not token.content:
            continue
        block_start, block_end = (offsets[n] for n in token.map)
        block = body[block_start:block_end]
        relative = block.find(token.content)
        if relative >= 0 and block.find(token.content, relative + 1) >= 0:
            continue
        mapped_lines = []
        if relative < 0:
            # CommonMark strips list/quote prefixes from each inline line.
            # Align complete lines first, never search a link in unrelated code.
            parsed_lines = token.content.split("\n")
            source_lines = block.splitlines(keepends=True)
            if len(parsed_lines) != len(source_lines):
                continue
            cursor = block_start
            for parsed, source in zip(parsed_lines, source_lines):
                raw = source.rstrip("\r\n")
                position = raw.find(parsed) if parsed else -1
                if (position < 0 or raw.find(parsed, position + 1) >= 0
                        or not _literal_container_prefix(raw[:position])
                        or raw[position + len(parsed):].strip(" \t")):
                    break
                mapped_lines.append(cursor + position)
                cursor += len(source)
            if len(mapped_lines) != len(parsed_lines):
                continue
        for child in token.children or []:
            span = child.meta.get("_wiki_link_span")
            if child.type != "link_open" or not span or "label" in child.meta:
                continue
            if relative >= 0:
                start, end = (block_start + relative + n for n in span)
            else:
                literal = token.content[span[0]:span[1]]
                # Normalization inside the link itself stays unsupported.
                if "\n" in literal or "\r" in literal or block.count(literal) != 1:
                    continue
                line = token.content.count("\n", 0, span[0])
                column = span[0] - token.content.rfind("\n", 0, span[0]) - 1
                start = mapped_lines[line] + column
                end = start + len(literal)
                if body[start:end] != literal:
                    continue
            literal = body[start:end]
            href = child.attrGet("href") or ""
            # Minimal scope: literal inline destinations, without titles or
            # parser normalization. Other syntax remains conservative.
            suffix = "](" + href + ")"
            if not literal.endswith(suffix) or not literal.startswith("["):
                continue
            absolute = fm.end() if fm else 0
            result.append(dict(start=start + absolute, end=end + absolute,
                               markdown=literal, href=href, prefix=literal[:-len(suffix)]))
    return result


def verify_locator_changes(current, base, contract, artifact_inputs):
    """Verify lexical custody edits, never semantic independence or freshness.

    The pinned CURRENT receipt is reviewed evidence of original identity and
    custody. Its hash proves receipt bytes, not remote state or authorization.
    BASE is never assigned that later custody event. Consumer intent requires
    separate origin/occurrence-bound qualifications in the existing contract.
    """
    declarations = contract.get("locator_changes", [])
    if not isinstance(declarations, list):
        raise ValueError("locator_changes must be an explicit list")
    result, ids = {}, set()

    def unique_keys(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate custody receipt key")
            values[key] = value
        return values

    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise ValueError("locator change must be a mapping")
        if set(declaration) != {"id", "path", "rationale", "replacements"}:
            raise ValueError("unknown or missing locator change field")
        identity, path = declaration["id"], declaration["path"]
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", identity)
                or identity in ids or not isinstance(path, str) or path in result
                or path not in base["documents"] or path not in current["documents"]
                or not isinstance(declaration["rationale"], str) or not declaration["rationale"].strip()):
            raise ValueError("invalid or duplicate locator change")
        replacements = declaration["replacements"]
        if not isinstance(replacements, list) or not replacements:
            raise ValueError("locator change requires explicit replacements")
        old, new = base["documents"][path], current["documents"][path]
        links = {o: _literal_inline_links(t) for o, t in (("base", old), ("current", new))}
        edits, occupied, proofs = [], {"base": set(), "current": set()}, []
        for replacement in replacements:
            required = {"base_markdown", "current_markdown", "locator_use", "artifact_sha256",
                        "size_bytes", "custody_evidence"}
            if (not isinstance(replacement, dict)
                    or set(replacement) not in (required, required | {"custody_entry"})
                    or replacement.get("locator_use") != "historical_artifact_address"):
                raise ValueError("locator replacement requires reviewed historical-address intent")
            selected = {}
            for origin in ("base", "current"):
                matches = [v for v in links[origin] if v["markdown"] == replacement[f"{origin}_markdown"]]
                if len(matches) != 1:
                    raise ValueError("locator occurrence missing, ambiguous or unsupported")
                selected[origin] = matches[0]
                span = (matches[0]["start"], matches[0]["end"])
                if span in occupied[origin]:
                    raise ValueError("duplicate locator occurrence")
                occupied[origin].add(span)
            a, b = selected["base"], selected["current"]
            if a["prefix"] != b["prefix"] or a["href"] == b["href"]:
                raise ValueError("locator edit changes label or does not change destination")
            before, after = urlsplit(a["href"]), urlsplit(b["href"])
            source_path = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(before.path)))
            if (before.scheme or before.netloc or before.query or before.fragment
                    or source_path.startswith(("/", "../")) or "\\" in source_path
                    or after.scheme != "https" or not after.netloc or after.username or after.password):
                raise ValueError("unsupported custody locator boundary")
            aid = replacement["custody_evidence"]
            if not isinstance(aid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", aid):
                raise ValueError("invalid custody evidence identity")
            key = ("current", aid)
            artifacts = [v for v in contract.get("artifacts", [])
                         if v.get("origin") == "current" and v.get("id") == aid and "path" in v]
            if len(artifacts) != 1 or key not in artifact_inputs:
                raise ValueError("custody evidence must be a verified CURRENT file receipt")
            try:
                receipt = json.loads(artifact_inputs[key], object_pairs_hook=unique_keys)
                if "custody_entry" in replacement:
                    receipt = receipt["files"][replacement["custody_entry"]]
                if not isinstance(receipt, dict):
                    raise ValueError("custody receipt must be a mapping")
                verified = dt.datetime.fromisoformat(receipt["verified_at"])
            except (TypeError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid custody receipt") from exc
            sha, size = replacement["artifact_sha256"], replacement["size_bytes"]
            if (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
                    or type(size) is not int or size <= 0 or verified.tzinfo is None
                    or receipt.get("sha256") != sha or type(receipt.get("size_bytes")) is not int
                    or receipt.get("size_bytes") != size
                    or receipt.get("source_path") != source_path or receipt.get("view_url") != b["href"]):
                raise ValueError("custody receipt does not match original identity and destination")
            edits.append((a["start"], a["end"], b["markdown"]))
            proofs.append(dict(base_span=[a["start"], a["end"]], current_span=[b["start"], b["end"]],
                custody_evidence=aid, custody_origin="current", source_path=source_path,
                artifact_sha256=sha, size_bytes=size, base_href=a["href"], current_href=b["href"]))
        rewritten = old
        for start, end, value in sorted(edits, reverse=True):
            rewritten = rewritten[:start] + value + rewritten[end:]
        if rewritten != new:
            raise ValueError("locator delta contains another lexical or factual change")
        result[path] = dict(id=identity, path=path, rationale=declaration["rationale"],
                            base_sha256=contract["base_documents_sha256"][path],
                            current_sha256=contract["current_documents_sha256"][path],
                            replacements=proofs)
        ids.add(identity)
    return result


def _body(text):
    fm = FRONTMATTER_RE.match(text)
    return fm, text[fm.end():] if fm else text


def _blocks(body):
    tokens = MarkdownIt("commonmark", {"store_labels": True}).enable("table").parse(body)
    path, paths, result = [], {}, []
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.level == 0:
            depth = int(token.tag[1:])
            path = [(d, title) for d, title in path if d < depth]
            path.append((depth, tokens[i + 1].content))
            key = tuple(title for _, title in path)
            paths[key] = paths.get(key, 0) + 1
        result.append((i, token, tuple(title for _, title in path)))
    return tokens, result, paths


def body_span(text, selector, *, common_ranges=None):
    """Return a complete body block span; ambiguity is an error."""
    from wiki_core.document_records import digest, section_spans
    _, body = _body(text)
    lines = body.splitlines(keepends=True)
    kind = selector.get("kind")
    if kind == "h2":
        candidates = [(a, b) for title, a, b, _ in section_spans(text)[1]
                      if title == selector.get("heading")]
        if len(candidates) > 1:
            raise ValueError("ambiguous H2 selector")
        if not candidates:
            return None
        start, end = candidates[0]
        padding = selector.get("leading_blank_lines", 0)
        if type(padding) is not int or not 0 <= padding <= 2 or start < padding:
            raise ValueError("invalid H2 padding")
        if any(line.strip() for line in lines[start - padding:start]):
            raise ValueError("H2 padding is not blank")
        return start - padding, end
    tokens, blocks, paths = _blocks(body)
    heading_path = selector.get("container_heading_path")
    if not isinstance(heading_path, list) or any(not isinstance(v, str) for v in heading_path):
        raise ValueError("explicit heading path required")
    heading_path = tuple(heading_path)
    if heading_path and paths.get(heading_path, 0) != 1:
        raise ValueError("missing or ambiguous container heading path")
    if selector.get("required_match_count") != 1:
        raise ValueError("selector requires exactly one match")
    if kind == "markdown_list_item":
        prefix = selector.get("literal_prefix")
        if (not isinstance(prefix, str) or not prefix.strip()
                or "\n" in prefix or "\r" in prefix):
            raise ValueError("list item requires a nonempty literal first-line prefix")
        matches = []
        for i, token, path in blocks:
            # Select only independent top-level siblings. A nested item cannot
            # shed a qualification carried by its enclosing item or quote.
            if (token.type != "list_item_open" or token.level != 1
                    or path != heading_path or not token.map
                    or not lines[token.map[0]].startswith(prefix)):
                continue
            end_index = next((j for j in range(i + 1, len(tokens))
                              if tokens[j].type == "list_item_close"
                              and tokens[j].level == token.level), None)
            if end_index is None:
                raise ValueError("uncertain complete list item boundary")
            # Whole AST span includes continuation paragraphs and all subitems.
            # References depend on definitions outside this lexeme; block code,
            # HTML and images remain conservative. Inline code stays literal
            # inside the whole item; it cannot introduce an AST link or item.
            for child in tokens[i + 1:end_index]:
                if child.type in {"fence", "code_block", "html_block"} or any(
                        c.type in {"html_inline", "image"} or "label" in c.meta
                        for c in child.children or []):
                    raise ValueError("unsupported code, HTML, image or reference in list item")
            matches.append(tuple(token.map))
        if len(matches) > 1:
            raise ValueError("duplicate list item prefix")
        return matches[0] if matches else None
    if kind == "table_row":
        tables = [(i, t) for i, t, path in blocks
                  if t.type == "table_open" and t.level == 0 and path == heading_path
                  and digest("".join(lines[t.map[0]:t.map[0] + 2])) == selector.get("header_sha256")]
        if len(tables) != 1:
            raise ValueError("missing or ambiguous table/header selector")
        index, table = tables[0]
        if common_ranges is not None:
            common_ranges.append((table.map[0], table.map[0] + 2))
        column, key = selector.get("key_column"), selector.get("key", {})
        if type(column) is not int or column < 0 or key.get("kind") not in {"text", "link_destination"}:
            raise ValueError("invalid table key")
        if not isinstance(key.get("value"), str) or not key["value"]:
            raise ValueError("table key requires a canonical nonempty string")
        matches = []
        for i in range(index + 1, len(tokens)):
            token = tokens[i]
            if token.type == "table_close" and token.level == 0:
                break
            if token.type != "tr_open" or token.map[0] < table.map[0] + 2:
                continue
            cells = []
            for cell in tokens[i + 1:]:
                if cell.type == "tr_close":
                    break
                if cell.type == "inline":
                    cells.append(cell)
            if column >= len(cells) or token.map[1] != token.map[0] + 1:
                raise ValueError("uncertain table row boundary/key column")
            children = cells[column].children or []
            if key["kind"] == "link_destination":
                links = [c.attrGet("href") for c in children if c.type == "link_open"]
                matched = links == [key["value"]]
                # Multiple links that include this identity are ambiguous.
                if key["value"] in links and len(links) != 1:
                    raise ValueError("ambiguous table key links")
            else:
                if any(c.type != "text" for c in children):
                    raise ValueError("text key requires plain text cells")
                matched = "".join(c.content for c in children) == key["value"]
            if matched:
                matches.append(tuple(token.map))
        if len(matches) > 1:
            raise ValueError("duplicate table row key")
        return matches[0] if matches else None
    if kind == "markdown_generation_paragraph":
        template = selector.get("template", {})
        prefix, suffix = template.get("prefix"), template.get("suffix")
        fmt = template.get("value_format")
        if not isinstance(prefix, str) or not prefix or not isinstance(suffix, str):
            raise ValueError("generation paragraph requires literal template")
        pattern = {"iso_date": r"\d{4}-\d{2}-\d{2}",
                   "iso_datetime_minutes": r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"}.get(fmt)
        if pattern is None:
            raise ValueError("unsupported generation timestamp format")
        candidates = []
        for i, token, path in blocks:
            if token.type != "paragraph_open" or token.level != 0 or path != heading_path:
                continue
            inline = tokens[i + 1]
            if not inline.content.startswith(prefix):
                continue
            match = re.fullmatch(re.escape(prefix) + "(" + pattern + ")" + re.escape(suffix), inline.content)
            if not match or any(c.type != "text" for c in inline.children or []):
                raise ValueError("generation paragraph is not the declared literal timestamp")
            value = match.group(1)
            if fmt == "iso_date":
                dt.date.fromisoformat(value)
            else:
                dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
            if token.map[1] != token.map[0] + 1:
                raise ValueError("generation paragraph must be a single lexical line")
            candidates.append(tuple(token.map))
        if len(candidates) != 1:
            raise ValueError("missing or ambiguous generation paragraph")
        return candidates[0]
    raise ValueError("unsupported explicit view body selector")


def frontmatter_span(text, selector, shape):
    """Unique whole YAML field lexeme; reject aliases/merges/duplicate keys."""
    fm, _ = _body(text)
    if not fm:
        raise ValueError("frontmatter selector requires frontmatter")
    raw = fm.group(1)
    if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.TagToken))
           for t in yaml.scan(raw)):
        raise ValueError("frontmatter aliases/anchors/tags are not selectable")
    root = yaml.compose(raw)

    def validate(node):
        if isinstance(node, MappingNode):
            keys = []
            for key, value in node.value:
                if not isinstance(key, ScalarNode) or key.value == "<<" or key.value in keys:
                    raise ValueError("duplicate/complex/merge frontmatter key")
                keys.append(key.value)
                validate(value)
        elif isinstance(node, SequenceNode):
            for value in node.value:
                validate(value)
    validate(root)
    path = selector.get("path")
    if not isinstance(path, list) or not path or any(not isinstance(v, str) for v in path):
        raise ValueError("frontmatter selector requires an explicit key path")
    node = root
    for depth, name in enumerate(path):
        if not isinstance(node, MappingNode) or node.flow_style:
            raise ValueError("frontmatter field requires a block mapping")
        found = [(i, k, v) for i, (k, v) in enumerate(node.value) if k.value == name]
        if len(found) != 1:
            raise ValueError("frontmatter field missing or ambiguous")
        i, key, value = found[0]
        if depth == len(path) - 1:
            start = key.start_mark.line
            end = node.value[i + 1][0].start_mark.line if i + 1 < len(node.value) else node.end_mark.line
            if i + 1 == len(node.value) and node.end_mark.column:
                end += 1
            break
        node = value
    if shape == "canonical_iso_date":
        if not isinstance(value, ScalarNode) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.value):
            raise ValueError("publication date requires canonical ISO date")
        dt.date.fromisoformat(value.value)
    elif shape == "unique_string_sequence":
        if (not isinstance(value, SequenceNode) or any(not isinstance(v, ScalarNode)
                or v.tag != "tag:yaml.org,2002:str" for v in value.value)
                or len({v.value for v in value.value}) != len(value.value)):
            raise ValueError("membership requires unique strings")
    else:
        raise ValueError("unsupported envelope value shape")
    lines = raw.splitlines(keepends=True)
    if any("#" in line for line in lines[start:end]):
        raise ValueError("envelope field cannot absorb comments or additional prose")
    if start >= end or any(line[:key.start_mark.column].strip() for line in lines[start:end]):
        raise ValueError("uncertain frontmatter lexical span")
    offset = len(text[:fm.start(1)].splitlines(keepends=True))
    return start + offset, end + offset


def partition_view(text, entries, origin):
    """Build the canonical partition once, shared by projection and review."""
    from wiki_core.document_records import digest, section_spans
    fm, body = _body(text)
    lines = body.splitlines(keepends=True)
    full_lines = text.splitlines(keepends=True)
    body_offset = len(full_lines) - len(lines)
    ranges, full_ranges, parts, fm_fields = [], [], {}, {}
    shared_body_context = []
    for record in entries:
        rid = record["id"]
        selectors = record.get("selectors", {})
        if set(selectors) != {"base", "current"}:
            raise ValueError("explicit selectors required in both origins")
        selector = selectors[origin]
        expected = record.get(f"{origin}_sha256")
        absent = selector is None
        if absent != (expected is None):
            raise ValueError("null selector and null hash must agree")
        probe = selectors["current" if origin == "base" else "base"] if absent else selector
        if not isinstance(probe, dict):
            raise ValueError("record absent in both origins")
        if probe.get("kind") == "frontmatter_field":
            if absent:
                raise ValueError("envelope field cannot be absent")
            start, end = frontmatter_span(text, probe, record.get("value_shape"))
            body_range = None
            if len(probe["path"]) == 1:
                fm_fields[probe["path"][0]] = rid
        else:
            common = []
            span = body_span(text, probe, common_ranges=common)
            if absent:
                if span is not None:
                    raise ValueError("declared absent record exists")
                continue
            if span is None:
                raise ValueError("record selector missing")
            body_range = span
            shared_body_context.extend((a, b, rid) for a, b in common)
            start, end = (v + body_offset for v in span)
        if any(start < b and a < end for a, b, _ in full_ranges):
            raise ValueError("overlapping explicit view selectors")
        if digest("".join(full_lines[start:end])) != expected:
            raise ValueError("explicit view selector/hash mismatch")
        full_ranges.append((start, end, rid))
        if body_range:
            ranges.append((*body_range, rid))
        parts[rid] = dict(content_sha256=expected, start=start, end=end)
    selected = {i for a, b, _ in full_ranges for i in range(a, b)}
    remainder = "".join(line for i, line in enumerate(full_lines) if i not in selected)
    for start, _, rid in full_ranges:
        parts[rid]["remainder_anchor"] = sum(len(line) for i, line in enumerate(full_lines[:start])
                                            if i not in selected)
    parts["remainder"] = dict(content_sha256=digest(remainder))
    return dict(parts=parts, ranges=ranges, order_ranges=full_ranges, remainder=remainder,
                section_ranges=[(a, b) for _, a, b, _ in section_spans(text)[1]], fm_fields=fm_fields,
                shared_body_context=shared_body_context)
