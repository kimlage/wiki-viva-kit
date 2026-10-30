"""Run fail-closed JavaScript admission tests without OpenClaw or model calls."""
import subprocess
from pathlib import Path

def test_node_mission_guard_contract():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','tests/node/openclaw-mission-guard.test.mjs','tests/node/openclaw-native-capture.test.mjs'],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr
