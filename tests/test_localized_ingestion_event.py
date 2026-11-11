from datetime import date
from pathlib import Path

import pytest

from scripts import wiki_audit as audit
from wiki_core.config import WikiConfig
from wiki_core.consolidate import build_event_markdown
from wiki_core.frontmatter import parse_frontmatter_flat
from wiki_core.page_types import load_page_type_registry, validate_shape

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('language', ['en', 'pt', 'es'])
@pytest.mark.parametrize('has_claim', [False, True])
def test_generated_event_shape_and_consolidation_claim_gate(tmp_path, monkeypatch, language, has_claim):
    config = WikiConfig(language=language)
    record = {'source_id': 'source-synthetic-example',
              'quadrants': {key: 'Synthetic observation.' for key in (
                  'interior_individual', 'exterior_individual', 'interior_collective', 'exterior_collective')},
              'claims': [{'claim': 'Synthetic candidate claim.'}] if has_claim else []}
    event_dir = tmp_path / 'memories/system/ingestion/events'
    event_dir.mkdir(parents=True)
    text = build_event_markdown(record, config=config, context='system', date=date(2026, 1, 1),
        source_ref='source-synthetic-example', root=tmp_path, event_dir=event_dir)
    shape = load_page_type_registry(ROOT).page_types['ingestion_event']
    assert not validate_shape(ROOT, 'memories/system/ingestion/events/synthetic.md',
                              parse_frontmatter_flat(text), text, shape)
    bullets = audit._claims_section_bullets(text)
    assert bool(bullets) is has_claim
    (event_dir / 'synthetic.md').write_text(text, encoding='utf-8')
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    audit.parse_frontmatter.cache_clear()
    errors, warnings = [], []
    audit.audit_consolidation(errors, warnings, config)
    assert any('candidate claims present but none linked' in error for error in errors) is has_claim


def test_localized_headings_do_not_waive_missing_or_other_page_requirements():
    shape = {'required_sections': ['Source', 'Quadrants']}
    text = '## Fonte\n\nSynthetic.\n'
    event_errors = validate_shape(ROOT, 'example.md', {'page_type': 'ingestion_event'}, text, shape)
    assert any('Quadrants' in error for error in event_errors)
    other_errors = validate_shape(ROOT, 'example.md', {'page_type': 'claim'}, text, shape)
    assert any('Source' in error for error in other_errors)


@pytest.mark.parametrize(('sections', 'text', 'missing'), [
    (['Source', 'Fonte'], '## Fonte\n', 'Source'),
    (['Quadrants', 'Cuadrantes'], '## Cuadrantes\n', 'Quadrants'),
])
def test_explicit_custom_shape_requirements_are_not_merged(sections, text, missing):
    errors = validate_shape(ROOT, 'example.md', {'page_type': 'ingestion_event'}, text,
                            {'required_sections': sections})
    assert any(f'`{missing}`' in error for error in errors)
