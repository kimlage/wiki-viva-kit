"""Run fail-closed JavaScript admission tests without OpenClaw or model calls."""
import subprocess
from pathlib import Path

def test_node_mission_guard_contract():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','tests/node/openclaw-mission-guard.test.mjs','tests/node/openclaw-native-capture.test.mjs','tests/node/openclaw-mission-rpc.test.mjs','tests/node/openclaw-client-pin.test.mjs','tests/node/openclaw-bootstrap.test.mjs'],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr


def test_real_native_sdk_capture_opt_in():
    """Optional pinned runtime proof; never starts a Gateway or model request."""
    import os
    import shutil
    import pytest
    if not os.environ.get('WIKI_TEST_OPENCLAW_CORE_ROOT'):
        pytest.skip('Pinned native OpenClaw package not supplied')
    root = Path(__file__).resolve().parents[1]
    node = os.environ.get('WIKI_TEST_OPENCLAW_NODE') or shutil.which('node')
    for case in ('absolute', 'bridge', 'preloaded', 'integrity', 'late'):
        result = subprocess.run(
            [node, 'tests/node/openclaw-native-sdk-integration.mjs', case],
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_real_native_route_custody_opt_in():
    """Real captured modules and async proxy; synthetic mission, no model call."""
    import os
    import shutil
    import pytest
    if not (os.environ.get('WIKI_TEST_OPENCLAW_CORE_ROOT') and os.environ.get('WIKI_TEST_OPENCLAW_PLUGIN_ROOT')):
        pytest.skip('Both pinned native packages not supplied')
    root = Path(__file__).resolve().parents[1]
    node = os.environ.get('WIKI_TEST_OPENCLAW_NODE') or shutil.which('node')
    result = subprocess.run([node, 'tests/node/openclaw-native-route-integration.mjs'],
                            cwd=root, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
