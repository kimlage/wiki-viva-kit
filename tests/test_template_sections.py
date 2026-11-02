from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from wiki_core.config import WikiConfig
from wiki_core.content_sections import parse_sections, select_section
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.page_types import load_page_type_registry
from wiki_core.repository_reader import RepositoryReader
from wiki_core.template_sections import (TemplateSectionError, load_section_contract,
    selectors_for_roles, validate_section_page, read_template_file, MAX_BYTES, MAX_DEPTH)
from wiki_core.templates import resolve_template, instantiate_template

FIXTURES = Path(__file__).parent / 'fixtures/template-sections'
REF = 'tests/fixtures/template-sections/decision-risk.yaml'


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / 'tests/fixtures/template-sections'
    target.parent.mkdir(parents=True)
    shutil.copytree(FIXTURES, target)
    (tmp_path / 'wiki.page-types.yaml').write_text(yaml.safe_dump({'schema_version': 'wiki_page_types.v1',
        'page_types': {'decision': {'template': 'tests/fixtures/template-sections/decision.md',
                                  'allowed_dirs': ['memories/decisions']}}}))
    return tmp_path


def resolve(root, **override):
    config = WikiConfig(templates={'page_type_overrides': {'decision': {'section_contract': REF, **override}}})
    return resolve_template(root, config, load_page_type_registry(root), 'decision'), config


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_real_resolve_instantiate_read_select_validate(repo):
    resolved, config = resolve(repo)
    contract = resolved.section_contract
    text = instantiate_template(resolved, title='Synthetic launch', context='example', config=config)
    fm, _ = parse_frontmatter(text)
    assert fm['schema_version'] == 1
    assert fm['template_version'] == '1'
    assert fm['template_id'] == 'decision-risk'
    assert validate_section_page(text, contract) == []
    assert len(validate_section_page(text, contract, mode='filled')) == 5
    assert list(parse_sections(text)) == ['facts', 'constraints', 'risk', 'decision', 'evidence', 'uncertainty', 'next-step']
    for section in contract['sections']:
        old = select_section(text, section['id']).text
        text = text.replace(old, old.rstrip() + f'\nSynthetic statement for {section["id"]}.\n\n')
    assert validate_section_page(text, contract, mode='filled') == []
    # Visual title changes preserve identity and contract version.
    text = text.replace('## Evidence', '## Supporting records')
    assert validate_section_page(text, contract, mode='filled') == []
    (repo / 'page.md').write_text(text)
    git(repo, 'init', '-q')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'fixture')
    reader = RepositoryReader(repo)
    selectors = selectors_for_roles(contract, ['constraints', 'evidence'])
    assert selectors == ['section:constraints', 'section:evidence']
    for selector in selectors:
        result = reader.read('decision-synthetic-launch', section=selector)
        assert result['section'] == selector.split(':', 1)[1]
        assert 'Synthetic statement' in result['text']
        assert result['frontmatter'] == {}
    # Updating a contract never writes/migrates the committed or working page.
    before = (repo / 'page.md').read_bytes()
    parent = repo / 'tests/fixtures/template-sections/decision.yaml'
    parent.write_text(parent.read_text().replace("template_version: '1'", "template_version: '2'"))
    with pytest.raises(TemplateSectionError, match='parent template identity/version mismatch'):
        resolve(repo)
    assert (repo / 'page.md').read_bytes() == before


@pytest.mark.parametrize('change', [
    lambda s: s + '\nsections: []\n',
    lambda s: s.replace('id: risk', 'id: evidence'),
    lambda s: s.replace("slot: 'before:decision'", "slot: 'before:facts'"),
    lambda s: s + '\nallowed_slots: []\n',
    lambda s: s.replace('role: uncertainty', 'role: invented'),
])
def test_extension_cannot_redefine_or_weaken_parent(repo, change):
    path = repo / REF
    path.write_text(change(path.read_text()))
    with pytest.raises(TemplateSectionError):
        load_section_contract(repo, REF)


@pytest.mark.parametrize('bad', ['../outside.yaml', '/tmp/outside.yaml', 'tests/../outside.yaml'])
def test_paths_are_confined(repo, bad):
    with pytest.raises(TemplateSectionError):
        load_section_contract(repo, bad)


