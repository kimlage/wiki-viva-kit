"""Authored, occurrence-local roles carried by Markdown producers.

The digest binds the declaration to literal link syntax, not to an authenticated
producer or a true assertion. Normal content review still owns its semantics.
Unknown, stale or ambiguously located declarations remain ordinary citations.
"""
from __future__ import annotations

import hashlib
import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import html_inline, link

ROLES = frozenset({"navigation", "change_target", "factual_support", "operational_prerequisite",
                   "projection_state", "review_record", "historical_support", "projection"})
_MARKER = re.compile(
    r"<!-- wiki-link-role\.v1 (" + "|".join(sorted(ROLES)) + r") sha256:([0-9a-f]{64}) -->"
)
_PROJECTION_MARKER = re.compile(
    r"<!-- wiki-link-role\.v2 projection consumes:([a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*) produces:([a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*) sha256:([0-9a-f]{64}) -->"
)
_SPAN = "_wiki_link_span"
_ABSOLUTE_SPAN = "_wiki_body_link_span"
_DECLARATION_PREFIX = re.compile(r"<!--\s*wiki-link-role\b")


def _has_following_declaration(children, index):
    """Conflicting/duplicate declarations in the same comment cluster abstain."""
    for following in children[index + 1:]:
        if following.type == "softbreak":
            continue
        if following.type == "text" and not following.content.strip():
            continue
        if following.type != "html_inline" or not following.content.startswith("<!--"):
            break
        if _DECLARATION_PREFIX.match(following.content):
            return True
    return False


def declare_link_role(markdown: str, role: str) -> str:
    """Attach an explicit reviewed intent; this does not grant authority."""
    if role not in ROLES:
        raise ValueError("unsupported Markdown occurrence role")
    digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    return markdown + f"<!-- wiki-link-role.v1 {role} sha256:{digest} -->"


def declare_projection(markdown: str, *, consumes: list[str], produces: list[str] | None = None) -> str:
    """A generated occurrence declares its input/output fields, never grants."""
    produces = produces or ['body']
    for fields in (consumes, produces):
        if not fields or len(fields) > 64 or any(not re.fullmatch(r'[a-z][a-z0-9_]*', field) for field in fields):
            raise ValueError('invalid projection fields')
    digest = hashlib.sha256(markdown.encode('utf-8')).hexdigest()
    return (markdown + '<!-- wiki-link-role.v2 projection consumes:' + ','.join(sorted(set(consumes)))
            + ' produces:' + ','.join(sorted(set(produces))) + ' sha256:' + digest + ' -->')


def _tracked_link(state, silent):
    start, count = state.pos, len(state.tokens)
    accepted = link(state, silent)
    if accepted and not silent:
        created = state.tokens[count:]
        opening = next((t for t in created if t.type == "link_open"), None)
        closing = next((t for t in reversed(created) if t.type == "link_close"), None)
        if opening is not None and closing is not None:
            opening.meta[_SPAN] = closing.meta[_SPAN] = (start, state.pos)
    return accepted


def _tracked_html(state, silent):
    start, count = state.pos, len(state.tokens)
    accepted = html_inline(state, silent)
    if accepted and not silent and len(state.tokens) > count:
        token = state.tokens[-1]
        if token.type == "html_inline":
            token.meta[_SPAN] = (start, state.pos)
    return accepted


def parse_role_markdown(body: str):
    """Return the usual CommonMark tokens plus positively verified spans.

    Map inline content only when it is a unique contiguous literal in its
    source block. Indentation/reflow ambiguity is deliberately conservative.
    Never use a destination or a line number to merge different occurrences.
    """
    parser = MarkdownIt("commonmark", {"store_labels": True})
    parser.inline.ruler.at("link", _tracked_link)
    parser.inline.ruler.at("html_inline", _tracked_html)
    tokens = parser.parse(body)
    lines = body.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    roles = {}
    for token in tokens:
        if token.type != "inline" or token.map is None or not token.content:
            continue
        start, end = (offsets[n] for n in token.map)
        block = body[start:end]
        relative = block.find(token.content)
        if relative < 0 or block.find(token.content, relative + 1) >= 0:
            continue
        absolute = start + relative
        children = token.children or []
        for index, child in enumerate(children):
            if child.type != "html_inline" or index == 0:
                continue
            marker = _MARKER.fullmatch(child.content)
            projection = _PROJECTION_MARKER.fullmatch(child.content)
            closing = children[index - 1]
            span = closing.meta.get(_SPAN) if closing.type == "link_close" else None
            marker_span = child.meta.get(_SPAN)
            if (not marker and not projection) or not span or not marker_span or span[1] != marker_span[0]:
                continue
            if _has_following_declaration(children, index):
                continue
            # The matching opener must have the very same parser-produced span.
            opening = next((t for t in reversed(children[:index - 1])
                            if t.type == "link_open" and t.meta.get(_SPAN) == span), None)
            if opening is None:
                continue
            literal = token.content[span[0]:span[1]]
            digest = hashlib.sha256(literal.encode("utf-8")).hexdigest()
            if digest != (projection.group(3) if projection else marker.group(2)):
                continue
            body_span = (absolute + span[0], absolute + span[1])
            if body[body_span[0]:body_span[1]] != literal:
                continue
            opening.meta[_ABSOLUTE_SPAN] = body_span
            roles[body_span] = {
                "schema_version": "wiki_link_role.v2" if projection else "wiki_link_role.v1",
                "role": "projection" if projection else marker.group(1),
                **({"consumed_fields": projection.group(1).split(","),
                    "produced_fields": projection.group(2).split(",")} if projection else {}),
                "link_sha256": digest, "body_marker_offset": absolute + marker_span[0],
            }
    return tokens, roles


def project_link_role(edge: dict, declaration: dict | None) -> dict:
    """Use the existing nonfactual relation vocabulary in the same projector."""
    if declaration is None:
        return edge
    kinds = {"navigation": "navigation_link", "change_target": "record_context_reference",
             "factual_support": "markdown_link", "operational_prerequisite": "operational_prerequisite",
             "projection_state": "projection_state", "projection": "projection", "review_record": "review_record",
             "historical_support": "historical_support"}
    return {**edge, "type": kinds[declaration["role"]],
            **({"consumed_fields": declaration["consumed_fields"], "produced_fields": declaration["produced_fields"]}
               if declaration.get("schema_version") == "wiki_link_role.v2" else {}),
            "classification": "authored_occurrence_role",
            "authored_role": declaration["role"], "role_declaration": dict(declaration)}
