"""Parity tests for the canonical frontmatter parser.

The point of ``wiki_core.frontmatter`` is that there is now ONE parser. These
tests pin:
  * the yaml-based :func:`parse_frontmatter` agrees with ``yaml.safe_load`` on
    flat AND nested blocks (including ``affected_pages.must_update`` maps);
  * :func:`split_frontmatter` distinguishes "no block" (``None``) from "empty";
  * the flat parser keeps the string-flattening contract the shape gate needs;
  * :func:`list_values` covers csv-as-single / list / single / None / ``[]``.
"""

from __future__ import annotations

import yaml

import pytest

from wiki_core.frontmatter import (
    list_values,
    parse_frontmatter,
    parse_frontmatter_flat,
    parse_frontmatter_flat_with_errors,
    split_frontmatter,
)


def _doc(block: str, body: str = "\n# Title\n\nbody\n") -> str:
    return f"---\n{block}\n---{body}"


# ---------------------------------------------------------------------------
# parse_frontmatter (yaml) parity
# ---------------------------------------------------------------------------


def test_parse_frontmatter_flat_block_matches_yaml():
    block = (
        "page_id: p-1\n"
        "page_type: dashboard\n"
        "stale_after_days: 7\n"
        "requires_gate: true\n"
        "source_refs:\n"
        "  - a.md\n"
        "  - b.md\n"
    )
    values, body = parse_frontmatter(_doc(block))
    assert values == yaml.safe_load(block)
    assert values["stale_after_days"] == 7  # yaml keeps the int
    assert values["requires_gate"] is True
    assert values["source_refs"] == ["a.md", "b.md"]
    # FRONTMATTER_RE consumes the closing fence's trailing newline, so the body
    # begins at the first content line.
    assert body.startswith("# Title")


def test_parse_frontmatter_nested_map_matches_yaml():
    block = (
        "page_type: ingestion_event\n"
        "affected_pages:\n"
        "  must_update:\n"
        "    - memories/a.md\n"
        "    - memories/b.md\n"
        "  should_review: []\n"
        "impact_closure:\n"
        "  updated: []\n"
        "  no_change: []\n"
        "  blocked: []\n"
    )
    values, _body = parse_frontmatter(_doc(block))
    assert values == yaml.safe_load(block)
    assert values["affected_pages"]["must_update"] == [
        "memories/a.md",
        "memories/b.md",
    ]
    assert values["affected_pages"]["should_review"] == []
    assert isinstance(values["impact_closure"], dict)


def test_parse_frontmatter_inline_flow_map_matches_yaml():
    block = "affected_pages: {must_update: [], should_review: []}\n"
    values, _body = parse_frontmatter(_doc(block))
    assert values == yaml.safe_load(block)
    assert values["affected_pages"] == {"must_update": [], "should_review": []}


def test_parse_frontmatter_no_block_returns_empty_and_full_text():
    text = "# No frontmatter\n\nbody only.\n"
    values, body = parse_frontmatter(text)
    assert values == {}
    assert body == text


def test_parse_frontmatter_accepts_path(tmp_path):
    path = tmp_path / "page.md"
    path.write_text(_doc("page_id: p\npage_type: dashboard"), encoding="utf-8")
    values, _body = parse_frontmatter(path)
    assert values["page_id"] == "p"


def test_parse_frontmatter_malformed_yaml_is_empty():
    # Unbalanced bracket -> YAMLError -> {} (never raises).
    values, _body = parse_frontmatter(_doc("source_refs: [a, b"))
    assert values == {}


# ---------------------------------------------------------------------------
# split_frontmatter: None (no block) vs {} (empty)
# ---------------------------------------------------------------------------


def test_split_frontmatter_distinguishes_missing_from_empty():
    missing, _ = split_frontmatter("# legacy page\n\nno frontmatter\n")
    assert missing is None
    empty, _ = split_frontmatter("---\n\n---\n\nbody\n")
    assert empty == {}
    present, _ = split_frontmatter(_doc("page_id: p"))
    assert present == {"page_id": "p"}


# ---------------------------------------------------------------------------
# flat parser: string-flattening contract
# ---------------------------------------------------------------------------


