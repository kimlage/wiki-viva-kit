"""The exported kit version follows the primary documented release."""
from pathlib import Path
import re

from wiki_core import __version__


def test_export_matches_primary_release_notes():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    match = re.search(
        r"^Release and migration notes: \[Wiki Viva v(\d+\.\d+\.\d+)\]"
        r"\(docs/references/releases/wiki-viva-v\1\.md\)",
        readme,
        re.MULTILINE,
    )
    assert match, "README must identify the primary kit release and its notes"
    version = match.group(1)
    assert __version__ == version
    notes = root / "docs/references/releases" / f"wiki-viva-v{version}.md"
    assert notes.read_text(encoding="utf-8").startswith(f"# Wiki Viva v{version}\n")
