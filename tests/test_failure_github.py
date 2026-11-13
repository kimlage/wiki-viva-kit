import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from wiki_core.failure_github import ApprovedTemplate, GitHubIssueError, GitHubIssuePort
from wiki_core.failure_routing import IssueRef


def port():
    return GitHubIssuePort(route="kit", repository="synthetic/example", expected_login="operator",
                           expected_visibility="PUBLIC", templates={"fixture": ApprovedTemplate("Synthetic problem", "An approved synthetic issue body.")})


def stub(port, *, login="operator", visibility="PUBLIC", permission="WRITE", issues=None, view_state="OPEN"):
    seen = []
    def run(args):
        seen.append(args)
        if args[0] == "api":
            return login
        if args[:2] == ["repo", "view"]:
            return json.dumps({"nameWithOwner": "synthetic/example", "visibility": visibility, "viewerPermission": permission})
        if args[:2] == ["issue", "list"]:
            return json.dumps(issues if issues is not None else [])
        if args[:2] == ["issue", "view"]:
            return json.dumps({"number": int(args[2]), "state": view_state})
        if args[:2] == ["issue", "create"]:
            body = Path(args[args.index("--body-file") + 1])
            assert body.is_file()
            assert body.stat().st_mode & 0o077 == 0
            seen.append(body.read_text())
            return "https://example.invalid/issue/1"
        raise AssertionError(args)
    port._run = run
    return seen


def test_create_uses_only_approved_template_and_opaque_marker():
    p = port()
    seen = stub(p)
    marker = "a" * 32
    p.create("kit", "fixture", marker)
    assert "<!-- wiki-failure:" + marker + " -->" in seen[-1]
    assert seen[-1].startswith("An approved synthetic issue body.")
    assert seen[-2][:2] == ["issue", "create"]
    assert "--body-file" in seen[-2]
    assert not Path(seen[-2][seen[-2].index("--body-file") + 1]).exists()


def test_readback_matches_exact_marker_and_preserves_closed_state():
    marker = "b" * 32
    tag = "<!-- wiki-failure:" + marker + " -->"
    p = port()
    seen = stub(p, issues=[{"number": 7, "body": "fixture\n" + tag, "state": "OPEN"}, {"number": 8, "body": "unrelated", "state": "OPEN"}])
    assert p.find("kit", marker) == [IssueRef("7", marker)]
    search = next(args for args in seen if isinstance(args, list) and args[:2] == ["issue", "list"])
    assert search[search.index("--search") + 1] == marker + " in:body"
    stub(p, issues=[{"number": 7, "body": tag, "state": "CLOSED"}])
    assert p.find("kit", marker) == [IssueRef("7", marker, "closed")]


@pytest.mark.parametrize("change", [{"login": "other"}, {"visibility": "PRIVATE"}, {"permission": "READ"}])
def test_changed_identity_visibility_or_write_permission_blocks_creation(change):
    p = port()
    seen = stub(p, **change)
    with pytest.raises(GitHubIssueError, match="github_binding_refused"):
        p.create("kit", "fixture", "a" * 32)
    assert not any(isinstance(args, list) and args[:2] == ["issue", "create"] for args in seen)


def test_foreign_route_and_template_are_refused():
    p = port()
    seen = stub(p)
    with pytest.raises(GitHubIssueError, match="target_not_authorized"):
        p.get("foreign", "7")
    assert seen == []
    with pytest.raises(GitHubIssueError, match="template_not_authorized"):
        p.create("kit", "unknown", "a" * 32)
    assert not any(isinstance(args, list) and args[:2] == ["issue", "create"] for args in seen)


def test_existing_issue_requires_exact_number_and_reports_state():
    p = port()
    stub(p)
    assert p.get("kit", "7") == IssueRef("7", "")
    with pytest.raises(GitHubIssueError, match="issue_invalid"):
        p.get("kit", "7; other")
    assert p.verified_merge("kit", "7") is None
    stub(p, view_state="CLOSED")
    assert p.get("kit", "7") == IssueRef("7", "", "closed")


def test_sensitive_template_is_refused_before_provider_access():
    with pytest.raises(GitHubIssueError, match="template_not_eligible"):
        GitHubIssuePort(route="kit", repository="synthetic/example", expected_login="operator",
                        expected_visibility="PUBLIC", templates={"bad": ApprovedTemplate("Synthetic problem", "Contact someone@example.com")})


def test_cli_uses_fixed_argv_without_shell_or_provider_error_output(monkeypatch):
    p = port()
    def fake(argv, **kwargs):
        assert Path(argv[0]).is_absolute()
        assert kwargs.get("shell") is None
        assert argv[1:] == ["issue", "list"]
        return SimpleNamespace(returncode=1, stdout="", stderr="private provider diagnostic")
    monkeypatch.setattr("wiki_core.failure_github.subprocess.run", fake)
    with pytest.raises(GitHubIssueError, match="github_unavailable") as error:
        p._run(["issue", "list"])
    assert "private provider diagnostic" not in str(error.value)