def test_duplicate_keys_symlinks_cycles_size_and_depth(repo):
    path = repo / REF
    original = path.read_text()
    path.write_text(original + '\ntemplate_version: 2\n')
    with pytest.raises(TemplateSectionError, match='duplicate'):
        load_section_contract(repo, REF)
    path.write_text(original.replace('tests/fixtures/template-sections/decision.yaml', REF))
    with pytest.raises(TemplateSectionError, match='cycle'):
        load_section_contract(repo, REF)
    path.unlink()
    path.symlink_to('decision.yaml')
    with pytest.raises(TemplateSectionError, match='symlink'):
        load_section_contract(repo, REF)
    path.unlink()
    path.write_text('x' * (MAX_BYTES + 1))
    with pytest.raises(TemplateSectionError, match='byte budget'):
        load_section_contract(repo, REF)
    for index in range(MAX_DEPTH + 1):
        (repo / f'c{index}.yaml').write_text(yaml.safe_dump({'schema_version': 'wiki_template_sections.v1',
            'template_id': 'nested', 'template_version': '1', 'extends': {'path': f'c{index+1}.yaml', 'template_id': 'nested', 'template_version': '1'}, 'add_sections': []}))
    with pytest.raises(TemplateSectionError, match='depth'):
        load_section_contract(repo, 'c0.yaml')


def test_structure_filled_missing_duplicate_and_version_are_distinct(repo):
    resolved, config = resolve(repo)
    text = instantiate_template(resolved, title='Synthetic', context='example', config=config)
    contract = resolved.section_contract
    assert validate_section_page(text, contract) == []
    for placeholder in ['TODO', '{{write_here}}', '<!-- later -->', '## Nested heading']:
        candidate = text.replace('## Facts', f'## Facts\n{placeholder}')
        assert 'empty or placeholder required section: facts' in validate_section_page(candidate, contract, mode='filled')
    missing = text.replace(select_section(text, 'evidence').text, '')
    assert 'missing required section: evidence' in validate_section_page(missing, contract)
    duplicate = text + '\n<!-- wiki:section id=facts version=1 -->\n## Duplicate\n'
    assert any('duplicate' in error for error in validate_section_page(duplicate, contract))
    wrong = text.replace('template_version: \"1\"', 'template_version: \"2\"')
    assert any('template_version mismatch' in error for error in validate_section_page(wrong, contract))
    with pytest.raises(TemplateSectionError):
        selectors_for_roles(contract, ['unknown'])


def test_opt_in_skeleton_and_overlay_must_be_confined_and_bounded(repo):
    with pytest.raises(TemplateSectionError):
        resolve(repo, template='../outside.md')
    path = repo / 'alias.md'
    path.symlink_to('tests/fixtures/template-sections/decision.md')
    with pytest.raises(TemplateSectionError):
        resolve(repo, overlay='alias.md')
    path.unlink()
    path.write_text('x' * (MAX_BYTES + 1))
    with pytest.raises(TemplateSectionError):
        resolve(repo, overlay='alias.md')


def test_legacy_opt_out_keeps_old_text_and_metadata(repo):
    config = WikiConfig()
    resolved = resolve_template(repo, config, load_page_type_registry(repo), 'decision')
    assert resolved.section_contract is None
    assert resolved.template_id == 'decision-default'
    assert resolved.template_version == '1'
    assert resolved.text == (repo / 'tests/fixtures/template-sections/decision.md').read_text()
    assert '<!-- wiki:section' not in instantiate_template(resolved, title='Legacy', context='example', config=config)


def test_registry_contract_and_cli(repo):
    registry_path = repo / 'wiki.page-types.yaml'
    doc = yaml.safe_load(registry_path.read_text())
    doc['page_types']['decision']['section_contract'] = REF
    registry_path.write_text(yaml.safe_dump(doc))
    resolved = resolve_template(repo, WikiConfig(), load_page_type_registry(repo), 'decision')
    assert resolved.section_contract is not None
    command = [sys.executable, str(Path(__file__).parents[1] / 'scripts/wiki_template_sections.py'),
               '--root', str(repo), '--page-type', 'decision']
    checked = subprocess.run(command, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['mode'] == 'contract'
    text = instantiate_template(resolved, title='Draft', context='example', config=WikiConfig())
    (repo / 'page.md').write_text(text)
    checked = subprocess.run([*command, '--page', 'page.md', '--mode', 'filled'], capture_output=True, text=True)
    assert checked.returncode == 1
    assert len(json.loads(checked.stdout)['errors']) == 5


def test_published_schema_matches_synthetic_contracts():
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).parents[1] / 'docs/references/schemas/wiki-template-sections-v1.schema.json').read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for path in FIXTURES.glob('*.yaml'):
        validator.validate(yaml.safe_load(path.read_text()))


