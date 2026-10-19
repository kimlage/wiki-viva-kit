"""Synthetic occurrence identity and conservative fallback proofs."""
import hashlib

import pytest

from wiki_core.markdown_link_roles import declare_link_role, parse_role_markdown


def test_emitter_binds_literal_and_rejects_unverified_provenance():
    literal = "[Open](item.md)"
    text = declare_link_role(literal, "navigation")
    assert hashlib.sha256(literal.encode()).hexdigest() in text
    with pytest.raises(ValueError):
        declare_link_role(literal, "provenance")


@pytest.mark.parametrize("role", ["navigation", "change_target"])
def test_exact_inline_occurrence_and_table_carry_role(role):
    literal = "[**Open**](item.md)"
    body = "| Destination |\n| --- |\n| " + declare_link_role(literal, role) + " |\n"
    _, roles = parse_role_markdown(body)
    assert list(roles) == [(body.index(literal), body.index(literal) + len(literal))]
    assert next(iter(roles.values()))["role"] == role


def test_real_link_does_not_validate_identical_inline_code_copy():
    declared = declare_link_role("[Open](item.md)", "navigation")
    body = "`" + declared + "` and " + declared
    _, roles = parse_role_markdown(body)
    assert list(roles) == [(body.rindex("[Open]"), body.rindex("[Open]") + len("[Open](item.md)"))]


@pytest.mark.parametrize("transform", [
    lambda text: "```md\n" + text + "\n```",
    lambda text: "    " + text,
    lambda text: "`" + text + "`",
    lambda text: "<div>\n" + text + "\n</div>",
    lambda text: text.replace("<!--", " <!--", 1),
    lambda text: text.replace("<!--", "\n<!--", 1),
    lambda text: text.replace("item.md", "different.md", 1),
    lambda text: text.replace("navigation", "unrecognized", 1),
    lambda text: "!" + text,
])
def test_uncertain_or_stale_declaration_never_qualifies_link(transform):
    _, roles = parse_role_markdown(transform(declare_link_role("[Open](item.md)", "navigation")))
    assert not roles


def test_marker_in_label_is_not_an_adjacent_declaration():
    marker = declare_link_role("[Open](item.md)", "navigation").split("<!--", 1)[1]
    _, roles = parse_role_markdown("[Open<!--" + marker + "](item.md)")
    assert not roles


def test_reference_style_occurrence_is_bound_without_qualifying_its_sibling():
    literal = "[Open][item]"
    body = declare_link_role(literal, "navigation") + " and [Open][item]\n\n[item]: item.md\n"
    _, roles = parse_role_markdown(body)
    assert list(roles) == [(0, len(literal))]


@pytest.mark.parametrize("second_role", ["navigation", "change_target", "factual", "unknown"])
@pytest.mark.parametrize("separator", ["", " ", "<!-- ordinary note -->"])
def test_multiple_declarations_on_same_occurrence_are_conservative(second_role, separator):
    literal = "[Open](item.md)"
    first = declare_link_role(literal, "navigation")
    digest = hashlib.sha256(literal.encode()).hexdigest()
    second = f"<!-- wiki-link-role.v1 {second_role} sha256:{digest} -->"
    _, roles = parse_role_markdown(first + separator + second)
    assert not roles


def test_code_example_of_second_marker_is_not_an_authored_declaration():
    first = declare_link_role("[Open](item.md)", "navigation")
    marker = first[first.index("<!--"):]
    _, roles = parse_role_markdown(first + " `" + marker + "`")
    assert len(roles) == 1