def test_flat_parser_flattens_scalars_to_strings():
    values = parse_frontmatter_flat(
        _doc("page_id: p\nstale_after_days: 7\nvisibility: private_self")
    )
    # The shape gate relies on this: 7 stays the string "7".
    assert values["stale_after_days"] == "7"
    assert values["page_id"] == "p"


def test_flat_parser_strips_quotes():
    # wiki_audit finding 15: quoted visibility must lose the quotes.
    values = parse_frontmatter_flat(_doc('visibility: "public_candidate"'))
    assert values["visibility"] == "public_candidate"


def test_flat_parser_list_block_and_empty_list():
    values = parse_frontmatter_flat(
        _doc("source_refs:\n  - a.md\n  - b.md\nconsolidated_into: []")
    )
    assert values["source_refs"] == ["a.md", "b.md"]
    assert values["consolidated_into"] == []


def test_flat_parser_missing_and_unterminated_blocks():
    missing = parse_frontmatter_flat("no block here\n")
    assert missing == {}
    unterminated = parse_frontmatter_flat("---\npage_id: p\nno closing fence\n")
    assert unterminated == {}


def test_flat_with_errors_reports_required_keys():
    values, errors = parse_frontmatter_flat_with_errors(
        _doc("page_id: p"), required_keys={"page_id", "page_type"}
    )
    assert values == {"page_id": "p"}
    assert "missing keys: page_type" in errors


def test_flat_with_errors_structural_messages():
    _v1, e1 = parse_frontmatter_flat_with_errors("no block\n")
    assert "missing frontmatter block" in e1
    _v2, e2 = parse_frontmatter_flat_with_errors("---\nkey: v\nstill open\n")
    assert "unterminated frontmatter block" in e2
    _v3, e3 = parse_frontmatter_flat_with_errors(_doc("page_id: p\nnot a kv line"))
    assert any(err.startswith("invalid frontmatter line:") for err in e3)


# ---------------------------------------------------------------------------
# list_values: csv / list / single / None / []
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, []),
        ([], []),
        ("", []),
        ("[]", []),
        ("   ", []),
        ("single.md", ["single.md"]),
        ("  padded  ", ["padded"]),
        # A CSV STRING is kept as one element (callers that want true CSV use
        # config._parse_contexts). This pins the documented merge decision.
        ("a, b, c", ["a, b, c"]),
        (["a.md", "b.md"], ["a.md", "b.md"]),
        (("a.md", "b.md"), ["a.md", "b.md"]),
        (["a.md", "", "  ", "b.md"], ["a.md", "b.md"]),
        ([1, 2, 3], ["1", "2", "3"]),
        (7, ["7"]),
        (True, ["True"]),
    ],
)
def test_list_values_cases(value, expected):
    assert list_values(value) == expected


# ---------------------------------------------------------------------------
# Property-based parity with yaml.safe_load (hypothesis if available)
# ---------------------------------------------------------------------------

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

_keys = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=8)
_scalars = st.one_of(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-./ ", min_size=0, max_size=12),
    st.integers(min_value=-100, max_value=100),
    st.booleans(),
)


@settings(max_examples=200, deadline=None)
@given(st.dictionaries(_keys, _scalars, max_size=6))
def test_parse_frontmatter_parity_flat(mapping):
    block = yaml.safe_dump(mapping, sort_keys=True, allow_unicode=True) if mapping else ""
    text = f"---\n{block}---\n\nbody\n" if block else "---\n\n---\n\nbody\n"
    values, _body = parse_frontmatter(text)
    expected = yaml.safe_load(block) if block else None
    assert values == (expected if isinstance(expected, dict) else {})


@settings(max_examples=100, deadline=None)
@given(
    st.dictionaries(
        _keys,
        st.lists(st.text(alphabet="abcdefghijklmnop0123456789-./", min_size=1, max_size=8), max_size=4),
        max_size=4,
    )
)
def test_parse_frontmatter_parity_nested_lists(mapping):
    block = yaml.safe_dump(mapping, sort_keys=True, allow_unicode=True) if mapping else ""
    text = f"---\n{block}---\n\nbody\n" if block else "---\n\n---\n\nbody\n"
    values, _body = parse_frontmatter(text)
    expected = yaml.safe_load(block) if block else None
    assert values == (expected if isinstance(expected, dict) else {})
