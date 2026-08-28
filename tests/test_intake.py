from __future__ import annotations

from pathlib import Path

from wiki_core.config import WikiConfig
from wiki_core.web.intake import intake_copy


def _config() -> WikiConfig:
    return WikiConfig(repo_id="intake-test", contexts=["financeiro", "system"], default_context="system")


def test_copies_external_file_into_raw(tmp_path: Path) -> None:
    external = tmp_path / "Downloads" / "extrato.pdf"
    external.parent.mkdir(parents=True)
    external.write_bytes(b"%PDF-1.4 fake statement bytes")
    result = intake_copy(tmp_path, _config(), str(external), "financeiro")
    assert result["ok"] is True
    assert result["path"] == "data/raw/financeiro/extrato.pdf"
    assert (tmp_path / "data/raw/financeiro/extrato.pdf").read_bytes() == b"%PDF-1.4 fake statement bytes"


def test_refuses_a_file_with_a_secret(tmp_path: Path) -> None:
    external = tmp_path / "creds.txt"
    external.write_text("OPENAI_API_KEY=sk-supersecret1234567890", encoding="utf-8")
    result = intake_copy(tmp_path, _config(), str(external), "system")
    assert result["ok"] is False
    assert result["reason"] == "secret_block"
    assert not (tmp_path / "data/raw/system/creds.txt").exists()


def test_unreadable_source_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """A file the scanner cannot read is refused (it cannot be proven
    secret-free), never waved through unscanned."""
    external = tmp_path / "locked.txt"
    external.write_text("harmless", encoding="utf-8")
    original_open = Path.open

    def fail_only_for_fixture(path: Path, *args, **kwargs):
        if path == external:
            raise PermissionError("synthetic unreadable source")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_only_for_fixture)
    result = intake_copy(tmp_path, _config(), str(external), "system")
    assert result["ok"] is False
    assert result["reason"] == "secret_block"
    assert "secret" in result["error"]
    assert not (tmp_path / "data/raw/system/locked.txt").exists()


def test_unknown_context_rejected(tmp_path: Path) -> None:
    external = tmp_path / "a.txt"
    external.write_text("hello", encoding="utf-8")
    assert intake_copy(tmp_path, _config(), str(external), "nope")["ok"] is False


def test_missing_source_rejected(tmp_path: Path) -> None:
    assert intake_copy(tmp_path, _config(), str(tmp_path / "ghost.txt"), "system")["ok"] is False


def test_no_clobber_suffixes_on_collision(tmp_path: Path) -> None:
    external = tmp_path / "note.md"
    external.write_text("first", encoding="utf-8")
    first = intake_copy(tmp_path, _config(), str(external), "system")
    external.write_text("second", encoding="utf-8")
    second = intake_copy(tmp_path, _config(), str(external), "system")
    assert first["path"] == "data/raw/system/note.md"
    assert second["path"] == "data/raw/system/note-2.md"
    # The original is preserved, not overwritten.
    assert (tmp_path / "data/raw/system/note.md").read_text() == "first"


def test_symlink_source_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert intake_copy(tmp_path, _config(), str(link), "system")["ok"] is False
