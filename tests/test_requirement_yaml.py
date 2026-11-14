import pytest

from wiki_core.requirement_yaml import RequirementYamlError, check_requirement_yaml


@pytest.mark.parametrize('block', [
    'information_requirements: []\ninformation_requirements: []',
    'information_requirements: [{target: one}]\n"information_requirements": []',
    'information_requirements: []\n!!str information_requirements: [{target: one}]',
    'information_requirements: [{target: one, target: two}]',
    'information_requirements: [{query: {filters: {amount: true, amount: 1}}}]',
    'defaults: &d {information_requirements: []}\n<<: *d\ninformation_requirements: []',
    'defaults: &d {target: one}\ninformation_requirements: [{<<: *d, target: two}]',
    'information_requirements: &r [*r]',
])
def test_ambiguous_or_cyclic_requirement_subtree_is_refused(block):
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        check_requirement_yaml('---\n' + block + '\n---\nBody\n')


@pytest.mark.parametrize('block', [
    'title: ordinary',
    'information_requirements: [{target: one, fields: ["*"]}]',
    'metadata: &m {title: example}\ncopy: *m\n<<: *m',
    'metadata: &m [*m]\ninformation_requirements: []',
    'shared: &s {target: one}\ninformation_requirements: [*s, *s]',
    'shared: &s {fields: ["*"]}\ninformation_requirements: [{<<: *s, target: one}]',
])
def test_unambiguous_requirements_and_unrelated_aliases_are_allowed(block):
    check_requirement_yaml('---\n' + block + '\n---\nBody\n')


def test_missing_frontmatter_and_bounded_depth():
    check_requirement_yaml('# Plain Markdown\n')
    nested = '[' * 129 + '0' + ']' * 129
    with pytest.raises(RequirementYamlError, match='frontmatter unavailable'):
        check_requirement_yaml('---\nmetadata: ' + nested + '\n---\n')


def test_long_merge_alias_chain_fails_with_controlled_error():
    rows = ['m0: &m0 {x: 1}']
    rows += [f'm{i}: &m{i} {{<<: *m{i - 1}}}' for i in range(1, 1100)]
    rows.append('<<: *m1099')
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        check_requirement_yaml('---\n' + '\n'.join(rows) + '\n---\n')
