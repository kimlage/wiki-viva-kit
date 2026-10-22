"""Complete AST list items, never a convenient fragment of a mixed assertion."""
import copy

import pytest

from wiki_core.document_records import digest
from wiki_core.document_view_selectors import body_span, partition_view


def selector(prefix="- Readback:"):
    return dict(kind="markdown_list_item", container_heading_path=["Evidence"],
                literal_prefix=prefix, required_match_count=1)


def selected(text, choice=None):
    span = body_span(text, choice or selector())
    return None if span is None else "".join(text.splitlines(keepends=True)[span[0]:span[1]])


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("marker", ["-", "1.", "+"])
def test_whole_item_contains_continuation_and_nested_norm(newline, marker):
    item = (f"{marker} Readback: [capture](capture.md)\n"
            "  continued observation\n\n"
            "    Do not disclose without approval.\n"
            "    - Nested revocation stays in this same record.\n")
    text = "## Evidence\n\n" + item + "- Independent sibling.\n"
    text = text.replace("\n", newline)
    assert selected(text, selector(f"{marker} Readback:")) == item.replace("\n", newline)


def test_nested_item_cannot_be_selected_without_enclosing_qualification():
    text = "## Evidence\n\n- Parent: do not disclose.\n  - Readback: [capture](capture.md)\n"
    assert selected(text, selector("  - Readback:")) is None


def test_duplicate_item_prefix_and_ambiguous_heading_fail():
    item = "- Readback: recorded once.\n"
    with pytest.raises(ValueError, match="duplicate list item"):
        selected("## Evidence\n\n" + item * 2)
    with pytest.raises(ValueError, match="ambiguous container"):
        selected("## Evidence\n\n" + item + "## Evidence\n\n" + item)


@pytest.mark.parametrize("item", [
    "- Readback: [capture][proof]\n\n[proof]: capture.md\n",
    "- Readback: <span>uncertain</span>\n",
    "- Readback: ![capture](capture.png)\n",
    "- Readback: recorded.\n\n  ```md\n  - Code is not evidence.\n  ```\n",
])
def test_uncertain_reference_code_html_image_fail_closed(item):
    with pytest.raises(ValueError, match="unsupported code"):
        selected("## Evidence\n\n" + item)


def test_fenced_and_quoted_lookalikes_are_not_independent_items():
    assert selected("## Evidence\n\n```md\n- Readback: fake.\n```\n") is None
    assert selected("## Evidence\n\n> - Readback: quoted.\n", selector("> - Readback:")) is None


def test_inline_code_is_retained_literal_not_a_link_or_item_boundary():
    item = "- Readback: `Featured` and `- fake [link](hidden.md)` were inspected.\n"
    assert selected("## Evidence\n\n" + item + "- Do not disclose.\n") == item


@pytest.mark.parametrize("wrapper", ["blockquote", "div", "section"])
@pytest.mark.parametrize("heading_inside", [False, True])
def test_raw_html_wrapper_cannot_shed_enclosing_context(wrapper, heading_inside):
    heading = "## Evidence\n\n"
    opening = f"<{wrapper}>\n\nPrivate: do not disclose.\n\n"
    text = (opening + heading if heading_inside else heading + opening)
    text += f"- Readback: [capture](capture.md)\n\n</{wrapper}>\n"
    with pytest.raises(ValueError, match="raw HTML container"):
        selected(text)


def test_missing_and_full_lexeme_hash_drift_fail_partition():
    item = "- Readback: recorded.\n  Never disclose.\n"
    text = "## Evidence\n\n" + item
    entry = dict(id="readback", selectors={o: selector() for o in ("base", "current")},
                 base_sha256=digest(item), current_sha256=digest(item))
    assert partition_view(text, [entry], "base")["parts"]["readback"]["content_sha256"] == digest(item)
    with pytest.raises(ValueError, match="hash mismatch"):
        partition_view(text.replace("Never", "May"), [entry], "current")
    with pytest.raises(ValueError, match="record selector missing"):
        partition_view("## Evidence\n\n- Other item.\n", [entry], "base")
    with pytest.raises(ValueError, match="overlapping"):
        partition_view(text, [entry, {**copy.deepcopy(entry), "id": "overlap"}], "base")


@pytest.mark.parametrize("fault", ["path", "count", "prefix", "multiline"])
def test_identity_is_explicit(fault):
    choice = selector()
    if fault == "path":
        choice.pop("container_heading_path")
    elif fault == "count":
        choice["required_match_count"] = 2
    elif fault == "prefix":
        choice["literal_prefix"] = ""
    else:
        choice["literal_prefix"] += "\n"
    with pytest.raises(ValueError):
        selected("## Evidence\n\n- Readback: recorded.\n", choice)
