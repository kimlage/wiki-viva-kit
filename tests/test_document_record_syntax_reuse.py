"""Memoized syntax preserves bytes, ambiguity and independent caller state."""
import wiki_core.document_records as records


def test_identical_text_reuses_syntax_but_never_caller_mutations(monkeypatch):
    records._section_spans_cached.cache_clear()
    records._reference_definitions_cached.cache_clear()
    original = records.MarkdownIt.parse
    calls = []
    def parse(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(records.MarkdownIt, "parse", parse)
    text = "# Log\r\n\r\n## Kept\r\n\r\nA [source][s].\r\n\r\n[s]: source.md\r\n"
    before = records.sections(text)
    refs = records.reference_definitions(text)
    count = len(calls)
    spans = records.section_spans(text)[1]
    spans.clear()
    before[1].clear()
    refs.clear()
    again = records.sections(text)
    assert again[1]["Kept"][2].endswith("[s]: source.md\r\n")
    assert records.reference_definitions(text) == {"S": ("source.md", "")}
    assert len(calls) == count
    changed = text.replace("A [source]", "A changed [source]")
    assert records.sections(changed)[1] != again[1]
    assert len(calls) == count + 1


def test_reused_syntax_keeps_repeated_heading_ambiguity():
    text = "# Log\n\n## Repeated\n\nFirst.\n\n## Repeated\n\nSecond.\n"
    for _ in range(2):
        assert "Repeated" not in records.sections(text)[1]
        assert [row[0] for row in records.section_spans(text)[1]] == ["Repeated", "Repeated"]
    assert records.sections(text.replace("## Repeated", "## Unique", 1))[1]["Unique"][2].endswith("First.\n\n")
