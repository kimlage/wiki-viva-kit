"""Synthetic boundaries for stable protected-ingestion cache namespaces."""
import re

import pytest

from wiki_core.ingest.cache_partition import partition_component


def test_component_is_deterministic_and_opaque():
    component = partition_component('alpha', '.', 'alpha/source.txt')
    assert component == partition_component('alpha', '.', 'alpha/source.txt')
    assert re.fullmatch(r'by-source-v1/[0-9a-f]{64}', component)
    assert 'alpha' not in component


@pytest.mark.parametrize(('context', 'integrator', 'source'), [
    ('beta', '.', 'alpha/source.txt'),
    ('alpha', 'alpha', 'alpha/source.txt'),
    ('alpha', '.', 'alpha/other.txt'),
    ('.', '.', 'alpha/source.txt'),
])
def test_actor_and_source_select_distinct_namespaces(context, integrator, source):
    assert partition_component(context, integrator, source) != partition_component('alpha', '.', 'alpha/source.txt')


@pytest.mark.parametrize(('context', 'integrator', 'source'), [
    ('/alpha', '.', 'alpha/source.txt'),
    ('alpha/../beta', '.', 'alpha/source.txt'),
    ('alpha//beta', '.', 'alpha/source.txt'),
    ('alpha', '../root', 'alpha/source.txt'),
    ('alpha', '.', '/alpha/source.txt'),
    ('alpha', '.', 'alpha/../source.txt'),
    ('alpha', '.', 'alpha/./source.txt'),
    ('alpha', '.', 'alpha\\source.txt'),
    ('alpha', '.', 'alpha/.wiki-viva-protected/old.json'),
    ('alpha', '.', 'alpha/.env'),
    ('alpha', '.', ''),
])
def test_noncanonical_or_reserved_selectors_are_rejected(context, integrator, source):
    with pytest.raises(ValueError):
        partition_component(context, integrator, source)


def test_namespace_is_distinct_from_legacy_cache_directories():
    component = partition_component('.', '.', 'source.txt')
    assert component.split('/', 1)[0] == 'by-source-v1'
    assert component.split('/', 1)[0] not in {'source-manifests', 'source-text', 'chunks', 'llm-cache', 'extraction-events'}
