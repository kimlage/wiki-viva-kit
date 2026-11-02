"""Opt-in, additive page-section templates; never authority or page migration."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
import re

from markdown_it import MarkdownIt
import yaml

from wiki_core.content_sections import parse_sections, SectionError
from wiki_core.frontmatter import parse_frontmatter

SCHEMA_VERSION = 'wiki_template_sections.v1'
ROLES = frozenset({'facts', 'decision', 'constraints', 'evidence', 'uncertainty', 'next_step'})
MAX_BYTES = 65_536
MAX_DEPTH = 8
MAX_SECTIONS = 64
_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.:-]*\Z')


class TemplateSectionError(ValueError):
    pass


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise TemplateSectionError('duplicate or non-string YAML key')
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _path(root: Path, ref: str) -> Path:
    if (not isinstance(ref, str) or not ref or '\\' in ref
            or PurePosixPath(ref).is_absolute()
            or any(part in {'', '.', '..'} for part in ref.split('/'))):
        raise TemplateSectionError('contract path must be repository relative without traversal')
    current = root.resolve()
    for part in ref.split('/'):
        current = current / part
        if current.is_symlink():
            raise TemplateSectionError('contract symlinks are forbidden')
    try:
        current.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise TemplateSectionError('contract escaped repository') from exc
    return current


def read_template_file(root: Path, ref: str) -> str:
    """Bounded, confined text read for opt-in skeletons and overlays."""
    with _path(root, ref).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise TemplateSectionError('template byte budget exceeded')
    try:
        return raw.decode('utf-8')
    except UnicodeError as exc:
        raise TemplateSectionError('template must be UTF-8') from exc


def _section(value: object, *, extension: bool = False) -> dict:
    allowed = {'id', 'role', 'required', 'title'} | ({'slot'} if extension else set())
    if not isinstance(value, dict) or set(value) != allowed:
        raise TemplateSectionError('section must declare exactly id, role, required, title and extension slot')
    if not isinstance(value['id'], str) or not _ID.fullmatch(value['id']):
        raise TemplateSectionError('invalid stable section id')
    if not isinstance(value['role'], str) or value['role'] not in ROLES:
        raise TemplateSectionError('unknown section role')
    if type(value['required']) is not bool:
        raise TemplateSectionError('required must be boolean')
    if (not isinstance(value['title'], str) or not value['title'].strip()
            or any(char in value['title'] for char in '\r\n<>')):
        raise TemplateSectionError('section title must be one plain line')
    if extension and not isinstance(value['slot'], str):
        raise TemplateSectionError('extension slot must be a string')
    return deepcopy(value)


def load_section_contract(root: Path, ref: str) -> dict:
    """Load bounded root-relative YAML inheritance with immutable parent sections."""
    budget = [0]

    def load(path_ref: str, ancestors: tuple[str, ...]) -> dict:
        if path_ref in ancestors:
            raise TemplateSectionError('contract inheritance cycle')
        if len(ancestors) >= MAX_DEPTH:
            raise TemplateSectionError('contract inheritance depth exceeded')
        path = _path(root, path_ref)
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        budget[0] += len(raw)
        if budget[0] > MAX_BYTES:
            raise TemplateSectionError('contract byte budget exceeded')
        try:
            doc = yaml.load(raw.decode('utf-8'), Loader=_UniqueLoader)
        except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
            raise TemplateSectionError('invalid contract YAML') from exc
        common = {'schema_version', 'template_id', 'template_version'}
        if not isinstance(doc, dict) or doc.get('schema_version') != SCHEMA_VERSION:
            raise TemplateSectionError('invalid contract schema_version')
        for key in ('template_id', 'template_version'):
            if not isinstance(doc.get(key), str) or not doc[key].strip():
                raise TemplateSectionError(f'{key} must be a nonempty string')
        if 'extends' in doc:
            if set(doc) != common | {'extends', 'add_sections'}:
                raise TemplateSectionError('derived contract may only add sections')
            parent = load(doc['extends'], (*ancestors, path_ref))
            sections = deepcopy(parent['sections'])
            slots = list(parent['allowed_slots'])
            additions = doc['add_sections']
            if not isinstance(additions, list):
                raise TemplateSectionError('add_sections must be a list')
            # Keep declaration order for multiple additions to the same slot.
            after_tail = {}
            for value in additions:
                section = _section(value, extension=True)
                slot = section.pop('slot')
                if slot not in slots:
                    raise TemplateSectionError('extension uses unauthorized slot')
                if section['id'] in {item['id'] for item in sections}:
                    raise TemplateSectionError('inherited or duplicate section id cannot be redefined')
                side, target = slot.split(':', 1)
                anchor = after_tail.get(slot, target) if side == 'after' else target
                index = next(i for i, item in enumerate(sections) if item['id'] == anchor)
                sections.insert(index + (side == 'after'), section)
                after_tail[slot] = section['id']
        else:
            if set(doc) != common | {'sections', 'allowed_slots'}:
                raise TemplateSectionError('base contract must declare sections and allowed_slots')
            if not isinstance(doc['sections'], list) or not doc['sections']:
                raise TemplateSectionError('sections must be a nonempty list')
            sections = [_section(value) for value in doc['sections']]
            slots = doc['allowed_slots']
            if not isinstance(slots, list) or not all(isinstance(s, str) for s in slots):
                raise TemplateSectionError('allowed_slots must be a string list')
            if len(set(slots)) != len(slots):
                raise TemplateSectionError('duplicate slot')
        ids = [item['id'] for item in sections]
        if len(ids) > MAX_SECTIONS or len(set(ids)) != len(ids):
            raise TemplateSectionError('duplicate section id or section limit exceeded')
        for slot in slots:
            side, sep, target = slot.partition(':')
            if not sep or side not in {'before', 'after'} or target not in ids:
                raise TemplateSectionError('slot must address an existing section')
        return {key: doc[key] for key in common} | {'sections': sections, 'allowed_slots': slots}

    return load(ref, ())


def compose_sections(text: str, contract: dict) -> str:
    """Append empty, addressable slots to a template skeleton without rewriting it."""
    if parse_sections(text):
        raise TemplateSectionError('opt-in skeleton must not already declare sections')
    return text.rstrip() + '\n\n' + '\n\n'.join(
        f'<!-- wiki:section id={section["id"]} version=1 -->\n## {section["title"]}\n'
        for section in contract['sections']) + '\n'


def selectors_for_roles(contract: dict, roles: list[str]) -> list[str]:
    """Return selectors, never read content or grant permission to a reader."""
    if any(role not in ROLES for role in roles):
        raise TemplateSectionError('unknown requested role')
    return [f'section:{section["id"]}' for section in contract['sections'] if section['role'] in roles]


def _has_text(text: str) -> bool:
    values = []
    previous = None
    for token in MarkdownIt('commonmark').parse(text):
        if token.type in {'fence', 'code_block'} or (token.type == 'inline' and previous != 'heading_open'):
            values.append(token.content.strip())
        previous = token.type
    value = ' '.join(values).strip()
    value = re.sub(r'\{\{.*?\}\}|\b(?:TODO|TBD|FIXME)\b|\[\s*\]', '', value, flags=re.I)
    return bool(re.search(r'\w', value))


def validate_section_page(text: str, contract: dict, *, mode: str = 'structure') -> list[str]:
    """`filled` checks non-placeholder text, never semantic quality or actual reading."""
    if mode not in {'structure', 'filled'}:
        raise TemplateSectionError('mode must be structure or filled')
    fm, _ = parse_frontmatter(text)
    errors = []
    for key in ('template_id', 'template_version'):
        if str(fm.get(key, '')) != contract[key]:
            errors.append(f'{key} mismatch; explicit review/migration required')
    try:
        sections = parse_sections(text)
    except SectionError as exc:
        return [*errors, str(exc)]
    expected = {section['id']: section for section in contract['sections']}
    for section in contract['sections']:
        found = sections.get(section['id'])
        if found is None:
            if section['required']:
                errors.append(f'missing required section: {section["id"]}')
        elif mode == 'filled' and section['required'] and not _has_text(found.text):
            errors.append(f'empty or placeholder required section: {section["id"]}')
    for section_id in sections.keys() - expected.keys():
        errors.append(f'undeclared section: {section_id}')
    actual_order = [key for key in sections if key in expected]
    if actual_order != [item['id'] for item in contract['sections'] if item['id'] in sections]:
        errors.append('section order differs from contract')
    return errors
