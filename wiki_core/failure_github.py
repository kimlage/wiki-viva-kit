"""Restricted GitHub issue port. It grants no authority or worker execution."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Mapping

from wiki_core.detectors import scan_text
from wiki_core.failure_routing import IssueRef, UpstreamMerge
from wiki_core.repo_read import contains_access_secrets

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_MARKER = re.compile(r"[0-9a-f]{32}\Z")
_NUMBER = re.compile(r"[1-9][0-9]{0,15}\Z")


class GitHubIssueError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedTemplate:
    title: str
    body: str


def _approved_template(value: ApprovedTemplate) -> None:
    if (not isinstance(value, ApprovedTemplate) or not isinstance(value.title, str)
            or not isinstance(value.body, str) or not 1 <= len(value.title) <= 150
            or not 1 <= len(value.body) <= 16000 or "\n" in value.title
            or "\r" in value.title or "wiki-failure:" in value.body.lower()
            or contains_access_secrets((value.title, value.body))
            or any(f.category in {"secret", "pii", "entity"} for f in scan_text(value.title + "\n" + value.body))):
        raise GitHubIssueError("template_not_eligible")


class GitHubIssuePort:
    """One host-approved repository, account and fixed set of templates.

    The host must separately enforce live per-effect admission. Template scans
    are defense in depth, not proof of privacy or a substitute for review.
    """
    def __init__(self, *, route: str, repository: str, expected_login: str,
                 expected_visibility: str, templates: Mapping[str, ApprovedTemplate],
                 gh_binary: str = "gh") -> None:
        if (not isinstance(route, str) or not _NAME.fullmatch(route)
                or not isinstance(repository, str) or not _REPO.fullmatch(repository)
                or not isinstance(expected_login, str) or not _NAME.fullmatch(expected_login)
                or expected_visibility not in {"PUBLIC", "PRIVATE"}
                or not isinstance(templates, Mapping) or not templates or len(templates) > 64):
            raise GitHubIssueError("binding_invalid")
        checked = {}
        for name, template in templates.items():
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise GitHubIssueError("binding_invalid")
            _approved_template(template)
            checked[name] = template
        binary = shutil.which(gh_binary)
        if binary is None or not Path(binary).is_file():
            raise GitHubIssueError("github_cli_unavailable")
        self._binary = str(Path(binary).resolve(strict=True))
        self._route, self._repository = route, repository
        self._expected_login, self._visibility, self._templates = expected_login, expected_visibility, checked

    def _run(self, args: list[str]) -> str:
        try:
            result = subprocess.run([self._binary, *args], capture_output=True, text=True,
                                    encoding="utf-8", timeout=60, check=False)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            raise GitHubIssueError("github_unavailable") from None
        if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 4_000_000:
            raise GitHubIssueError("github_unavailable")
        return result.stdout

    def _binding(self, target: str, *, write: bool) -> None:
        if target != self._route:
            raise GitHubIssueError("target_not_authorized")
        try:
            login = self._run(["api", "--hostname", "github.com", "user", "--jq", ".login"]).strip()
            repo = json.loads(self._run(["repo", "view", "github.com/" + self._repository,
                                          "--json", "nameWithOwner,visibility,viewerPermission"]))
        except (ValueError, TypeError):
            raise GitHubIssueError("github_binding_unavailable") from None
        if (login.casefold() != self._expected_login.casefold() or not isinstance(repo, dict)
                or str(repo.get("nameWithOwner", "")).casefold() != self._repository.casefold()
                or repo.get("visibility") != self._visibility
                or (write and repo.get("viewerPermission") not in {"WRITE", "MAINTAIN", "ADMIN"})):
            raise GitHubIssueError("github_binding_refused")

    @staticmethod
    def _marker(marker: str) -> str:
        if not isinstance(marker, str) or not _MARKER.fullmatch(marker):
            raise GitHubIssueError("marker_invalid")
        return "<!-- wiki-failure:" + marker + " -->"

    def find(self, target: str, marker: str) -> list[IssueRef]:
        self._binding(target, write=False)
        tag = self._marker(marker)
        try:
            data = json.loads(self._run(["issue", "list", "--repo", "github.com/" + self._repository,
                                         "--state", "all", "--limit", "100", "--search", marker + " in:body",
                                         "--json", "number,body,state"]))
            if not isinstance(data, list) or len(data) >= 100:
                raise ValueError()
            result = []
            for item in data:
                if not isinstance(item, dict) or type(item.get("number")) is not int or not isinstance(item.get("body"), str):
                    raise ValueError()
                if tag in item["body"]:
                    if item.get("state") not in {"OPEN", "CLOSED"}:
                        raise ValueError()
                    result.append(IssueRef(str(item["number"]), marker, item["state"].lower()))
            return result
        except (ValueError, TypeError):
            raise GitHubIssueError("github_readback_invalid") from None

    def get(self, target: str, issue: str) -> IssueRef | None:
        self._binding(target, write=False)
        if not isinstance(issue, str) or not _NUMBER.fullmatch(issue):
            raise GitHubIssueError("issue_invalid")
        try:
            data = json.loads(self._run(["issue", "view", issue, "--repo", "github.com/" + self._repository,
                                         "--json", "number,state"]))
            if (not isinstance(data, dict) or type(data.get("number")) is not int
                    or str(data["number"]) != issue or data.get("state") not in {"OPEN", "CLOSED"}):
                raise ValueError()
            return IssueRef(issue, "", data["state"].lower())
        except (ValueError, TypeError):
            raise GitHubIssueError("github_readback_invalid") from None

    def create(self, target: str, template: str, marker: str) -> None:
        self._binding(target, write=True)
        if template not in self._templates:
            raise GitHubIssueError("template_not_authorized")
        approved = self._templates[template]
        tag = self._marker(marker)
        _approved_template(approved)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="wiki-issue-", suffix=".md") as file:
            file.write(approved.body + "\n\n" + tag + "\n")
            file.flush()
            self._run(["issue", "create", "--repo", "github.com/" + self._repository,
                       "--title", approved.title, "--body-file", file.name])

    def verified_merge(self, target: str, issue: str) -> UpstreamMerge | None:
        self._binding(target, write=False)
        # A linked issue does not prove a reviewed, CI-passing exact PR merge.
        return None
