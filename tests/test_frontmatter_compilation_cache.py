"""Compilation reuse must not hide current bytes or share mutable page data."""
from concurrent.futures import ThreadPoolExecutor

import pytest

import wiki_core.frontmatter as frontmatter


def document(value="first", body="body"):
    return f"---\npage_id: synthetic\ntitle: {value}\nitems: [one, two]\n---\n{body}\n"


@pytest.fixture
def loads(monkeypatch):
    calls = []
    original = frontmatter.yaml.safe_load

    def tracked(block):
        calls.append(block)
        return original(block)

    monkeypatch.setattr(frontmatter.yaml, "safe_load", tracked)
    return calls


def test_repeated_compilation_reads_parse_once_and_return_independent_maps(loads):
    with frontmatter.frontmatter_parsing_cache():
        first, _ = frontmatter.parse_frontmatter(document())
        first["items"].append("caller mutation")
        second, _ = frontmatter.parse_frontmatter(document())
        second["title"] = "different caller"
        third, _ = frontmatter.parse_frontmatter(document())
    assert len(loads) == 1
    assert second["items"] == ["one", "two"]
    assert third == {"page_id": "synthetic", "title": "first", "items": ["one", "two"]}


def test_reads_current_file_bytes_and_body_even_inside_one_compilation(tmp_path, loads):
    page = tmp_path / "synthetic.md"
    page.write_text(document())
    with frontmatter.frontmatter_parsing_cache():
        frontmatter.parse_frontmatter(page)
        page.write_text(document(body="new body"))
        values, body = frontmatter.parse_frontmatter(page)
        assert values["title"] == "first"
        assert body == "new body\n"
        page.write_text(document(value="changed", body="new body"))
        values, body = frontmatter.parse_frontmatter(page)
    assert values["title"] == "changed"
    assert body == "new body\n"
    assert len(loads) == 2


def test_cache_discarded_after_failure_and_outside_compilation(loads):
    with pytest.raises(RuntimeError):
        with frontmatter.frontmatter_parsing_cache():
            frontmatter.parse_frontmatter(document())
            raise RuntimeError("synthetic compilation failed")
    frontmatter.parse_frontmatter(document())
    with frontmatter.frontmatter_parsing_cache():
        frontmatter.parse_frontmatter(document())
    assert len(loads) == 3


def test_nested_scopes_reuse_but_separate_threads_do_not_share_cache(loads):
    with frontmatter.frontmatter_parsing_cache():
        frontmatter.parse_frontmatter(document())
        with frontmatter.frontmatter_parsing_cache():
            frontmatter.parse_frontmatter(document())
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(frontmatter.parse_frontmatter, document()).result()[0]["title"] == "first"
    assert len(loads) == 2


@pytest.mark.parametrize("limit", ["_MAX_PARSE_CACHE_BYTES", "_MAX_PARSE_CACHE_ENTRIES"])
def test_cache_budget_falls_back_to_current_parsing(monkeypatch, loads, limit):
    monkeypatch.setattr(frontmatter, limit, 0)
    with frontmatter.frontmatter_parsing_cache():
        for _ in range(2):
            assert frontmatter.parse_frontmatter(document())[0]["title"] == "first"
    assert len(loads) == 2


def test_oversized_block_is_not_retained(monkeypatch, loads):
    monkeypatch.setattr(frontmatter, "_MAX_PARSE_CACHE_BLOCK_BYTES", 1)
    with frontmatter.frontmatter_parsing_cache():
        for _ in range(2):
            assert frontmatter.parse_frontmatter(document())[0]["title"] == "first"
    assert len(loads) == 2


def test_yaml_types_aliases_and_invalid_tags_preserve_safe_loader_semantics():
    valid = "---\nwhen: 2026-10-14\na: &values [1, true]\nb: *values\n---\nbody\n"
    invalid = "---\nx: !!python/object/apply:os.system [synthetic]\n---\nbody\n"
    expected = frontmatter.parse_frontmatter(valid)
    with frontmatter.frontmatter_parsing_cache():
        assert frontmatter.parse_frontmatter(valid) == expected
        values, body = frontmatter.parse_frontmatter(valid)
        assert values["a"] is values["b"]
        assert body == "body\n"
        assert frontmatter.parse_frontmatter(invalid) == ({}, "body\n")
