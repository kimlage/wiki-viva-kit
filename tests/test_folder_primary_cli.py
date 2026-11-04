"""The main context CLIs enter folders unless v1 is explicitly selected."""
import json
import subprocess
import sys
from pathlib import Path

from tests.test_folder_policy_v2 import project, put, git, commit, proposal_v2


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], text=True, capture_output=True)


def test_main_folder_cli_resolve_packet_and_preflight(project, tmp_path):
    put(project, 'a/source.md', 'Synthetic source\n'); commit(project)
    base = git(project, 'rev-parse', 'HEAD')
    common = ['--repo', project, '--approved-revision', base]
    resolved = run('wiki_context.py', *common, 'resolve', 'a', '--index', 'a/index.md')
    assert resolved.returncode == 0, resolved.stderr
    entry = json.loads(resolved.stdout)
    assert entry['active_context'] == 'a' and entry['index']['path'] == 'a/index.md'
    assert entry['policy_revision'] == base and entry['enforcement_claim'] == 'none'
    # A file request is separate from the Git-tracked wiki tree.
    request_file = tmp_path.parent / (tmp_path.name + '-folder-request.json')
    request_file.write_text(json.dumps({'max_bytes':20000, 'task_id':'synthetic', 'goal':'review',
        'output':'a/report.md', 'integrator':'independent', 'evidence':[{'path':'a/source.md',
        'producer_folder':'a', 'reason':'source', 'use':'interpret', 'classification':'internal'}]}))
    built = run('wiki_context.py', *common, 'pack', 'a', '--index', 'a/index.md',
                '--content-revision', base, '--request', request_file)
    assert built.returncode == 0, built.stderr
    packet = json.loads(built.stdout)
    assert packet['schema_version'] == 'wiki.folder-task-context/v2'
    assert packet['context_folder'] == 'a' and packet['index_path'] == 'a/index.md'
    git(project, 'checkout', '-qb', 'wiki/primary-cli')
    put(project, 'a/report.md', '---\npage_type: claim\n---\nSynthetic claim\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'synthetic proposal')
    head = git(project, 'rev-parse', 'HEAD')
    result = {'schema_version':'wiki.folder-task-result/v2', 'status':'completed',
        'task_id':packet['task_id'], 'context_id':packet['context_id'], 'packet_digest':packet['packet_digest'],
        'observed':[{'path': r['path'], 'kind': r['kind'], 'revision': r['revision'], 'sha256': r['sha256'],
                     'section': r.get('section'), 'field': r.get('field')} for r in packet['inputs']],
        'changes':[{'path':'a/report.md', 'action':'created'}]}
    packet_file = tmp_path.parent / (tmp_path.name + '-folder-packet.json'); packet_file.write_text(json.dumps(packet))
    result_file = tmp_path.parent / (tmp_path.name + '-folder-result.json'); result_file.write_text(json.dumps(result))
    options = [*common, 'preflight', '--folder', 'a', '--index', 'a/index.md', '--base', base,
               '--head', head, '--branch', 'wiki/primary-cli', '--packet', packet_file, '--result', result_file]
    checked = run('wiki_context_flow.py', *options)
    assert checked.returncode == 0, checked.stderr
    result_out = json.loads(checked.stdout)
    assert result_out['state'] == 'independent_review_required' and result_out['merge'] == 'not_performed'
    wrong_index = options.copy(); wrong_index[wrong_index.index('a/index.md')] = 'a/other.md'
    assert run('wiki_context_flow.py', *wrong_index).returncode != 0
    wrong_folder = options.copy(); wrong_folder[wrong_folder.index('a')] = 'a/aux/b'
    assert run('wiki_context_flow.py', *wrong_folder).returncode != 0


def test_folder_default_never_falls_back_to_legacy_or_guesses_index(project, tmp_path):
    sha = git(project, 'rev-parse', 'HEAD'); common = ['--repo', project, '--approved-revision', sha]
    assert run('wiki_context.py', *common, 'resolve', 'a').returncode != 0
    assert run('wiki_context.py', *common, '--manifest', 'context.yaml', 'resolve', 'a').returncode != 0
    assert run('wiki_context_flow.py', *common, 'revalidate', '--context', 'a', '--consumer', 'a/x.md').returncode != 0
    request = tmp_path.parent / (tmp_path.name + '-invalid-request.json')
    request.write_text(json.dumps({'max_bytes':10000,'task_id':'x','goal':'x','output':'a/x.md',
                                  'integrator':'x','evidence':[], 'omissions':[]}))
    assert run('wiki_context.py', *common, 'pack', 'a', '--index', 'a/index.md',
               '--content-revision', sha, '--request', request).returncode != 0
    request.write_text(json.dumps({'max_bytes':10000,'task_id':'x','goal':'x',
        'output':'a/aux/b/other.md','integrator':'x','evidence':[]}))
    denied = run('wiki_context.py', *common, 'pack', 'a', '--index', 'a/index.md',
                 '--content-revision', sha, '--request', request)
    assert denied.returncode != 0 and denied.stdout == ''


def test_v1_receipt_is_not_implicitly_converted(project, tmp_path):
    sha = git(project, 'rev-parse', 'HEAD')
    packet = tmp_path.parent / (tmp_path.name + '-legacy-packet.json')
    result = tmp_path.parent / (tmp_path.name + '-legacy-result.json')
    packet.write_text(json.dumps({'schema_version':'wiki.task-context/v1'})); result.write_text('{}')
    out = run('wiki_context_flow.py', '--repo', project, '--approved-revision', sha, 'preflight',
              '--folder', 'a', '--index', 'a/index.md', '--base', sha, '--head', sha,
              '--branch', 'wiki/x', '--packet', packet, '--result', result)
    assert out.returncode != 0 and json.loads(out.stderr)['reason'] == 'v1_packet_requires_migration'


def test_primary_preflight_refuses_diff_without_declared_output(project, tmp_path):
    _policy, base, _, packet, result = proposal_v2(project)
    git(project, 'rm', '-q', 'a/report.md')
    put(project, 'a/other.md', '---\npage_type: claim\n---\nSynthetic claim\n')
    git(project, 'add', '-A'); git(project, 'commit', '-qm', 'different output')
    result['changes'] = [{'path':'a/other.md', 'action':'created'}]
    pp = tmp_path.parent / (tmp_path.name + '-packet.json'); pp.write_text(json.dumps(packet))
    rp = tmp_path.parent / (tmp_path.name + '-result.json'); rp.write_text(json.dumps(result))
    out = run('wiki_context_flow.py', '--repo', project, '--approved-revision', base, 'preflight',
              '--folder', 'a', '--index', 'a/index.md', '--base', base, '--head', git(project, 'rev-parse', 'HEAD'),
              '--branch', 'wiki/folder-task', '--packet', pp, '--result', rp)
    assert out.returncode != 0 and json.loads(out.stderr)['reason'] == 'declared_output_change_required'
