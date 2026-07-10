from __future__ import annotations

import subprocess
import sys
from pathlib import Path


KIT_ROOT = Path(__file__).resolve().parents[1]


def test_web_snapshot_cli_accepts_absolute_output_outside_repo(tmp_path: Path) -> None:
    out = tmp_path / "snapshot"
    result = subprocess.run(
        [
            sys.executable,
            str(KIT_ROOT / "scripts/wiki_web_snapshot.py"),
            "--out",
            str(out),
            "--clean",
        ],
        cwd=KIT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (out / "manifest.json").exists()
    assert str(out) in result.stdout
