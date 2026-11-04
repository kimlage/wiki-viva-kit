"""CLI uses explicit artifacts and opaque errors for historical v2 queries."""
import json
import subprocess
import sys
from pathlib import Path

from tests.test_folder_query_history_v2 import project, created

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/wiki_folder_query_history_v2.py'


def test_explicit_cli_keeps_review_pending(project, tmp_path):
    packet, result, integrated = created(project)
    packet_file = tmp_path.parent / (tmp_path.name + '-packet.json')
    result_file = tmp_path.parent / (tmp_path.name + '-result.json')
    packet_file.write_text(json.dumps(packet)); result_file.write_text(json.dumps(result))
    process = subprocess.run([sys.executable, str(SCRIPT), '--repo', str(project),
        '--approved-revision', integrated, '--integrated-revision', integrated,
        '--packet', str(packet_file), '--result', str(result_file)], capture_output=True, text=True, check=True)
    output = json.loads(process.stdout)
    assert output['state'] == 'review_pending'
    assert output['read_verification'] == 'reported_not_independently_verified'


def test_cli_does_not_echo_sensitive_arguments_or_missing_paths():
    secret = 'https://example.invalid/?X-Goog-Signature=synthetic'
    bad_args = subprocess.run([sys.executable, str(SCRIPT), '--unknown', secret], capture_output=True, text=True)
    assert bad_args.returncode == 2 and secret not in bad_args.stdout + bad_args.stderr
    missing = subprocess.run([sys.executable, str(SCRIPT), '--repo', secret, '--approved-revision', 'HEAD',
        '--integrated-revision', '0' * 40, '--packet', secret, '--result', secret], capture_output=True, text=True)
    assert missing.returncode != 0 and secret not in missing.stdout + missing.stderr
