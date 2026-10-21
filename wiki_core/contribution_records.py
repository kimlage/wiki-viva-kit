"""Bounded documentary support for the existing one-action contribution port.

This derives hashes for a known canonical action/log delta. It does not author
semantic declarations, refresh evidence, evaluate freshness or grant model paths.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import tempfile
from pathlib import Path

from wiki_core.config import load_config
from wiki_core.document_records import artifact_paths, digest, project_records, sections
from wiki_core.freshness_impact import authored_graph


def _blob(root, revision, path):
    result = subprocess.run(["git", "show", f"{revision}:{path}"], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError("record_support_source_blob_unavailable")
    return result.stdout


def parent_policy(root: Path, parent: str):
    """Read only the immutable parent's policy, including the strict opt-in."""
    with tempfile.TemporaryDirectory(prefix="wiki-contribution-policy-") as directory:
        location = Path(directory)
        (location / "wiki.config.yaml").write_bytes(_blob(root, parent, "wiki.config.yaml"))
        config = load_config(location)
    enabled = config.approval.get("contribution_record_support", False)
    if type(enabled) is not bool:
        raise ValueError("invalid_contribution_record_support_policy")
    return config, enabled


def support_path(root: Path, parent: str) -> str | None:
    config, enabled = parent_policy(root, parent)
    if not enabled:
        return None
    value = config.audit.get("freshness_records")
    if not isinstance(value, str) or not value:
        raise ValueError("record_support_requires_configured_contract")
    path = Path(value)
    if (path.is_absolute() or path.as_posix() != value or ".." in path.parts
            or "\\" in value or any(ord(c) < 32 for c in value)
            or path.suffix != ".json" or value == "wiki.config.yaml"
            or any(p.startswith(".") or p.lower() in {"raw", "secrets", "credentials"} for p in path.parts)
            or any(path.is_relative_to(Path(str(config.paths[key])))
                   for key in ("memory_root", "raw_root", "derived_root"))):
        raise ValueError("record_support_path_not_eligible")
    target = root / path
    if (target.resolve() != root.resolve() / path or not target.is_file()
            or target.is_symlink() or target.stat().st_mode & 0o111):
        raise ValueError("record_support_requires_local_regular_file")
    result = subprocess.run(["git", "ls-tree", parent, "--", value], cwd=root, capture_output=True, text=True)
    if result.returncode or not result.stdout.startswith("100644 blob "):
        raise ValueError("record_support_requires_tracked_regular_file")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("record_support_duplicate_json_key:" + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("record_support_nonfinite_json:" + value)


def derive_support(root: Path, parent: str, action: str, log: str, final: dict,
                   *, final_revision: str | None = None) -> tuple[str, bytes] | None:
    """Validate the original pair, derive the exact subset, validate final pair.

    Final graph must come from the isolated proposal or immutable candidate.
    Occurrence guards are never renewed, even if their role says navigation.
    """
    from scripts.wiki_page_graph import project_memory_at_commit, run_git

    path = support_path(root, parent)
    if path is None:
        return None
    config, _ = parent_policy(root, parent)
    contract = json.loads(_blob(root, parent, path), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    base_ref = config.audit.get("freshness_base")
    if not isinstance(base_ref, str) or not re.fullmatch(r"[0-9a-f]{40}", base_ref):
        raise ValueError("record_support_requires_pinned_base")
    base_sha = run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], root=root).strip()
    run_git(["merge-base", "--is-ancestor", base_sha, parent], root=root)
    base = project_memory_at_commit(base_sha, authored_graph, root=root)
    old = project_memory_at_commit(parent, authored_graph, root=root)
    if old["errors"] or base["errors"] or final["errors"]:
        raise ValueError("record_support_graph_errors")
    paths = artifact_paths(root, contract)
    artifacts = {key: _blob(root, parent, p.relative_to(root).as_posix()) for key, p in paths.items()}
    if final_revision and any(_blob(root, final_revision, p.relative_to(root).as_posix()) != artifacts[key]
                              for key, p in paths.items()):
        raise ValueError("record_support_artifact_changed")
    changed = set(run_git(["diff", "--name-only", base_sha, parent], root=root).splitlines())
    trace = []
    project_records(old, base, changed, contract, artifact_inputs=artifacts, review_trace=trace)
    documents = old["documents"]
    if (set(final["documents"]) != set(documents)
            or {p for p in documents if documents[p] != final["documents"][p]} != {action, log}):
        raise ValueError("record_support_requires_exact_action_log_delta")
    result = copy.deepcopy(contract)
    for name in (action, log):
        result["current_documents_sha256"][name] = digest(final["documents"][name])
    for index, declaration in enumerate(result["documents"]):
        name = declaration["path"]
        if name not in {action, log}:
            continue
        if result.get("document_modes", {}).get(name, "h2_v1") != "h2_v1":
            raise ValueError(f"record_support_c3_required:documents/{index}/document_mode")
        old_body, old_sections = sections(documents[name])
        new_body, new_sections = sections(final["documents"][name])
        for number, record in enumerate(declaration["records"]):
            heading = record["heading"]
            before, after = old_sections.get(heading), new_sections.get(heading)
            if before == after:
                continue
            # Compare selected bytes, including the declared leading blanks.
            padding = record.get("leading_blank_lines", 0)
            def selected(body, section):
                if section is None:
                    return None
                return "".join(body.splitlines(keepends=True)[section[0] - padding:section[1]])
            old_content, new_content = selected(old_body, before), selected(new_body, after)
            if old_content == new_content:
                continue
            pointer = f"documents/{index}/records/{number}/current_sha256"
            if (name != log or before is None or after is None
                    or before[1] != len(old_body.splitlines(keepends=True))
                    or new_content != old_content + "\n\n"
                    or record.get("current_sha256") != digest(old_content)):
                raise ValueError("record_support_c3_required:" + pointer)
            record["current_sha256"] = digest(new_content)
    # A role name/empty evidence list cannot establish timeless identity. Keep
    # every binding literal; point at any affected guard instead of laundering it.
    from wiki_core.freshness_impact import REFERENCE
    for item in trace:
        binding = item.get("binding")
        if item["origin"] != "current" or not binding:
            continue
        edge = item["before"]
        prerequisite = edge["target" if edge["type"] in REFERENCE else "source"]
        if prerequisite in {action, log} and binding.get("role", "consumption") != "consumption":
            raise ValueError("record_support_c3_required:binding/" + item["edge_sha256"]
                             + "/prerequisite_document_sha256/evidence/rationale")
    try:
        project_records(final, base, changed | {action, log}, result, artifact_inputs=artifacts)
    except ValueError as exc:
        raise ValueError("record_support_c3_required:contract:" + str(exc)) from exc
    return path, (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
