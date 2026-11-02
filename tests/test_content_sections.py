import pytest

from wiki_core.content_sections import SectionError, parse_sections, section_digests, select_section


DOCUMENT = '''---
page_id: synthetic
---
# Policy
<!-- wiki:section id=criteria version=1 -->
## Criteria
Apply the condition.
### Exception
Preserve this qualifier.
```md
<!-- wiki:section id=pretend version=1 -->
## Fake
```
<!-- wiki:section id=next version=1 -->
## Next
Other material.
'''


def test_nested_qualifiers_fences_and_next_boundary_preserved():
    sections = parse_sections(DOCUMENT)
    assert set(sections) == {'criteria', 'next'}
    selected = select_section(DOCUMENT, 'section:criteria')
    assert '### Exception\nPreserve this qualifier.' in selected.text
    assert '## Fake' in selected.text
    assert 'id=next' not in selected.text
    assert '## Next' not in selected.text


def test_explicit_missing_never_falls_back_to_body():
    with pytest.raises(SectionError, match='missing section'):
        select_section(DOCUMENT, 'absent')


def test_duplicate_identity_and_unattached_marker_fail_closed():
    with pytest.raises(SectionError, match='duplicate'):
        parse_sections(DOCUMENT + '\n<!-- wiki:section id=criteria version=1 -->\n## Duplicate\n')
    with pytest.raises(SectionError, match='not attached'):
        parse_sections('<!-- wiki:section id=bad version=1 -->\nA paragraph\n## Heading\n')


def test_html_boundaries_and_indented_code_are_not_markers():
    document = '<div>\n<!-- wiki:section id=html version=1 -->\n## Fake\n</div>\n\n    <!-- wiki:section id=code version=1 -->\n\n## Actual\n'
    assert parse_sections(document) == {}


def test_title_rename_preserves_identity_and_body_change_invalidates_digest():
    before = section_digests(DOCUMENT)
    renamed = section_digests(DOCUMENT.replace('## Criteria', '## Renamed criteria'))
    assert set(before) == set(renamed) == {'section:criteria', 'section:next'}
    assert before['section:criteria'] != renamed['section:criteria']
    changed = section_digests(DOCUMENT.replace('Preserve this qualifier.', 'New exception.'))
    assert before['section:criteria'] != changed['section:criteria']
    assert before['section:next'] == changed['section:next']


def test_setext_heading_is_supported():
    assert select_section('<!-- wiki:section id=stable version=2 -->\nTitle\n=====\nText\n', 'stable').version == 2


@pytest.mark.parametrize('document', [
    '> <!-- wiki:section id=nested version=1 -->\n> ## Nested\n> Qualified rule.\n\n## Outer\nUnrelated body.\n',
    '- <!-- wiki:section id=nested version=1 -->\n  ## Nested\n  Qualified rule.\n\n## Outer\nUnrelated body.\n',
])
def test_nested_container_markers_fail_instead_of_leaking_outer_content(document):
    with pytest.raises(SectionError, match='top-level'):
        parse_sections(document)


def test_raw_html_wrapper_with_blank_lines_fails_instead_of_shedding_qualifier():
    document = '<div data-condition="restricted">\n\n<!-- wiki:section id=inside version=1 -->\n## Inside\nQualified content.\n\n</div>\n\n## Outside\nOther content.\n'
    with pytest.raises(SectionError, match='HTML wrappers'):
        select_section(document, 'inside')
