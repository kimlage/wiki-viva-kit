import pytest
import yaml

from wiki_core.requirement_yaml import RequirementYamlError, check_requirement_yaml, _canonical_bounded


@pytest.mark.parametrize('block', [
    'information_requirements: []\ninformation_requirements: []',
    'information_requirements: [{target: one}]\n"information_requirements": []',
    'information_requirements: []\n!!str information_requirements: [{target: one}]',
    'information_requirements: [{target: one, target: two}]',
    'information_requirements: [{query: {filters: {amount: true, amount: 1}}}]',
    'defaults: &d {information_requirements: [{target: one}]}\n<<: *d\ninformation_requirements: []',
    'defaults: &d {target: one, target: two}\ninformation_requirements: [{<<: *d, target: three}]',
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
    'defaults: &d {information_requirements: []}\n<<: *d\ninformation_requirements: []',
    'defaults: &d {target: one}\ninformation_requirements: [{<<: *d, target: two}]',
    'first: &a {target: one}\nsecond: &b {target: two}\ninformation_requirements: [{<<: [*a, *b]}]',
])
def test_unambiguous_requirements_and_unrelated_aliases_are_allowed(block):
    check_requirement_yaml('---\n' + block + '\n---\nBody\n')


def test_missing_frontmatter_and_bounded_depth():
    check_requirement_yaml('# Plain Markdown\n')
    nested = '[' * 129 + '0' + ']' * 129
    with pytest.raises(RequirementYamlError, match='frontmatter unavailable'):
        check_requirement_yaml('---\nmetadata: ' + nested + '\n---\n')


def test_merge_sequence_precedence_matches_current_safe_loader():
    block = ('first: &a {target: one}\nsecond: &b {target: two}\n'
             'information_requirements: [{<<: [*a, *b]}]')
    check_requirement_yaml('---\n' + block + '\n---\n')
    assert yaml.safe_load(block)['information_requirements'][0]['target'] == 'one'


def test_long_merge_alias_chain_fails_with_controlled_error():
    rows = ['m0: &m0 {x: 1}']
    rows += [f'm{i}: &m{i} {{<<: *m{i - 1}}}' for i in range(1, 1100)]
    rows.append('<<: *m1099')
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        check_requirement_yaml('---\n' + '\n'.join(rows) + '\n---\n')


@pytest.mark.parametrize('block,proposed', [
    ('information_requirements: []\ninformation_requirements: []', []),
    ('information_requirements: [{target: one}]\ninformation_requirements: [{target: one}]', [{'target': 'one'}]),
])
def test_identical_direct_duplicates_can_be_repaired_without_changing_value(block, proposed):
    check_requirement_yaml('---\n' + block + '\n---\n', repair_value=proposed)


@pytest.mark.parametrize('block,proposed', [
    ('information_requirements: []\ninformation_requirements: [{target: one}]', []),
    ('information_requirements: [{query: {filters: {value: true}}}]\ninformation_requirements: [{query: {filters: {value: 1}}}]', [{'query': {'filters': {'value': True}}}]),
    ('information_requirements: [{target: one, target: two}]\ninformation_requirements: [{target: two}]', [{'target': 'two'}]),
    ('other: &x []\ncopy: *x\ninformation_requirements: []\ninformation_requirements: []', []),
    ('information_requirements: []\ninformation_requirements: []', [{'target': 'one'}]),
])
def test_uncertain_or_changed_duplicate_repair_is_refused(block, proposed):
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        check_requirement_yaml('---\n' + block + '\n---\n', repair_value=proposed)


def test_repair_canonicalization_bounds_expanded_aliases():
    shared = 'x' * 160_000
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        _canonical_bounded([shared] * 400)
    with pytest.raises(RequirementYamlError, match='ambiguous information requirements'):
        check_requirement_yaml('---\ninformation_requirements: []\ninformation_requirements: []\n---\n',
                               repair_value=[shared] * 400)
