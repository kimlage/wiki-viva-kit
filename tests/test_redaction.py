from __future__ import annotations

from wiki_core.web.commands import SECRET_VALUE_RE


def _redact(text: str) -> str:
    return SECRET_VALUE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def test_redacts_key_equals_value() -> None:
    out = _redact("OPENAI_API_KEY=sk-test1234567890secret")
    assert "sk-test1234567890secret" not in out
    assert "[REDACTED]" in out


def test_redacts_json_quoted_secret() -> None:
    # The exact shape `codex exec --json` emits.
    out = _redact('{"openai_api_key": "sk-json0987654321secret"}')
    assert "sk-json0987654321secret" not in out
    assert "[REDACTED]" in out


def test_redacts_bearer_and_access_token() -> None:
    assert "abc.def.ghi" not in _redact("authorization: Bearer abc.def.ghi")
    assert "rt_zzz" not in _redact('"refresh_token":"rt_zzz111222333"')
    assert "at_yyy" not in _redact("access_token = at_yyy444555666")


def test_keeps_the_key_visible() -> None:
    out = _redact('{"token": "sekritvalue123"}')
    assert "token" in out  # the key name stays; only the value is blanked
    assert "sekritvalue123" not in out


def test_leaves_ordinary_text_untouched() -> None:
    text = "the freshness radar shows 49 fresh pages and 0 stale"
    assert _redact(text) == text
