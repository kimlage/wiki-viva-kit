from __future__ import annotations

from pathlib import Path

from wiki_core.source_state import read_state, stream_cursor, write_stream_cursor


def test_empty_state_for_new_source(tmp_path: Path) -> None:
    state = read_state(tmp_path, "source-slack-fin")
    assert state["streams"] == {}
    assert stream_cursor(state, "#financeiro") == {}


def test_write_then_read_a_cursor(tmp_path: Path) -> None:
    write_stream_cursor(
        tmp_path, "source-slack-fin", "#financeiro",
        cursor="2026-06-28T00:00:00Z", last_unit="msg-9812", updated_at="2026-07-03",
    )
    state = read_state(tmp_path, "source-slack-fin")
    cursor = stream_cursor(state, "#financeiro")
    assert cursor["cursor"] == "2026-06-28T00:00:00Z"
    assert cursor["last_unit"] == "msg-9812"


def test_second_stream_does_not_clobber_the_first(tmp_path: Path) -> None:
    write_stream_cursor(tmp_path, "s", "a", cursor="c1")
    write_stream_cursor(tmp_path, "s", "b", cursor="c2")
    state = read_state(tmp_path, "s")
    assert stream_cursor(state, "a")["cursor"] == "c1"
    assert stream_cursor(state, "b")["cursor"] == "c2"


def test_corrupt_state_degrades_to_full_reread(tmp_path: Path) -> None:
    (tmp_path / "s.json").write_text("{ not valid json", encoding="utf-8")
    # A lost/corrupt cursor is safe (manifest dedup) — never raises.
    assert read_state(tmp_path, "s")["streams"] == {}


def test_source_id_with_slash_is_filename_safe(tmp_path: Path) -> None:
    write_stream_cursor(tmp_path, "sources/slack/fin", "a", cursor="c")
    assert stream_cursor(read_state(tmp_path, "sources/slack/fin"), "a")["cursor"] == "c"
