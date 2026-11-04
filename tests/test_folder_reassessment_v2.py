"""End-to-end source reassessment uses only synthetic Git content."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_folder_policy_v2 import project, put, git, commit, proposal_v2
from wiki_core.folder_policy_v2 import load_folder_policy_v2
from wiki_core.folder_reassessment_v2 import FolderReassessmentError, reassess_folder_source_v2


def setup_flow(project):
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-')
    git(project, 'merge', '--ff-only', 'wiki/folder-task')
    put(project, 'a/report.md', '''---
information_requirements:
  - target: a/source.md
    fields: [field:amount, field:unreported]
    temporal: current
    max_age_days: 30
---
Independent interpretation
''')
    put(project, 'a/second.md', '''---
information_requirements:
  - target: a/source.md
    fields: ['*']
    temporal: current
    max_age_days: 30
---
Another interpretation
''')
    put(project, 'a/source.md', '---\namount: 5\nunreported: 1\n---\nChanged unselected body\n')
    commit(project)
    report = {'target': 'a/report.md', 'section': None, 'field': 'amount', 'packet': packet, 'result': result}
    return report


def run(project, report):
    policy = load_folder_policy_v2(project, 'HEAD')
    return reassess_folder_source_v2(project, policy, folder='a', source='a/source.md', reports=[report],
                                    candidates=['a/report.md', 'a/second.md'])


def test_inventory_and_reports_show_changed_unchanged_and_missing_without_writes(project):
    report = setup_flow(project)
    before = git(project, 'status', '--porcelain')
    interpretation = (project / 'a/report.md').read_text()
    unchanged = run(project, report)
    rows = {(x['target'], x['selector']): x for x in unchanged['consumers']}
    assert rows['a/report.md', 'field:amount']['state'] == 'verification_pending'
    assert rows['a/report.md', 'field:amount']['impact']['source_state'] == 'unchanged'
    assert rows['a/report.md', 'field:unreported']['state'] == 'declared_without_report'
    assert rows['a/second.md', '*']['state'] == 'declared_without_report'
    put(project, 'a/source.md', '---\namount: 9\nunreported: 1\n---\nChanged unselected body\n')
    commit(project)
    changed = run(project, report)
    first = changed['consumers'][0]
    assert first['state'] == 'review_pending'
    assert first['impact']['consumed_revision'] == report['packet']['policy_revision']
    assert first['impact']['verification'] == 'reported_not_independently_verified'
    assert changed['coverage'] == 'selected_authorized_consumer_paths_and_explicit_reports_only'
    assert (project / 'a/report.md').read_text() == interpretation
    assert git(project, 'status', '--porcelain') == before


def test_unmatched_duplicate_and_invented_reports_fail_closed(project):
    report = setup_flow(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    args = dict(folder='a', source='a/source.md', candidates=['a/report.md'])
    with pytest.raises(FolderReassessmentError, match='duplicate'):
        reassess_folder_source_v2(project, policy, reports=[report, report], **args)
    wrong = {**report, 'field': 'unreported'}
    with pytest.raises(ValueError):
        reassess_folder_source_v2(project, policy, reports=[wrong], **args)
    with pytest.raises(FolderReassessmentError, match='does not match'):
        reassess_folder_source_v2(project, policy, reports=[{**report, 'target': 'a/second.md'}], **args)


def test_declared_revision_and_use_must_match_report(project):
    report = setup_flow(project)
    report_path = project / 'a/report.md'
    original = report_path.read_text()
    report_path.write_text(original.replace('    temporal: current',
                           "    consumed_revision: '" + '0' * 40 + "'\n    temporal: current", 1))
    commit(project)
    with pytest.raises(FolderReassessmentError, match='declared source constraints'):
        run(project, report)
    report_path.write_text(original.replace('    temporal: current',
                           '    use: another_use\n    temporal: current', 1))
    commit(project)
    with pytest.raises(FolderReassessmentError, match='declared source constraints'):
        run(project, report)


def test_multiple_reported_consumers_of_same_source_are_independent(project):
    from wiki_core.folder_packet_v2 import build_folder_packet_v2
    first = setup_flow(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    packet = build_folder_packet_v2(project, policy, 'a', 20000, index_path='a/index.md',
                    content_revision='HEAD', task_id='second', goal='review source', output='a/second.md',
                    integrator='independent', evidence=[{'path': 'a/source.md', 'producer_folder': 'a',
                    'reason': 'source', 'use': 'interpret', 'classification': 'synthetic', 'field': 'unreported'}])
    put(project, 'a/second.md', '''---
information_requirements:
  - target: a/source.md
    fields: [field:unreported]
    temporal: current
    max_age_days: 30
---
Second independent interpretation
''')
    commit(project)
    result = {'schema_version': 'wiki.folder-task-result/v2', 'status': 'completed', 'task_id': packet['task_id'],
              'context_id': packet['context_id'], 'packet_digest': packet['packet_digest'],
              'observed': [{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                            'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
              'changes': [{'path': 'a/second.md', 'action': 'modified'}]}
    second = {'target': 'a/second.md', 'section': None, 'field': 'unreported', 'packet': packet, 'result': result}
    put(project, 'a/source.md', '---\namount: 9\nunreported: 1\n---\nBody\n'); commit(project)
    policy = load_folder_policy_v2(project, 'HEAD')
    out = reassess_folder_source_v2(project, policy, folder='a', source='a/source.md',
                    reports=[first, second], candidates=['a/report.md', 'a/second.md'])
    states = {(r['target'], r['selector']): r['state'] for r in out['consumers']}
    assert states['a/report.md', 'field:amount'] == 'review_pending'
    assert states['a/second.md', 'field:unreported'] == 'verification_pending'
    assert states['a/report.md', 'field:unreported'] == 'declared_without_report'


def test_deny_fails_before_reading_historical_source(project, monkeypatch):
    import yaml
    from wiki_core.repository_reader import RepositoryReader
    report = setup_flow(project)
    path = project / 'wiki-context-controls.yaml'
    controls = yaml.safe_load(path.read_text())
    controls['controls']['a']['policy']['deny'] = {'read': ['a/source.md']}
    path.write_text(yaml.safe_dump(controls)); commit(project)
    original = RepositoryReader.read
    def guarded(self, path, *args, **kwargs):
        if path == 'a/source.md':
            raise AssertionError('denied source body opened')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(ValueError):
        run(project, report)


def test_historical_and_unsupported_selectors_remain_explicit(project):
    setup_flow(project)
    put(project, 'a/second.md', '''---
information_requirements:
  - target: a/source.md
    fields: [body]
    temporal: current
    max_age_days: 30
  - target: a/source.md
    fields: ['*']
    temporal: historical
    max_age_days: 30
---
Independent historical interpretation
''')
    commit(project)
    p = load_folder_policy_v2(project, 'HEAD')
    out = reassess_folder_source_v2(project, p, folder='a', source='a/source.md', reports=[], candidates=['a/second.md'])
    assert [row['state'] for row in out['consumers']] == ['unsupported_selector', 'historical_review_required']


def test_real_cli_reports_missing_consumption_in_selected_scope(project):
    setup_flow(project)
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_reassessment_v2.py'
    call = subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
                           '--folder', 'a', '--source', 'a/source.md', '--candidate', 'a/second.md'],
                          text=True, capture_output=True)
    assert call.returncode == 0, call.stderr
    assert json.loads(call.stdout)['consumers'][0]['state'] == 'declared_without_report'


def test_real_cli_reassesses_explicit_report_after_source_update(project, tmp_path):
    report = setup_flow(project)
    put(project, 'a/source.md', '---\namount: 9\nunreported: 1\n---\nSource update\n'); commit(project)
    reports = tmp_path.parent / (tmp_path.name + '-reports.json')
    reports.write_text(json.dumps([report]))
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_reassessment_v2.py'
    call = subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
                           '--folder', 'a', '--source', 'a/source.md', '--candidate', 'a/report.md',
                           '--reports', str(reports)], text=True, capture_output=True)
    assert call.returncode == 0, call.stderr
    rows = json.loads(call.stdout)['consumers']
    assert rows[0]['state'] == 'review_pending'
    assert rows[1]['state'] == 'declared_without_report'
    assert 'Independent interpretation' not in call.stdout


def test_missing_source_blocks_without_false_empty_inventory(project):
    report = setup_flow(project)
    (project / 'a/source.md').unlink(); commit(project)
    out = run(project, report)
    rows = {(row['target'], row['selector']): row for row in out['consumers']}
    assert rows['a/report.md', 'field:amount']['state'] == 'blocked_missing_source'
    assert rows['a/report.md', 'field:unreported']['state'] == 'declared_without_report'
    assert rows['a/second.md', '*']['state'] == 'declared_without_report'


def test_missing_denied_source_is_not_opened_or_disclosed(project, monkeypatch):
    import yaml
    from wiki_core.repository_reader import RepositoryReader
    report = setup_flow(project)
    (project / 'a/source.md').unlink()
    config = project / 'wiki-context-controls.yaml'
    controls = yaml.safe_load(config.read_text())
    controls['controls']['a']['policy']['deny'] = {'read': ['a/source.md']}
    config.write_text(yaml.safe_dump(controls)); commit(project)
    original = RepositoryReader.read
    def guarded(self, path, *args, **kwargs):
        if path == 'a/source.md':
            pytest.fail('denied source body opened')
        return original(self, path, *args, **kwargs)
    monkeypatch.setattr(RepositoryReader, 'read', guarded)
    with pytest.raises(ValueError):
        run(project, report)
