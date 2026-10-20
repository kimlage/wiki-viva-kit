"""Exact lexical partitions for explicitly reviewed documentary views.

Selectors prove location and bytes, never independence, truth or freshness.
Unselected material remains common context; no producer/path defaults exist.
"""
from __future__ import annotations

import datetime as dt
import re

import yaml
from markdown_it import MarkdownIt
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from wiki_core.frontmatter import FRONTMATTER_RE


def _body(text):
    fm = FRONTMATTER_RE.match(text)
    return fm, text[fm.end():] if fm else text


def _blocks(body):
    tokens = MarkdownIt("commonmark").enable("table").parse(body)
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


def body_span(text, selector):
    """Return a body line span or proven absent H2/row; ambiguity is an error."""
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
    if kind == "table_row":
        tables = [(i, t) for i, t, path in blocks
                  if t.type == "table_open" and t.level == 0 and path == heading_path
                  and digest("".join(lines[t.map[0]:t.map[0] + 2])) == selector.get("header_sha256")]
        if len(tables) != 1:
            raise ValueError("missing or ambiguous table/header selector")
        index, table = tables[0]
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
            span = body_span(text, probe)
            if absent:
                if span is not None:
                    raise ValueError("declared absent record exists")
                continue
            if span is None:
                raise ValueError("record selector missing")
            body_range = span
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
                section_ranges=[(a, b) for _, a, b, _ in section_spans(text)[1]], fm_fields=fm_fields)
