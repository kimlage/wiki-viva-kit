from pathlib import Path
import shutil
import sys

import pytest
import yaml

from wiki_core.config import load_config
from wiki_core.content_sections import select_section
from wiki_core.page_creation import create_page, prepare_page
from wiki_core.page_types import load_page_type_registry
from wiki_core.template_sections import validate_section_page
from wiki_core.template_sections import TemplateSectionError, read_template_file
from wiki_core.templates import resolve_template
from wiki_core.templates import instantiate_template
import scripts.wiki_new as wiki_new


@pytest.fixture
def wiki(tmp_path):
    kit = Path(__file__).resolve().parents[1]
    (tmp_path / 'wiki.config.yaml').write_text('repo_id: synthetic\ncontexts: example\ndefault_context: example\n')
    registry = yaml.safe_load((kit / 'wiki.page-types.yaml').read_text())
    (tmp_path / 'wiki.page-types.yaml').write_text(yaml.safe_dump(registry))
    for name in ('context-instructions.md', 'context-instructions.yaml'):
        src = kit / 'docs/references/templates/wiki' / name
        dest = tmp_path / 'docs/references/templates/wiki' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return tmp_path


def test_create_and_validate_context_instructions_in_selected_folder(wiki):
    path, text = prepare_page(wiki, 'context_instructions', 'A context', 'example',
                              'projects/example/AGENTS.md')
    resolved = resolve_template(wiki, load_config(wiki), load_page_type_registry(wiki),
                                'context_instructions')
    assert path == 'projects/example/AGENTS.md'
    assert 'moc_parent:' not in text
    assert validate_section_page(text, resolved.section_contract) == []
    assert len(validate_section_page(text, resolved.section_contract, mode='filled')) == 6
    for section in resolved.section_contract['sections']:
        current = select_section(text, section['id']).text
        text = text.replace(current, current.rstrip() + '\nSynthetic instruction.\n\n')
    assert validate_section_page(text, resolved.section_contract, mode='filled') == []
    create_page(wiki, path, text)
    assert (wiki / path).read_text() == text
    (wiki / 'projects/example/index.md').write_text('# Synthetic index\n')
    from wiki_core.llm.context_pass import _folder_documents
    docs = _folder_documents(wiki, 'projects/example', None, 100000)
    assert [item['path'] for item in docs] == [path, 'projects/example/index.md']
    assert docs[0]['text'] == text
    with pytest.raises(FileExistsError):
        create_page(wiki, path, text)
    assert (wiki / path).read_text() == text


def test_instructions_require_an_explicit_native_name_and_do_not_cross_git(wiki):
    with pytest.raises(ValueError, match='explicit output'):
        prepare_page(wiki, 'context_instructions', 'Synthetic')
    for path in ('projects/example/context.md', '.git/AGENTS.md', '../AGENTS.md'):
        with pytest.raises(ValueError):
            prepare_page(wiki, 'context_instructions', 'Synthetic', output=path)
    (wiki / 'projects/repo/.git').mkdir(parents=True)
    with pytest.raises(ValueError, match='boundary'):
        prepare_page(wiki, 'context_instructions', 'Synthetic', output='projects/repo/AGENTS.md')
    (wiki / 'projects/repo/AGENTS.md').write_text('Separate repository')
    with pytest.raises(TemplateSectionError, match='repository boundary'):
        read_template_file(wiki, 'projects/repo/AGENTS.md')
    (wiki / 'projects/link').symlink_to(wiki / 'projects/repo', target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_page(wiki, 'context_instructions', 'Synthetic', output='projects/link/AGENTS.md')
    path, text = prepare_page(wiki, 'context_instructions', 'Synthetic',
                              output='projects/example/AGENTS.override.md')
    (wiki / 'projects/example/.git').mkdir(parents=True)
    with pytest.raises(ValueError, match='boundary'):
        create_page(wiki, path, text)
    assert not (wiki / path).exists()


def test_normal_page_writes_remain_inside_memory_root(wiki):
    with pytest.raises(ValueError, match='memory_root'):
        create_page(wiki, 'projects/example/page.md', 'ordinary page')


def test_cli_creates_a_native_file_at_explicit_destination(wiki, monkeypatch, capsys):
    monkeypatch.setattr(wiki_new, 'ROOT', wiki)
    monkeypatch.setattr(sys, 'argv', ['wiki_new.py', '--type', 'context_instructions',
        '--title', 'Synthetic', '--output', 'contexts/alpha/AGENTS.md'])
    assert wiki_new.main() == 0
    assert capsys.readouterr().out.strip() == 'contexts/alpha/AGENTS.md'
    assert (wiki / 'contexts/alpha/AGENTS.md').is_file()
    assert wiki_new.main() == 2


def test_project_extends_the_same_instruction_contract_without_a_context_tree(wiki):
    derived = wiki / 'project-instructions.yaml'
    derived.write_text(yaml.safe_dump({
        'schema_version': 'wiki_template_sections.v1',
        'template_id': 'project-instructions', 'template_version': '1',
        'extends': {'path': 'docs/references/templates/wiki/context-instructions.yaml',
                    'template_id': 'context-instructions', 'template_version': '1'},
        'add_sections': [{'id': 'project-notes', 'title': 'Project notes',
                          'role': 'constraints', 'required': True, 'slot': 'after:limits'}],
    }))
    config = load_config(wiki)
    config.templates['page_type_overrides'] = {
        'context_instructions': {'section_contract': 'project-instructions.yaml'}}
    resolved = resolve_template(wiki, config, load_page_type_registry(wiki), 'context_instructions')
    text = instantiate_template(resolved, title='Synthetic', context='example', config=config)
    assert validate_section_page(text, resolved.section_contract) == []
    assert select_section(text, 'project-notes') is not None
    assert 'moc_parent:' not in text


@pytest.mark.parametrize('kind', ['template', 'overlay'])
@pytest.mark.parametrize('path_kind', ['nested_git', 'symlink'])
def test_instruction_override_rejects_untrusted_paths_before_open(wiki, monkeypatch, kind, path_kind):
    repo = wiki / 'projects/repo'
    (repo / '.git').mkdir(parents=True)
    target = repo / 'input.md'
    target.write_text('This file must not be opened.')
    if path_kind == 'symlink':
        selected = wiki / 'alias.md'
        selected.symlink_to(target)
    else:
        selected = target
    config = load_config(wiki)
    config.templates['page_type_overrides'] = {'context_instructions': {
        'section_contract': None, kind: selected.relative_to(wiki).as_posix()}}
    registry = load_page_type_registry(wiki)
    original_open = Path.open
    original_read_text = Path.read_text
    def guarded_open(path, *args, **kwargs):
        if path in (selected, target):
            raise AssertionError('untrusted file opened')
        return original_open(path, *args, **kwargs)
    def guarded_read_text(path, *args, **kwargs):
        if path in (selected, target):
            raise AssertionError('untrusted file opened')
        return original_read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(Path, 'read_text', guarded_read_text)
    with pytest.raises(TemplateSectionError):
        resolve_template(wiki, config, registry, 'context_instructions')
