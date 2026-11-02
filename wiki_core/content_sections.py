"""CommonMark section selectors with explicit, heading-bound stable identities."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from markdown_it import MarkdownIt

from wiki_core.frontmatter import parse_frontmatter

PARSER_VERSION = 1
_MARKER = re.compile(r'<!-- wiki:section id=([a-zA-Z][a-zA-Z0-9_.:-]*) version=([1-9][0-9]*) -->')


class SectionError(ValueError):
    """An explicit section is missing, ambiguous or malformed."""


@dataclass(frozen=True)
class ContentSection:
    id: str
    version: int
    heading: str
    level: int
    text: str
    start_line: int
    end_line: int

    @property
    def content_digest(self) -> str:
        return hashlib.sha256(self.text.encode('utf-8')).hexdigest()


def parse_sections(document_text: str) -> dict[str, ContentSection]:
    """Select source slices, preserving nested content and Markdown boundaries.

    A marker must be a standalone CommonMark HTML comment immediately before a
    heading in the same container. Code fences and HTML block contents never
    create selectors. A section extends through subordinate headings to the next
    heading of equal or lower level, including any unlabelled exceptions.
    """
    _, body = parse_frontmatter(document_text)
    lines = body.splitlines(keepends=True)
    tokens = MarkdownIt('commonmark').parse(body)
    headings = []
    markers = []
    for i, token in enumerate(tokens):
        if token.type == 'heading_open' and token.map:
            headings.append((i, token, tokens[i + 1].content))
        if token.type == 'html_block' and token.map:
            match = _MARKER.fullmatch(token.content.strip())
            if match:
                markers.append((i, token, match))
    # CommonMark HTML blocks can terminate at a blank line while their raw
    # wrapper remains open. Do not detach selected prose from that qualifier.
    if markers and any(token.type == 'html_block' and
                       re.match(r'</?[A-Za-z][^>]*>', token.content.lstrip())
                       for token in tokens):
        raise SectionError('raw HTML wrappers are unsupported for section selection')
    bound = {}
    for i, marker, match in markers:
        if marker.level != 0:
            raise SectionError("section markers require top-level headings")
        heading = tokens[i + 1] if i + 1 < len(tokens) else None
        if (heading is None or heading.type != 'heading_open' or not heading.map
                or heading.level != marker.level
                or any(line.strip() for line in lines[marker.map[1]:heading.map[0]])):
            raise SectionError(f'section marker is not attached to a heading: {match[1]}')
        if match[1] in bound:
            raise SectionError(f'duplicate section id: {match[1]}')
        bound[match[1]] = (marker, heading, match)
    result = {}
    for section_id, (marker, heading, match) in bound.items():
        start = marker.map[0]
        end = len(lines)
        for _, candidate, _ in headings:
            if (candidate.map[0] > heading.map[0] and candidate.level == heading.level
                    and int(candidate.tag[1:]) <= int(heading.tag[1:])):
                end = candidate.map[0]
                # The next section's identity belongs to that section alone.
                for other_marker, other_heading, _ in bound.values():
                    if other_heading is candidate:
                        end = other_marker.map[0]
                break
        title = next(title for _, candidate, title in headings if candidate is heading)
        result[section_id] = ContentSection(section_id, int(match[2]), title,
            int(heading.tag[1:]), ''.join(lines[start:end]), start, end)
    return result


def select_section(document_text: str, section_id: str) -> ContentSection:
    selected = section_id.removeprefix('section:')
    sections = parse_sections(document_text)
    if selected not in sections:
        raise SectionError(f'missing section id: {selected}')
    return sections[selected]


def section_digests(document_text: str) -> dict[str, str]:
    """Pure stable-ID digest map for the scoped information-impact consumer."""
    return {f'section:{key}': section.content_digest
            for key, section in parse_sections(document_text).items()}