def test_template_version_reports_old_pages_without_writing_them(repo):
    resolved, config = resolve(repo)
    page = repo / 'old-page.md'
    page.write_text(instantiate_template(resolved, title='Existing', context='example', config=config))
    before = page.read_bytes()
    contract_file = repo / REF
    doc = yaml.safe_load(contract_file.read_text())
    doc['template_version'] = '2'
    contract_file.write_text(yaml.safe_dump(doc))
    updated, _ = resolve(repo)
    assert validate_section_page(before.decode(), updated.section_contract) == [
        'template_version mismatch; explicit review/migration required']
    assert page.read_bytes() == before


def test_immutable_pack_rejects_unverified_section_contract(repo):
    registry = load_page_type_registry(repo)
    registry.page_types['decision']['experience_pack'] = {'id': 'synthetic', 'version': '1'}
    config = WikiConfig(templates={'page_type_overrides': {'decision': {'section_contract': REF}}})
    with pytest.raises(ValueError, match='immutable installed pack'):
        resolve_template(repo, config, registry, 'decision')


def test_contract_metadata_is_rendered_as_yaml_scalars(repo):
    path = repo / REF
    doc = yaml.safe_load(path.read_text())
    doc['template_id'] = 'decision\nvisibility: injected'
    doc['template_version'] = 'true'
    path.write_text(yaml.safe_dump(doc))
    resolved, config = resolve(repo)
    text = instantiate_template(resolved, title='Synthetic', context='example', config=config)
    fm, _ = parse_frontmatter(text)
    assert fm['template_id'] == doc['template_id']
    assert fm['template_version'] == 'true'
    assert fm['visibility'] == 'public'
    assert validate_section_page(text, resolved.section_contract) == []


@pytest.mark.parametrize('key,value', [('template_id', 'renamed-parent'), ('template_version', '2')])
def test_parent_pin_drift_blocks_resolution_without_rewriting_page(repo, key, value):
    resolved, config = resolve(repo)
    page = repo / 'existing.md'
    page.write_text(instantiate_template(resolved, title='Existing', context='example', config=config))
    before = page.read_bytes()
    parent_file = repo / 'tests/fixtures/template-sections/decision.yaml'
    parent = yaml.safe_load(parent_file.read_text())
    parent[key] = value
    parent_file.write_text(yaml.safe_dump(parent))
    with pytest.raises(TemplateSectionError, match='parent template identity/version mismatch'):
        resolve(repo)
    assert page.read_bytes() == before
    # Explicitly reviewed pin/version edits are consumer choices, never automatic.
    child_file = repo / REF
    child = yaml.safe_load(child_file.read_text())
    child['extends'][key] = value
    child['template_version'] = '2'
    child_file.write_text(yaml.safe_dump(child))
    updated, _ = resolve(repo)
    assert updated.template_version == '2'
    assert validate_section_page(before.decode(), updated.section_contract) == [
        'template_version mismatch; explicit review/migration required']
    assert page.read_bytes() == before


@pytest.mark.parametrize('pin', ['tests/fixtures/template-sections/decision.yaml',
    {'path': 'tests/fixtures/template-sections/decision.yaml'},
    {'path': 'tests/fixtures/template-sections/decision.yaml', 'template_id': 'decision-modular',
     'template_version': 1}])
def test_inheritance_requires_explicit_string_identity_version_pin(repo, pin):
    path = repo / REF
    doc = yaml.safe_load(path.read_text())
    doc['extends'] = pin
    path.write_text(yaml.safe_dump(doc))
    with pytest.raises(TemplateSectionError, match='extends must pin'):
        resolve(repo)


@pytest.mark.parametrize('kind', ['fifo', 'directory'])
@pytest.mark.parametrize('reader', [load_section_contract, read_template_file])
def test_nonregular_inputs_are_rejected_before_open(repo, monkeypatch, kind, reader):
    target = repo / 'nonregular'
    if kind == 'fifo':
        os.mkfifo(target)
    else:
        target.mkdir()
    def forbidden_open(*args, **kwargs):
        raise AssertionError('nonregular input must never reach open')
    monkeypatch.setattr(Path, 'open', forbidden_open)
    with pytest.raises(TemplateSectionError, match='regular file'):
        reader(repo, 'nonregular')
