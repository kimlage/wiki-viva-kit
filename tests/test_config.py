"""Tests for the hardened config parser (findings 0,1,2 of the critical review).

The config drives the honesty gates; common YAML shapes must not silently disable
verification. No network, no writes outside tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki_core.config import _as_bool, _parse_contexts, load_config


def _write(tmp_path: Path, body: str) -> Path:
    (tmp_path / "wiki.config.yaml").write_text(body, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Finding 2 — inline comment corrupted the value (language became 'pt  # ...')
# ---------------------------------------------------------------------------


def test_inline_comment_is_stripped(tmp_path):
    cfg = load_config(_write(tmp_path, "repo_id: r\nlanguage: pt  # idioma do projeto\n"))
    assert cfg.language == "pt"


def test_hash_inside_quotes_is_preserved(tmp_path):
    cfg = load_config(_write(tmp_path, 'repo_id: r\nlanguage: en\nowner_label: "a # b"\n'))
    assert cfg.owner_label == "a # b"


# ---------------------------------------------------------------------------
# Finding 1 — non-lowercase/quoted boolean silently became True
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["false", "False", "FALSE", "no", "off", '"false"'])
def test_bool_false_forms(tmp_path, value):
    cfg = load_config(
        _write(tmp_path, f"repo_id: r\nlanguage: en\nprivate_sensitive_allowed: {value}\n")
    )
    assert cfg.private_sensitive_allowed is False


@pytest.mark.parametrize("value", ["true", "True", "yes", "on"])
def test_bool_true_forms(tmp_path, value):
    cfg = load_config(
        _write(tmp_path, f"repo_id: r\nlanguage: en\nprivate_sensitive_allowed: {value}\n")
    )
    assert cfg.private_sensitive_allowed is True


def test_as_bool_raises_on_garbage():
    with pytest.raises(ValueError):
        _as_bool("maybe", field_name="x")


# ---------------------------------------------------------------------------
# Finding 0 — YAML list for contexts became ('{}',)
# ---------------------------------------------------------------------------


def test_contexts_yaml_list_indented(tmp_path):
    cfg = load_config(
        _write(tmp_path, "repo_id: r\nlanguage: en\ncontexts:\n  - financeiro\n  - documentos\n")
    )
    assert cfg.contexts == ("financeiro", "documentos")


def test_contexts_yaml_list_same_level(tmp_path):
    cfg = load_config(
        _write(tmp_path, "repo_id: r\nlanguage: en\ncontexts:\n- financeiro\n- documentos\n")
    )
    assert cfg.contexts == ("financeiro", "documentos")


def test_contexts_comma_separated_still_works(tmp_path):
    cfg = load_config(
        _write(tmp_path, "repo_id: r\nlanguage: en\ncontexts: financeiro, documentos\n")
    )
    assert cfg.contexts == ("financeiro", "documentos")


def test_contexts_rejects_invalid_slug(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, "repo_id: r\nlanguage: en\ncontexts: ok, BAD_SLUG\n"))


def test_parse_contexts_rejects_empty_dict_artifact():
    # '{}' was the symptom of the old discarded-list bug.
    with pytest.raises(ValueError):
        _parse_contexts("{}")


# ---------------------------------------------------------------------------
# Language validation fails loud
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["PT", "portugues!", "e", "x" * 9])
def test_language_invalid_raises(tmp_path, bad):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, f"repo_id: r\nlanguage: {bad}\n"))


# ---------------------------------------------------------------------------
# Nested maps remain intact
# ---------------------------------------------------------------------------


def test_nested_maps_intact(tmp_path):
    body = (
        "repo_id: r\nlanguage: en\n"
        "paths:\n  memory_root: mem\n  raw_root: raw\n"
        "llm:\n  chunk_target_tokens: 1200\n  prompt_versions:\n    context_deep_read: v1\n"
    )
    cfg = load_config(_write(tmp_path, body))
    assert cfg.paths["memory_root"] == "mem"
    assert cfg.paths["raw_root"] == "raw"
    assert cfg.llm["chunk_target_tokens"] == 1200
    assert cfg.llm["prompt_versions"]["context_deep_read"] == "v1"
