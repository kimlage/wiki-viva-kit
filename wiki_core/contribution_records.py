"""Bounded documentary support for the existing one-action contribution port.

This derives hashes and the exact new receipt-backed log observation for a
known canonical action/log delta. It never reclassifies existing assertions,
refreshes old evidence, evaluates freshness or grants model-selected paths.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import tempfile
from pathlib import Path

from wiki_core.config import load_config
from wiki_core.document_records import artifact_paths, digest, project_records, sections, structured_digest
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


def support_path(root: Path, parent: str, *, require_worktree: bool = False) -> str | None:
    """Resolve eligibility from Git; local source checks are opt-in for writers."""
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
    result = subprocess.run(["git", "ls-tree", parent, "--", value], cwd=root, capture_output=True, text=True)
    if result.returncode or not result.stdout.startswith("100644 blob "):
        raise ValueError("record_support_requires_tracked_regular_file")
    if require_worktree:
        worktree_support_bytes(root, value)
    return value


def worktree_support_bytes(root: Path, path: str) -> bytes:
    """Use the existing bounded, handle-pinned regular-file reader and mode guard."""
    from wiki_core.source_integrity import SourceIntegrityError, _worktree_entry
    try:
        return _worktree_entry(root, "100644", path)
    except (SourceIntegrityError, OSError) as exc:
        raise ValueError("record_support_requires_local_regular_file") from exc


def worktree_support_matches(root: Path, path: str, expected: bytes) -> bool:
    """A local adoption mismatch does not invalidate immutable canonical Git."""
    try:
        return worktree_support_bytes(root, path) == expected
    except ValueError:
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("record_support_duplicate_json_key:" + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("record_support_nonfinite_json:" + value)


def _canonical_log_effect(documents: dict, final: dict, action: str, log: str, identity: dict | None):
    """Prove the new canonical effect, not the continuing truth of an old capture."""
    from wiki_core.action_transition import (_history, _parse_document, action_transition_diagnostics,
                                             contribution_log_text)
    from wiki_core.action_contribution import _review

    fields = {"material_sha256", "effect_key", "task_ref", "run_ref", "session_ref", "review"}
    try:
        if (not isinstance(identity, dict) or set(identity) != fields
                or not re.fullmatch(r"[0-9a-f]{64}", str(identity["material_sha256"]))):
            raise ValueError("missing exact contribution identity")
        before, _ = _parse_document(documents[action])
        after, _ = _parse_document(final["documents"][action])
        prior, history = _history(before), _history(after)
        if (len(history) <= len(prior) or history[:len(prior)] != prior
                or action_transition_diagnostics(documents[action], final["documents"][action])):
            raise ValueError("invalid canonical receipt extension")
        entry = history[-1]
        material = entry.get("contribution")
        if (entry.get("kind") != "body_integration" or not isinstance(material, dict)
                or any(material.get(k) != identity[k] for k in fields)
                or before.get("page_id") != identity["task_ref"]["action_id"]
                or any(isinstance(e.get("contribution"), dict)
                       and e["contribution"].get("effect_key") == identity["effect_key"] for e in prior)):
            raise ValueError("contribution identity does not match new receipt")
        _review(identity, identity["material_sha256"], identity["review"])
        annotations = {legacy: contribution_log_text(
            documents[log], action, log, identity["material_sha256"], entry["at"], legacy=legacy)
            for legacy in (False, True)}
        if final["documents"][log] not in annotations.values():
            raise ValueError("canonical log annotation does not match receipt")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("record_support_canonical_log_effect_unproved") from exc
    return {"entry": entry, "legacy": final["documents"][log] == annotations[True]}


def _append_canonical_record(contract: dict, documents: dict, final: dict,
                             action: str, log: str, proof: dict) -> str | None:
    """Derive only the freshly proved annotation; old assertions stay untouched.

    No incoming occurrence is reclassified or rehashed. The new H2 and its
    structured receipt evidence keep an earlier remainder byte-identical.
    """
    if proof["legacy"]:
        return  # Reconstruct retained pre-record proposals exactly as authored.
    entry = proof["entry"]
    material = entry["contribution"]["material_sha256"]
    heading = "[" + entry["at"][:10] + "] Reviewed action body " + material
    rid = "contribution-" + material
    declaration = next((d for d in contract["documents"] if d["path"] == log), None)
    if declaration is None:
        declaration = {"path": log, "records": []}
        contract["documents"].append(declaration)
        if contract["schema_version"] == "document_record.v2":
            contract["document_modes"][log] = "h2_v1"
    if contract.get("document_modes", {}).get(log, "h2_v1") != "h2_v1":
        raise ValueError("record_support_c3_required:canonical_log_document_mode")
    if any(r["id"] == rid or r.get("heading") == heading for r in declaration["records"]):
        raise ValueError("record_support_canonical_log_record_collision")
    old_body, old_sections = sections(documents[log])
    new_body, new_sections = sections(final["documents"][log])
    section = new_sections.get(heading)
    if heading in old_sections or section is None:
        raise ValueError("record_support_canonical_log_record_selector")
    old_eof = len(old_body.splitlines(keepends=True))
    # A selected previous final H2 owns the appended separator under v1 and is
    # already updated by the exact blank-only rule below. Otherwise the new
    # record owns those two blank lines, preserving the unselected remainder.
    previous_selected = any(old_sections.get(r.get("heading"), (None, None))[1] == old_eof
                            for r in declaration["records"])
    padding = 0 if previous_selected else 2
    start, end, _ = section
    lines = new_body.splitlines(keepends=True)
    content = "".join(lines[start - padding:end])
    artifact = {"origin": "current", "id": rid, "document": action,
                "field": "action_state_history", "match_key": "receipt_id",
                "match_value": entry["receipt_id"], "sha256": structured_digest(entry)}
    if any(a.get("origin") == "current" and a.get("id") == rid
           for a in contract.get("artifacts", [])):
        raise ValueError("record_support_canonical_log_evidence_collision")
    contract.setdefault("artifacts", []).append(artifact)
    declaration["records"].append({
        "id": rid, "heading": heading, "base_sha256": None,
        "current_sha256": digest(content), "leading_blank_lines": padding,
        "independent": True, "epistemic_status": "observation",
        "recorded_on": entry["at"][:10], "context_records": [],
        "current_evidence": [rid],
        "rationale": "Exact canonical annotation proved by its independent-review-bound "
                     "body-integration receipt. It records preparation of this material only; "
                     "it does not assert execution, served adoption or current historical facts.",
    })
    return rid


def _inherit_qualified_annotation_context(contract: dict, trace: list, log: str,
                                           record: str | None) -> None:
    """Reuse only explicitly qualified, hash-bound historical destination context.

    The projector validates the existing CURRENT event occurrence. This does
    not broaden its historical assertion or renew the source document; it
    records the parent author's separate qualification for the fixed new H2.
    """
    qualification = contract.get("canonical_log_annotation_context")
    if qualification is None or record is None:
        return
    if qualification["log_path"] != log:
        raise ValueError("record_support_context_requires_configured_log")
    source_bindings = {(item["origin"], item["edge_sha256"], item["consumer_record"]): item["binding"]
                       for item in trace if item.get("binding")}
    for source in qualification["bindings"]:
        key = ("current", source["edge_sha256"], source["consumer_record"])
        # Syntax, actual relation, source guard and absence of historical
        # evidence/effect fields were checked by the parent's projection.
        original = source_bindings[key]
        contract["bindings"].append({
            "origin": "current", "edge_sha256": original["edge_sha256"],
            "consumer_record": record, "role": "change_target",
            "prerequisite_document_sha256": original["prerequisite_document_sha256"],
            "rationale": source["rationale"],
        })


def derive_support(root: Path, parent: str, action: str, log: str, final: dict,
                   *, final_revision: str | None = None, contribution_identity: dict | None = None) -> tuple[str, bytes] | None:
    """Validate the original pair, derive the exact subset, validate final pair.

    Final graph must come from the isolated proposal or immutable candidate.
    Unqualified occurrence guards are never renewed. The new canonical log H2
    is isolated with its actual receipt evidence; old formats are reconstructed
    without retroactive records. A parent-authored effect qualification still
    requires the actual new canonical receipt/annotation.
    """
    from scripts.wiki_page_graph import project_memory_at_commit, run_git

    path = support_path(root, parent)
    if path is None:
        return None
    if final_revision:
        mode = subprocess.run(["git", "ls-tree", final_revision, "--", path],
                              cwd=root, capture_output=True, text=True)
        if mode.returncode or not mode.stdout.startswith("100644 blob "):
            raise ValueError("record_support_requires_tracked_regular_file")
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
    paths = artifact_paths(root, contract, check_worktree=False)
    for p in paths.values():
        for revision in {parent, final_revision} - {None}:
            mode = subprocess.run(["git", "ls-tree", revision, "--", p.relative_to(root).as_posix()],
                                  cwd=root, capture_output=True, text=True)
            if mode.returncode or not mode.stdout.startswith(("100644 blob ", "100755 blob ")):
                raise ValueError("record_support_artifact_requires_tracked_regular_file")
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
    proof = _canonical_log_effect(documents, final, action, log, contribution_identity)
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
    record = _append_canonical_record(result, documents, final, action, log, proof)
    _inherit_qualified_annotation_context(result, trace, log, record)
    from wiki_core.freshness_impact import REFERENCE
    qualified = []
    for item in trace:
        binding = item.get("binding")
        if not binding or "contribution_effect" not in binding:
            continue
        edge = item["before"]
        prerequisite = edge["target" if edge["type"] in REFERENCE else "source"]
        # The projector already validates v2/CURRENT/change_target/no-evidence.
        # Only the immutable policy can identify this exact canonical log.
        if prerequisite != log:
            raise ValueError("record_support_effect_requires_configured_log")
        consumer = item["raw"]["source" if edge["type"] in REFERENCE else "target"]
        if documents.get(consumer) != final["documents"].get(consumer):
            raise ValueError("record_support_effect_consumer_context_changed")
        qualified.append((binding["origin"], binding["edge_sha256"], binding.get("consumer_record", "document")))
    # Neither role names nor empty evidence infer an exemption. Only the
    # already approved exact occurrence can advance its one CURRENT hash.
    for item in trace:
        binding = item.get("binding")
        if item["origin"] != "current" or not binding:
            continue
        edge = item["before"]
        prerequisite = edge["target" if edge["type"] in REFERENCE else "source"]
        if prerequisite in {action, log} and binding.get("role", "consumption") != "consumption":
            key = (binding["origin"], binding["edge_sha256"], binding.get("consumer_record", "document"))
            if key in qualified:
                for updated in result["bindings"]:
                    if (updated.get("origin"), updated.get("edge_sha256"), updated.get("consumer_record", "document")) == key:
                        updated["prerequisite_document_sha256"] = digest(final["documents"][log])
                        break
                continue
            raise ValueError("record_support_c3_required:binding/" + item["edge_sha256"]
                             + "/prerequisite_document_sha256/evidence/rationale")
    try:
        project_records(final, base, changed | {action, log}, result, artifact_inputs=artifacts)
    except ValueError as exc:
        raise ValueError("record_support_c3_required:contract:" + str(exc)) from exc
    return path, (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
