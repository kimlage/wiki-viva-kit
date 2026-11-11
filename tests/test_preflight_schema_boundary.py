"""Synthetic checks of the existing entrypoint, not host-I/O qualification."""
from pathlib import Path

import pytest

from tests.test_context_flow import repo, folder_requirements_proposal, folder_requirements_setup
from wiki_core.coordination_context import ProtectedCoordinationError, prepare_preflight


@pytest.fixture
def proposal(repo):
    binding = folder_requirements_setup(repo)
    _, base, head, packet, result = folder_requirements_proposal(repo, binding)
    payload = {'context_id': 'finance/costs', 'approved_revision': base,
               'base': base, 'head': head, 'branch': 'wiki/costs-task-1',
               'packet': packet, 'result': result}
    return repo, binding, payload


@pytest.mark.parametrize('case', ['missing_binding', 'unbound_context'])
def test_unavailable_entrypoint_refuses_before_schema(proposal, monkeypatch, case):
    root, binding, payload = proposal
    original = Path.read_text

    def watch_schema(path, *args, **kwargs):
        if path.name.startswith('wiki-task-result-') and path.name.endswith('.schema.json'):
            pytest.fail('schema opened before the context entrypoint refused')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', watch_schema)
    if case == 'missing_binding':
        binding = None
    else:
        payload = {**payload, 'context_id': 'not-bound'}
    with pytest.raises(ProtectedCoordinationError) as error:
        prepare_preflight(root, binding, payload)
    assert error.value.code in {'coordination_not_available', 'coordination_not_authorized'}


def test_bound_entrypoint_reads_validator_schema_as_technical_dependency(proposal, monkeypatch):
    root, binding, payload = proposal
    original = Path.read_text
    schemas = []

    def watch_schema(path, *args, **kwargs):
        if path.name.startswith('wiki-task-result-') and path.name.endswith('.schema.json'):
            schemas.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', watch_schema)
    result = prepare_preflight(root, binding, payload)
    assert result['preflight']['state'] == 'independent_review_required'
    assert schemas == ['wiki-task-result-v1.schema.json']
