import traceback

import pytest

from tests.test_context_dynamic_selection import (AUDIT_CONTEXT, audit_collection, collection, repo,
    git, commit, folder_policy, folder_build_packet)  # noqa: F401
from tests.test_repository_reader import repository, commit as reader_commit  # noqa: F401
from wiki_core import repository_reader
from wiki_core.context_integration import IntegrationError, preflight
from wiki_core.repository_reader import RepositoryReader, RepositoryReadError


BAD = '---\nupdated_at: 2026-01-01T00:00:00+99:00\nnote: synthetic-private-sentinel\n---\nOld\n'
BAD_BOOL = '---\nflag: !!bool synthetic-private-sentinel\n---\nOld\n'
BAD_TIMESTAMP = '---\nupdated_at: !!timestamp synthetic-private-sentinel\n---\nOld\n'
BAD_INT = '---\ncount: !!int ""\n---\nOld\n'
BAD_FLOAT = '---\namount: !!float ""\n---\nOld\n'
GOOD = '---\nupdated_at: 2026-01-01\n---\nOld\n'


def assert_opaque(error):
    rendered = ''.join(traceback.format_exception(error))
    assert 'synthetic-private-sentinel' not in rendered
    assert 'datetime.timedelta(days=4' not in rendered


@pytest.mark.parametrize('bad', [BAD, BAD_BOOL, BAD_TIMESTAMP, BAD_INT, BAD_FLOAT])
def test_reader_returns_opaque_error_for_invalid_frontmatter(repository, bad):
    (repository / 'memories/policy.md').write_text(bad)
    reader_commit(repository)
    with pytest.raises(RepositoryReadError, match='frontmatter unavailable') as error:
        RepositoryReader(repository).read('memories/policy.md')
    assert_opaque(error.value)


def test_reader_wraps_parser_overflow(repository, monkeypatch):
    def overflow(_text):
        raise OverflowError('synthetic-private-sentinel')
    monkeypatch.setattr(repository_reader, 'parse_frontmatter', overflow)
    with pytest.raises(RepositoryReadError, match='frontmatter unavailable') as error:
        RepositoryReader(repository).read('memories/policy.md')
    assert_opaque(error.value)


@pytest.mark.parametrize('case,bad', [
    ('bad_base', BAD), ('bad_proposal', BAD), ('valid', GOOD),
    ('bad_base', BAD_BOOL), ('bad_proposal', BAD_BOOL),
    ('bad_base', BAD_TIMESTAMP), ('bad_proposal', BAD_TIMESTAMP),
    ('bad_base', BAD_INT), ('bad_proposal', BAD_FLOAT),
])
def test_preflight_handles_invalid_base_and_proposal_opaquely(audit_collection, case, bad):
    root = audit_collection
    target = 'finance/costs/result.md'
    (root / target).write_text(bad if case == 'bad_base' else GOOD)
    commit(root)
    base = git(root, 'rev-parse', 'HEAD')
    policy = folder_policy(root)
    packet = folder_build_packet(root, policy, AUDIT_CONTEXT, base, [], 50000,
        task_id='date', goal='synthetic', output=target, integrator='reviewer')
    git(root, 'checkout', '-qb', 'wiki/date-test')
    (root / target).write_text(bad if case == 'bad_proposal' else GOOD.replace('Old', 'New'))
    git(root, 'add', target); git(root, 'commit', '-qm', 'proposal')
    head = git(root, 'rev-parse', 'HEAD')
    result = {'schema_version': 'wiki.task-result/v1', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'status': 'completed', 'blockers': [],
              'changes': [{'path': target, 'action': 'modified'}],
              'read_coverage': {'observed_refs': packet['declared_read_set'], 'observed_queries': [],
                                'missing': packet['coverage']['missing']}}
    args = dict(context_id=AUDIT_CONTEXT, base=base, head=head, branch='wiki/date-test',
                packet=packet, result=result)
    if case == 'valid':
        assert preflight(root, policy, **args)['state'] == 'independent_review_required'
    else:
        with pytest.raises(IntegrationError) as error:
            preflight(root, policy, **args)
        assert_opaque(error.value)
