"""The CI runner must execute the entire collection and fail on any failure."""
from pathlib import Path
import subprocess
import sys


RUNNER = Path(__file__).resolve().parents[1] / '.github/scripts/run_python_tests.py'


def test_parallel_runner_preserves_coverage_and_failure(tmp_path):
    tests = tmp_path / 'test_examples.py'
    tests.write_text('def test_first(): pass\ndef test_second(): pass\ndef test_third(): assert False\n')
    command = [sys.executable, str(RUNNER), '--workers', '2', tests.name]
    failed = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True)
    assert failed.returncode != 0
    assert 'Running 3 tests in 2 processes.' in failed.stdout
    assert 'test_third' in failed.stdout
    tests.write_text(tests.read_text().replace('assert False', 'pass'))
    passed = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert 'Running 3 tests in 2 processes.' in passed.stdout
