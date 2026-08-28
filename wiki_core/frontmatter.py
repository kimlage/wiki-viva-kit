"""Canonical frontmatter parsing for the wiki toolkit.

For most of the kit's history there were FOUR divergent frontmatter parsers and
FIVE near-identical ``_list_values`` helpers, each with subtle differences. This
module is the single source of truth. The differences that were merged here:

Parsers (previously hand-rolled or ad-hoc ``yaml.safe_load`` wrappers):
  * ``graph.page_graph.parse_frontmatter`` -- hand-rolled, flattened every value
    to a string or a ``list[str]``; returned ``{}`` on a missing/unterminated
    block; wrapped every consumer read in ``str(...)``.
  * ``consolidate._read_frontmatter`` -- ``yaml.safe_load`` over the block;
    returned ``{}`` on error or non-mapping payload.
  * ``migration.split_frontmatter`` -- ``yaml.safe_load`` but distinguished
    "no frontmatter at all" (``None``) from "empty frontmatter" (``{}``) so the
    legacy-migration inventory can tell which pages still need a block.
  * ``scripts/wiki_audit.parse_frontmatter`` -- hand-rolled, memoized, returned a
    ``(values, errors)`` tuple and enforced ``REQUIRED_KEYS``; its string-only
    flattening is LOAD-BEARING for the page-type shape gate (e.g.
    ``stale_after_days: 7`` must stay the string ``"7"`` so a ``string`` field
    type validates -- ``yaml`` would coerce it to ``int`` and break the gate).
  * ``scripts/wiki_audit.parse_yaml_frontmatter`` -- ``yaml.safe_load`` used only
    where nested maps matter (``affected_pages.must_update``,
    ``impact_closure``).

Two strategies survive because they are genuinely different and both needed:

  * :func:`parse_frontmatter` -- ``yaml.safe_load`` based. Returns a real Python
    mapping, so nested maps (``affected_pages.must_update``) and typed scalars
    are preserved. Use this whenever you need structure or types.
  * :func:`parse_frontmatter_flat` -- the hand-rolled flattening parser. Every
    scalar becomes a ``str`` and every ``- item`` block becomes a ``list[str]``.
    Use this for the link graph and the audit shape gate, which depend on the
    "everything is a string" contract.

``list_values`` differences that were merged (the five copies):
  * ``graph.page_graph._list_values`` returned a ``tuple`` and stripped items.
  * ``closure``/``quality``/``source_config._list_values`` returned a ``list``
    and stripped items.
  * ``page_types.list_values`` returned a ``list``, did NOT strip, and filtered
    on truthiness *after* ``str(item)`` (so whitespace-only survived).
  * ``scripts/wiki_audit.list_values`` took ``(values, key)`` (not a value),
    returned the raw list items unstripped, and dropped ``tuple`` support.

The canonical :func:`list_values` returns a ``list[str]``, strips each item, and
drops empties -- the behaviour the overwhelming majority of call sites relied on.
Call sites that needed a ``tuple`` wrap the result; ``page_types`` keeps its own
non-stripping helper for the shape validator (documented at that call site).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "FRONTMATTER_RE",
    "list_values",
    "parse_frontmatter",
    "parse_frontmatter_flat",
    "split_frontmatter",
    "unquote",
]

# Matches a leading YAML fence with either LF or CRLF line endings. Snapshot
# compilation reads canonical bytes to hash them, so Windows-authored CRLF must
# parse without normalizing those bytes first.
FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n)?", re.DOTALL)


def _read_text(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8", errors="replace")
    return source


def unquote(value: str) -> str:
    """Strip a single matching pair of surrounding quotes.

    ``visibility: "public_candidate"`` must parse to ``public_candidate`` (without
    the quotes) or a public page escapes the PII block (wiki_audit finding 15).
    """
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def list_values(value: Any) -> list[str]:
    """Canonical normalization of a frontmatter value into a ``list[str]``.

    Unifies the five historical ``_list_values`` helpers. Handles:
      * ``None`` -> ``[]``
      * a ``list`` or ``tuple`` -> each item ``str``-cast, stripped, empties dropped
      * a ``str`` -> ``[]`` when blank or the literal ``"[]"``; otherwise a single
        stripped element (NOT split on commas -- CSV splitting lives in
        ``config._parse_contexts``, which has stricter validation)
      * any other scalar -> a single stripped ``str`` element
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped == "[]":
            return []
        return [stripped]
    text = str(value).strip()
    return [text] if text else []


