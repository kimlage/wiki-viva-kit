"""Pinned links to published Git blobs; never a local file-serving capability."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

from wiki_core.web.git_ops import _repository_web_url, _run_git


@lru_cache(maxsize=4)
def _blob_links(root: str, head: str, base: str) -> dict[str, str]:
    code, output, _ = _run_git(Path(root), ["ls-tree", "-rz", "--full-tree", head])
    if code:
        return {}
    paths = {}
    for entry in output.split("\0"):
        metadata, separator, path = entry.partition("\t")
        fields = metadata.split()
        # Symlinks, submodules and directories do not grant file access.
        if separator and len(fields) == 3 and fields[0] in {"100644", "100755"} and fields[1] == "blob":
            paths[path] = f"{base}/blob/{head}/{quote(path, safe='/')}"
    return paths


def published_blob_links(root: Path, git_state: dict[str, Any]) -> dict[str, str]:
    """Resolve only the snapshot's approved, remotely tracked Git revision.

    No network request is made. The repository host still enforces access when
    the operator follows the link; a URL grants no new account permission.
    """
    head = str(git_state.get("head") or "")
    base = _repository_web_url(str(git_state.get("repository_url") or ""))
    if (
        git_state.get("available") is not True
        or git_state.get("worktree", {}).get("clean") is not True
        or git_state.get("proposal", {}).get("human_gate_state") != "approved"
        or not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", head)
        or git_state.get("published_head") is not True or not base
    ):
        return {}
    return _blob_links(str(root.resolve()), head, base)
