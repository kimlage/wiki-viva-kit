from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "wiki_page_graph.py"
    spec = importlib.util.spec_from_file_location("wiki_page_graph_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stub_clean_graph(monkeypatch: pytest.MonkeyPatch, module) -> None:
    config = SimpleNamespace(audit={}, paths={"memory_root": "memories"})
    monkeypatch.setattr(module, "load_config", lambda _root: config)
    monkeypatch.setattr(module, "build_page_graph", lambda _root, _config: object())
    monkeypatch.setattr(module, "orphan_pages", lambda _graph, _exempt: ())
    monkeypatch.setattr(module, "unreachable_pages", lambda _graph, _root: ())


def test_resolve_base_resolves_only_the_explicit_ref_to_full_commit_sha(
    monkeypatch,
) -> None:
    module = _load_script()
    full_sha = "a" * 40
    calls: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        calls.append(args)
        return full_sha

    monkeypatch.setattr(module, "run_git", fake_git)

    assert module.resolve_base("review/base") == full_sha
    assert calls == [["rev-parse", "--verify", "--quiet", "review/base^{commit}"]]


def test_changed_paths_include_committed_worktree_untracked_and_deleted_paths(
    monkeypatch,
) -> None:
    module = _load_script()
    full_sha = "b" * 40
    responses = {
        (
            "diff",
            "--name-only",
            "-z",
            f"{full_sha}..HEAD",
            "--",
        ): "memories/committed.md\0memories/deleted.md\0",
        ("diff", "--name-only", "-z", "--"): "memories/unstaged.md\0",
        (
            "diff",
            "--cached",
            "--name-only",
            "-z",
            "--",
        ): "memories/staged.md\0",
        (
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
        ): "memories/untracked.md\0",
        (
            "diff",
            "--name-only",
            "--diff-filter=D",
            "-z",
            f"{full_sha}..HEAD",
            "--",
        ): "memories/deleted.md\0",
        (
            "diff",
            "--name-only",
            "--diff-filter=D",
            "-z",
            "--",
        ): "",
        (
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=D",
            "-z",
            "--",
        ): "",
    }
    calls: list[list[str]] = []

    def fake_git(args: list[str]) -> str:
        calls.append(args)
        return responses[tuple(args)]

    monkeypatch.setattr(module, "run_git", fake_git)

    changes = module.collect_git_changes(full_sha)
    assert set(changes.paths) == {
        "memories/committed.md",
        "memories/deleted.md",
        "memories/staged.md",
        "memories/unstaged.md",
        "memories/untracked.md",
    }
    assert changes.deleted_paths == frozenset({"memories/deleted.md"})
    assert changes.untracked_paths == frozenset({"memories/untracked.md"})
    assert [
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
    ] in calls


def test_impact_requires_explicit_base_before_loading_the_wiki(
    monkeypatch, capsys
) -> None:
    module = _load_script()
    monkeypatch.setattr(sys, "argv", ["wiki_page_graph.py", "--impact"])
    monkeypatch.setattr(
        module,
        "load_config",
        lambda _root: pytest.fail(
            "configuration must not load without an explicit impact base"
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    assert "base=null, base_sha=null" in capsys.readouterr().err


def test_impact_rejects_an_unresolvable_explicit_base(monkeypatch, capsys) -> None:
    module = _load_script()
    monkeypatch.setattr(
        sys,
        "argv",
        ["wiki_page_graph.py", "--impact", "--base", "missing/ref"],
    )
    monkeypatch.setattr(module, "resolve_base", lambda _base: None)

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    diagnostic = capsys.readouterr().err
    assert "base='missing/ref'" in diagnostic
    assert "base_sha=null" in diagnostic


def test_impact_output_records_requested_base_and_resolved_sha(
    monkeypatch, capsys
) -> None:
    module = _load_script()
    _stub_clean_graph(monkeypatch, module)
    full_sha = "c" * 40
    monkeypatch.setattr(
        sys,
        "argv",
        ["wiki_page_graph.py", "--impact", "--base", "review/base"],
    )
    monkeypatch.setattr(module, "resolve_base", lambda _base: full_sha)
    monkeypatch.setattr(module, "base_is_ancestor", lambda _base_sha: True)
    changes = module.GitChanges(
        paths=frozenset({"memories/projects/x.md"}),
        deleted_paths=frozenset(),
        untracked_paths=frozenset({"memories/projects/x.md"}),
    )
    monkeypatch.setattr(module, "collect_git_changes", lambda _base_sha: changes)
    base_graph = SimpleNamespace(memory_root="memories", nodes={})
    monkeypatch.setattr(module, "build_page_graph_at_commit", lambda _sha: base_graph)

    monkeypatch.setattr(
        module,
        "compute_impact",
        lambda _graph, _changed, exempt_types, base_graph: SimpleNamespace(
            changed_pages=("memories/projects/x.md",),
            removed_pages=(),
            affected_pages=("memories/index.md",),
            references={"memories/index.md": ("memories/projects/x.md",)},
        ),
    )

    assert module.main() == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["schema_version"] == "wiki_page_graph_impact.v1"
    assert payload["base"] == "review/base"
    assert payload["base_sha"] == full_sha
    assert payload["head_sha"] == full_sha
    assert payload["git_changes"]["untracked_paths"] == [
        "memories/projects/x.md"
    ]
    assert payload["summary"] == {"error_count": 0, "warning_count": 0}
    assert "wiki_page_graph:" not in output


def test_impact_rejects_a_resolved_base_that_is_not_an_ancestor(
    monkeypatch, capsys
) -> None:
    module = _load_script()
    full_sha = "d" * 40
    monkeypatch.setattr(
        sys,
        "argv",
        ["wiki_page_graph.py", "--impact", "--base", "diverged/review"],
    )
    monkeypatch.setattr(module, "resolve_base", lambda _base: full_sha)
    monkeypatch.setattr(module, "base_is_ancestor", lambda _base_sha: False)
    monkeypatch.setattr(
        module,
        "collect_git_changes",
        lambda _base: pytest.fail("a divergent base must fail before diff collection"),
    )

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    diagnostic = capsys.readouterr().err
    assert f"base_sha={full_sha}" in diagnostic
    assert "not an ancestor of HEAD" in diagnostic


def test_impact_fails_closed_when_a_git_read_fails(monkeypatch, capsys) -> None:
    module = _load_script()
    full_sha = "e" * 40
    monkeypatch.setattr(
        sys,
        "argv",
        ["wiki_page_graph.py", "--impact", "--base", full_sha],
    )
    monkeypatch.setattr(module, "resolve_base", lambda _base: full_sha)
    monkeypatch.setattr(module, "base_is_ancestor", lambda _base_sha: True)

    def fail_git(_base_sha: str):
        raise module.GitCommandError(
            ["diff", "--name-only"],
            returncode=128,
            detail="synthetic object read failure",
        )

    monkeypatch.setattr(module, "collect_git_changes", fail_git)

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    diagnostic = capsys.readouterr().err
    assert "could not collect exact-base impact evidence" in diagnostic
    assert "synthetic object read failure" in diagnostic


def test_full_graph_mode_does_not_resolve_or_require_a_base(
    monkeypatch, capsys
) -> None:
    module = _load_script()
    _stub_clean_graph(monkeypatch, module)
    monkeypatch.setattr(sys, "argv", ["wiki_page_graph.py", "--check"])
    monkeypatch.setattr(
        module,
        "resolve_base",
        lambda _base: pytest.fail("full graph mode must not resolve an impact base"),
    )

    assert module.main() == 0
    assert "wiki_page_graph: 0 error(s), 0 warning(s)" in capsys.readouterr().out


def test_ci_wires_the_exact_event_base_sha_into_the_page_graph_gate() -> None:
    workflow_text = (ROOT / ".github/workflows/wiki.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    page_graph_command = "python3 scripts/wiki_page_graph.py --check"
    step = next(
        item
        for item in workflow["jobs"]["audit-and-test"]["steps"]
        if item.get("name") == "Exact-base page graph and impact evidence"
    )
    run_lines = [line.strip() for line in step["run"].splitlines() if line.strip()]

    assert "github.event.pull_request.base.sha" in workflow_text
    assert "github.event.before" in workflow_text
    assert run_lines == [
        'test -n "$BASE_SHA"',
        f'{page_graph_command} --impact --base "$BASE_SHA" '
        "> /tmp/wiki-page-graph-impact.json",
        "python3 -m json.tool /tmp/wiki-page-graph-impact.json",
    ]
