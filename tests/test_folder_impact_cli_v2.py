"""Exercise the real opt-in impact CLI on a synthetic Git repository."""
import json
import subprocess
import sys
from pathlib import Path

from tests.test_folder_policy_v2 import project, put, git, commit, proposal_v2


def run_cli(project, tmp_path, packet, result):
    packet_path = tmp_path.parent / (tmp_path.name + '-packet.json')
    result_path = tmp_path.parent / (tmp_path.name + '-result.json')
    packet_path.write_text(json.dumps(packet), encoding='utf-8')
    result_path.write_text(json.dumps(result), encoding='utf-8')
    script = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_impact_v2.py'
    return subprocess.run([sys.executable, str(script), '--repo', str(project), '--approved-revision', 'HEAD',
                           '--packet', str(packet_path), '--result', str(result_path), '--target', 'a/report.md',
                           '--source', 'a/source.md', '--field', 'amount'], capture_output=True, text=True)


def test_impact_cli_detects_selected_change_without_writing(project, tmp_path):
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    interpretation = (project / 'a/report.md').read_text()
    put(project, 'a/source.md', '---\namount: 9\n---\nNew source\n'); commit(project)
    before = git(project, 'status', '--porcelain')
    call = run_cli(project, tmp_path, packet, result)
    assert call.returncode == 0, call.stderr
    output = json.loads(call.stdout)
    assert output['state'] == 'review_pending' and output['candidates'][0]['field'] == 'amount'
    assert output['candidates'][0]['verification'] == 'reported_not_independently_verified'
    assert (project / 'a/report.md').read_text() == interpretation
    assert git(project, 'status', '--porcelain') == before


def test_impact_cli_keeps_equal_source_pending_without_verified_consumption(project, tmp_path):
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    call = run_cli(project, tmp_path, packet, result)
    assert call.returncode == 0, call.stderr
    output = json.loads(call.stdout)
    assert output['state'] == 'verification_pending'
    assert output['candidates'][0]['source_state'] == 'unchanged'


def test_impact_cli_rejects_legacy_result_without_disclosure(project, tmp_path):
    _, _, _, packet, result = proposal_v2(project)
    git(project, 'checkout', '-q', '-'); git(project, 'merge', '--ff-only', 'wiki/folder-task')
    git(project, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    result['schema_version'] = 'wiki.task-result/v1'
    call = run_cli(project, tmp_path, packet, result)
    assert call.returncode != 0 and not call.stdout
    assert 'v1_result_requires_migration' in call.stderr