def parse_frontmatter(source: str | Path) -> tuple[dict[str, Any], str]:
    """Parse a leading YAML frontmatter block with ``yaml.safe_load``.

    Accepts a file path or raw text. Returns ``(values, body)`` where ``values``
    is the parsed mapping (``{}`` when there is no block or the payload is not a
    mapping) and ``body`` is the remaining Markdown after the block.

    Nested maps and typed scalars are preserved (e.g. ``affected_pages`` stays a
    ``dict``; ``stale_after_days: 7`` stays the int ``7``). Use
    :func:`parse_frontmatter_flat` when you need string-flattened values.
    """
    text = _read_text(source)
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text[match.end():]
    values = data if isinstance(data, dict) else {}
    return values, text[match.end():]


def split_frontmatter(source: str | Path) -> tuple[dict[str, Any] | None, str]:
    """Like :func:`parse_frontmatter` but distinguishes "no block" from "empty".

    Returns ``(None, body)`` when there is no frontmatter block at all (the legacy
    page-migration inventory uses ``None`` to flag pages that still need one), and
    ``({}, body)`` for an empty-but-present block. A non-mapping payload (rare,
    malformed) also yields ``{}``.
    """
    text = _read_text(source)
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    data = yaml.safe_load(match.group(1)) or {}
    values = data if isinstance(data, dict) else {}
    return values, text[match.end():]


def parse_frontmatter_flat(source: str | Path) -> dict[str, Any]:
    """Hand-rolled frontmatter parse that flattens every value to a string.

    This is the historical ``graph.page_graph.parse_frontmatter`` /
    ``scripts/wiki_audit.parse_frontmatter`` body loop, made canonical. Scalars
    become ``str``; ``- item`` blocks become ``list[str]``; ``key:`` with no value
    and ``key: []`` both become ``[]``. Returns ``{}`` when the block is missing or
    unterminated.

    The link graph and the page-type shape gate depend on this "everything is a
    string" contract (``yaml`` would coerce ``stale_after_days: 7`` to an int and
    break a ``string`` field-type check), so it must not be swapped for
    :func:`parse_frontmatter`.
    """
    values, _errors = parse_frontmatter_flat_with_errors(source, required_keys=())
    return values


def parse_frontmatter_flat_with_errors(
    source: str | Path, *, required_keys: frozenset[str] | set[str] | tuple[str, ...] = ()
) -> tuple[dict[str, Any], list[str]]:
    """Flat parse that also reports structural errors (the audit gate contract).

    Returns ``(values, errors)``. ``errors`` carries the audit messages
    (``missing frontmatter block``, ``unterminated frontmatter block``,
    ``invalid frontmatter line: ...`` and, when ``required_keys`` is given,
    ``missing keys: ...``). When ``required_keys`` is empty the error list only
    reports structural problems, which is what the non-audit callers ignore.
    """
    text = _read_text(source)
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, ["missing frontmatter block"]
    try:
        end = lines[1:].index("---") + 1
    except ValueError:
        return {}, ["unterminated frontmatter block"]

    values: dict[str, Any] = {}
    errors: list[str] = []
    current_key: str | None = None
    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # YAML permits block-sequence entries at the same indentation as their
        # mapping key (the style emitted by ``yaml.safe_dump``):
        #
        #   source_refs:
        #   - source-a
        #
        # Keep the flat parser's string contract while accepting both valid
        # YAML spellings so generated fixtures and hand-authored pages agree.
        if stripped.startswith("- ") and current_key:
            current = values.setdefault(current_key, [])
            if isinstance(current, list):
                current.append(unquote(stripped[2:].strip()))
            continue
        if ":" not in raw:
            errors.append(f"invalid frontmatter line: {raw}")
            current_key = None
            continue
        key, value = raw.split(":", 1)
        current_key = key.strip()
        value = unquote(value.strip())
        if value == "[]":
            values[current_key] = []
        elif value:
            values[current_key] = value
        else:
            values[current_key] = []

    missing = sorted(set(required_keys) - values.keys())
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    return values, errors
