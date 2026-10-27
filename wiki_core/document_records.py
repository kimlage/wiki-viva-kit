"""Reviewed, hash-bound documentary records for freshness projection.

The declaration is authored semantic input, not a machine inference of
independence. Unknown consumers keep the whole-document dependency. This
module never edits a page, renews a date, or approves the declaration itself.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from functools import lru_cache

import yaml

from markdown_it import MarkdownIt

from wiki_core.frontmatter import FRONTMATTER_RE


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def substantive_digest(text: str, *, selector=None, claim=None) -> str:
    """Fingerprint actual assertions, never freshness/publication metadata.

    Selectors and claims here must come from the validated projector. Selected
    YAML fields lack document delimiters, so their meaning cannot be inferred
    by parsing the fragment as a complete Markdown document.
    """
    freshness_fields = {"updated_at", "stale_after_days", "refresh_cadence_days", "stale_exempt"}
    if (claim == "artifact_publication_date" or
            selector and selector.get("kind") == "frontmatter_field" and
            selector.get("path", [None])[0] in freshness_fields):
        return digest("")
    fm = FRONTMATTER_RE.match(text)
    if not fm:
        return digest(text)
    values = yaml.safe_load(fm.group(1)) or {}
    for field in freshness_fields:
        values.pop(field, None)
    return structured_digest(dict(frontmatter=values, body=text[fm.end():]))


def edge_digest(edge: dict) -> str:
    """Identity includes occurrence offset, direction, field and classification."""
    return digest(json.dumps(edge, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _section_spans_uncached(text: str):
    """All top-level H2 boundaries, including repeated titles.

    A lower-level heading is inside its H2; H1 ends it. Fenced/list headings
    cannot select a record. CRLF bytes are preserved in content hashes.
    """
    fm = FRONTMATTER_RE.match(text)
    body = text[fm.end():] if fm else text
    lines = body.splitlines(keepends=True)
    tokens = MarkdownIt("commonmark").parse(body)
    headings = [(t.map[0], int(t.tag[1:]), tokens[i + 1].content)
                for i, t in enumerate(tokens) if t.type == "heading_open" and t.level == 0]
    spans = []
    for i, (start, level, title) in enumerate(headings):
        if level != 2:
            continue
        end = next((line for line, depth, _ in headings[i + 1:] if depth <= 2), len(lines))
        spans.append((title, start, end, "".join(lines[start:end])))
    return body, tuple(spans)


def _cacheable(text: str) -> bool:
    try:
        return len(text) <= 1_048_576 and len(text.encode("utf-8")) <= 1_048_576
    except UnicodeEncodeError:
        return False


@lru_cache(maxsize=32)
def _section_spans_cached(text: str):
    return _section_spans_uncached(text)


def section_spans(text: str) -> tuple[str, list[tuple[str, int, int, str]]]:
    """Reuse only syntax of identical bytes; callers receive a fresh container.

    Per-process, bounded memoization does not cache qualifications, freshness,
    account access or authority. Changed text always has a separate key.
    """
    body, spans = (_section_spans_cached(text) if _cacheable(text)
                   else _section_spans_uncached(text))
    return body, list(spans)


def sections(text: str) -> tuple[str, dict[str, tuple[int, int, str]]]:
    """Only unique H2 titles can select a record; repeated sections still exist."""
    body, spans = section_spans(text)
    result = {}
    duplicates = set()
    for title, start, end, content in spans:
        if title in result:
            duplicates.add(title)
        result[title] = (start, end, content)
    for title in duplicates:
        del result[title]
    return body, result


def node_id(path: str, record: str) -> str:
    return f"{path}::record:{record}"


def _reference_definitions_uncached(text: str):
    """Definitions have document-wide rendering scope, unlike H2 assertions."""
    body, _ = sections(text)
    env = {}
    MarkdownIt("commonmark").parse(body, env)
    return tuple((label, (value["href"], value["title"]))
                 for label, value in env.get("references", {}).items())


@lru_cache(maxsize=32)
def _reference_definitions_cached(text: str):
    return _reference_definitions_uncached(text)


def reference_definitions(text: str) -> dict:
    """Return independent containers with the same document-wide scope."""
    return dict(_reference_definitions_cached(text) if _cacheable(text)
                else _reference_definitions_uncached(text))


def structured_digest(value) -> str:
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str))


def artifact_paths(root, contract, *, check_worktree=True):
    """Local captures; Git-only callers must validate immutable entry modes.

    Default filesystem checks remain required for working-tree audit inputs.
    """
    from pathlib import Path
    result = {}
    for item in contract.get("artifacts", []):
        if "path" not in item:
            continue
        rel = Path(item["path"])
        if rel.is_absolute() or rel.as_posix() != item["path"] or ".." in rel.parts:
            raise ValueError("record artifact requires a normalized repository-relative path")
        path = root / rel
        if check_worktree and (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())):
            raise ValueError("record artifact must be a local non-symlink file")
        result[(item["origin"], item["id"])] = path
    return result


def evidence_nodes(graphs, contract, artifact_inputs):
    """Verify bytes or a uniquely identified structured event in a frozen page.

    These nodes prove historical content, not current account/financial state.
    Structured events retain the source document's full snapshot identity.
    """
    evidence = {}
    for item in contract.get("artifacts", []):
        origin, aid = item["origin"], item["id"]
        key = (origin, aid)
        if origin not in graphs or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", aid) or key in evidence:
            raise ValueError("invalid/duplicate evidence identity")
        if ("path" in item) == ("document" in item):
            raise ValueError("evidence requires exactly one file or structured document selector")
        if "path" in item:
            data = artifact_inputs.get(key)
            if data is None or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("immutable evidence bytes missing or changed")
            source = dict(path=item["path"], sha256=item["sha256"])
        else:
            document = item["document"]
            text = graphs[origin]["documents"].get(document)
            fm = FRONTMATTER_RE.match(text or "")
            values = yaml.safe_load(fm.group(1)) if fm else {}
            entries = values.get(item["field"]) if isinstance(values, dict) else None
            matches = [v for v in entries if isinstance(v, dict)
                       and v.get(item["match_key"]) == item["match_value"]] if isinstance(entries, list) else []
            if len(matches) != 1 or structured_digest(matches[0]) != item["sha256"]:
                raise ValueError("structured evidence selector/hash missing or ambiguous")
            source = dict(document=document, document_sha256=digest(text),
                          field=item["field"], match_key=item["match_key"],
                          match_value=item["match_value"], sha256=item["sha256"])
        nid = f"evidence::{aid}:{item['sha256']}"
        if nid in graphs[origin]["nodes"]:
            raise ValueError("evidence node collision")
        graphs[origin]["nodes"][nid] = dict(immutable_evidence=True, evidence_source=source)
        graphs[origin].setdefault("verified_evidence_nodes", []).append(nid)
        evidence[key] = nid
    return evidence


def project_records(current: dict, base: dict, changed: set[str], contract: dict, *, artifact_inputs=None,
                    review_trace: list | None = None):
    """Validate and project an explicit documentary record declaration.

    A declaration binds BOTH full input snapshots. It is not a path filter:
    changed paths are still derived by the caller from the complete diff.
    Mixed deltas retain whole-page seeds. Records inherit page freshness unless
    an explicitly reviewed observation qualifies its own CURRENT record.
    """
    from wiki_core.freshness_impact import ASSOCIATION, REFERENCE, STRUCTURAL

    # Diagnostics observe this exact projection, never a second implementation
    # of inheritance or consumption. Publish only after all guards succeed.
    trace = [] if review_trace is not None else None

    version = contract.get("schema_version")
    if version not in {"document_record.v1", "document_record.v2"}:
        raise ValueError("unsupported document record contract")
    for origin, graph in (("base", base), ("current", current)):
        actual = {p: digest(text) for p, text in graph["documents"].items()}
        if contract.get(f"{origin}_documents_sha256") != actual:
            raise ValueError(f"{origin}: document snapshot does not match record contract")
    declarations = contract.get("documents")
    if not isinstance(declarations, list) or not declarations:
        raise ValueError("document record contract requires documents")
    modes = contract.get("document_modes", {}) if version == "document_record.v2" else {}
    if version == "document_record.v2":
        if (not isinstance(modes, dict) or set(modes) != {d["path"] for d in declarations}
                or any(m not in {"h2_v1", "explicit_view_v2"} for m in modes.values())):
            raise ValueError("v2 requires a complete explicit document_modes map")
    graphs = {"base": copy.deepcopy(base), "current": copy.deepcopy(current)}
    artifacts = evidence_nodes(graphs, contract, artifact_inputs or {})
    from wiki_core.document_view_selectors import verify_locator_changes
    locator_changes = verify_locator_changes(current, base, contract, artifact_inputs or {})
    if not set(locator_changes) <= set(changed):
        raise ValueError("locator declaration must describe an actual changed document")
    locator_ids = {v["id"] for v in locator_changes.values()}
    partitions = {"base": {}, "current": {}}
    declared = set()
    changes = set(changed)
    evidence = []
    for declaration in declarations:
        path = declaration["path"]
        if path in declared or path not in current["nodes"] or path not in base["nodes"]:
            raise ValueError("record pages must be unique and exist in both snapshots")
        declared.add(path)
        explicit_view = modes.get(path) == "explicit_view_v2"
        if version == "document_record.v2" and not explicit_view and ("envelope" in declaration or any(
                "selectors" in r for r in declaration.get("records", []))):
            raise ValueError("h2_v1 declarations must retain v1 selectors")
        records = declaration.get("records")
        if not isinstance(records, list) or not records:
            raise ValueError(f"{path}: empty records")
        envelope = declaration.get("envelope", []) if explicit_view else []
        if not isinstance(envelope, list):
            raise ValueError("explicit envelope must be a list")
        if explicit_view:
            if any("heading" in r or "leading_blank_lines" in r for r in records):
                raise ValueError("v2 records require explicit origin selectors")
            for slot in envelope:
                if (not slot.get("rationale", "").strip()
                        or not isinstance(slot.get("context_records"), list)
                        or slot.get("claim") not in {"artifact_publication_date", "declared_view_membership"}):
                    raise ValueError("envelope requires a reviewed claim and explicit contexts")
                if (set(slot.get("selectors", {})) != {"base", "current"}
                        or slot["selectors"]["base"] != slot["selectors"]["current"]):
                    raise ValueError("envelope selector/template must be identical in both origins")
                for selector in slot.get("selectors", {}).values():
                    if not isinstance(selector, dict):
                        raise ValueError("envelope selector cannot be absent")
                    kind = selector.get("kind")
                    if kind == "frontmatter_field":
                        required = {"artifact_publication_date": "canonical_iso_date",
                                    "declared_view_membership": "unique_string_sequence"}[slot["claim"]]
                        if slot.get("value_shape") != required:
                            raise ValueError("envelope claim/value shape mismatch")
                    elif kind != "markdown_generation_paragraph" or slot["claim"] != "artifact_publication_date":
                        raise ValueError("unsupported envelope selector/claim")
            if any(r.get("selectors", {}).get(o, {}).get("kind") not in {"h2", "table_row", "markdown_preamble"}
                   for r in records for o in ("base", "current") if r.get("selectors", {}).get(o) is not None):
                raise ValueError("records require H2, whole-preamble or table-row selectors")
        entries = records + envelope
        ids = set()
        selectors = set()
        for record in records:
            rid = record.get("id", "")
            if (not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rid) or rid in ids
                    or rid in {"remainder", "preamble"} or (not explicit_view and record.get("heading") in selectors)):
                raise ValueError(f"{path}: invalid/duplicate record identity or heading")
            ids.add(rid)
            selectors.add(record.get("heading"))
            if (record.get("independent") is not True or not record.get("rationale", "").strip()
                    or record.get("epistemic_status") not in {"observation", "proposal", "decision", "hypothesis"}):
                raise ValueError(f"{path}: record requires reviewed independence and epistemic status")
            captured = dt.date.fromisoformat(record["recorded_on"])
            if captured.isoformat() != record["recorded_on"]:
                raise ValueError(f"{path}: noncanonical record date")
            if not isinstance(record.get("context_records"), list):
                raise ValueError(f"{path}: explicit context_records required (may be empty)")
            if type(record.get("leading_blank_lines", 0)) is not int or not 0 <= record.get("leading_blank_lines", 0) <= 2:
                raise ValueError(f"{path}: leading_blank_lines must be 0, 1 or 2")
            if record.get("base_sha256") is None and record.get("current_sha256") is None:
                raise ValueError(f"{path}: record absent in both snapshots")
        for slot in envelope:
            rid = slot.get("id", "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rid) or rid in ids or rid in {"remainder", "preamble"}:
                raise ValueError("invalid/duplicate envelope identity")
            ids.add(rid)
        for origin, graph in graphs.items():
            text = graph["documents"][path]
            if explicit_view:
                from wiki_core.document_view_selectors import partition_view
                partition = partition_view(text, entries, origin)
                parts = partition["parts"]
                partitions[origin][path] = partition
            else:
                body, available = sections(text)
                lines = body.splitlines(keepends=True)
                ranges = []
                parts = {}
                for record in records:
                    section = available.get(record["heading"])
                    expected = record.get(f"{origin}_sha256")
                    if expected is None:
                        # Ambiguous headings must not masquerade as absent records.
                        if any(title == record["heading"] for title, *_ in section_spans(text)[1]):
                            raise ValueError(f"{path}: declared absent record exists or is ambiguous")
                        continue
                    if section is None:
                        raise ValueError(f"{path}: {origin} record selector/hash mismatch")
                    start, end, content = section
                    padding = record.get("leading_blank_lines", 0)
                    if start < padding or any(line.strip() for line in lines[start - padding:start]):
                        raise ValueError(f"{path}: record leading padding is not blank")
                    start -= padding
                    content = "".join(lines[start:end])
                    if digest(content) != expected:
                        raise ValueError(f"{path}: {origin} record selector/hash mismatch")
                    if any(start < other_end and other_start < end for other_start, other_end, _ in ranges):
                        raise ValueError(f"{path}: overlapping record selectors")
                    ranges.append((start, end, record["id"]))
                    parts[record["id"]] = dict(content_sha256=expected, start=start, end=end)
                selected = {line for start, end, _ in ranges for line in range(start, end)}
                remainder = text[:len(text) - len(body)] + "".join(
                    line for i, line in enumerate(lines) if i not in selected)
                parts["remainder"] = dict(content_sha256=digest(remainder))
                for start, _, rid in ranges:
                    parts[rid]["remainder_anchor"] = sum(len(line) for i, line in enumerate(lines[:start]) if i not in selected)
                partitions[origin][path] = dict(parts=parts, ranges=ranges, remainder=remainder,
                                               section_ranges=[(a, b) for _, a, b, _ in section_spans(text)[1]])
            for rid, part in parts.items():
                nid = node_id(path, rid)
                if nid in graph["nodes"]:
                    raise ValueError(f"{path}: record node collision")
                graph["nodes"][nid] = {**graph["nodes"][path], "document_record_id": rid,
                                       "document_path": path, "record_sha256": part["content_sha256"]}
            for record in entries:
                if record["id"] not in parts:
                    continue
                for context in record["context_records"]:
                    if context not in parts or context == record["id"]:
                        raise ValueError(f"{path}: invalid record context")
                    graph["edges"].append(dict(source=node_id(path, record["id"]),
                        target=node_id(path, context), type="source_ref", direction="directed",
                        basis="document_record.v1", path=path, field="context_records"))
                for aid in record.get(f"{origin}_evidence", []):
                    if (origin, aid) not in artifacts:
                        raise ValueError(f"{path}: missing record evidence")
                    graph["edges"].append(dict(source=node_id(path, record["id"]),
                        target=artifacts[(origin, aid)], type="source_ref", direction="directed",
                        basis="document_record.v1", path=path, field="record_evidence"))
        old, new = (partitions[o][path] for o in ("base", "current"))
        fully_covered = (old["remainder"] == new["remainder"]
                         and reference_definitions(base["documents"][path])
                         == reference_definitions(current["documents"][path]))
        precise = False
        if path in changed and fully_covered:
            changed_records = {rid for rid in ids
                               if old["parts"].get(rid, {}).get("content_sha256")
                               != new["parts"].get(rid, {}).get("content_sha256")}
            # Position changes alone are not semantic changes, but don't hide
            # reordering. Only additions/removals/edits with preserved remainder
            # and preserved common-record ordering get precise seeds.
            old_order = [rid for _, _, rid in sorted(old.get("order_ranges", old["ranges"])) if rid in new["parts"]]
            new_order = [rid for _, _, rid in sorted(new.get("order_ranges", new["ranges"])) if rid in old["parts"]]
            anchors_preserved = all(old["parts"][rid]["remainder_anchor"] == new["parts"][rid]["remainder_anchor"]
                                    for rid in old_order)
            if old_order == new_order and anchors_preserved:
                precise = True
                if not explicit_view:
                    changes.discard(path)
                changes.update(node_id(path, rid) for rid in changed_records)
            else:
                fully_covered = False
        if path in changes and not (explicit_view and precise):
            # Any uncovered delta seeds every part, including removed records.
            changes.update(node_id(path, rid) for rid in old["parts"].keys() | new["parts"].keys())
        evidence.append(dict(path=path, complete_delta_covered=fully_covered,
                             record_ids=sorted(ids)))
        if explicit_view:
            evidence[-1].update(mode="explicit_view_v2", raw_seed_preserved=path in changes,
                                precise_component_seeds=precise)

    # Exact, independently authored consumption bindings. There is no automatic
    # retroactive application to base. The absence of a binding means WHOLE.
    bindings = {}
    for binding in contract.get("bindings", []):
        key = (binding.get("origin"), binding.get("edge_sha256"), binding.get("consumer_record", "document"))
        if key[0] not in graphs or key in bindings or not binding.get("rationale", "").strip():
            raise ValueError("invalid/duplicate record consumption binding")
        if "contribution_effect" in binding:
            if (version != "document_record.v2"
                    or binding["contribution_effect"] != "canonical_log_annotation"
                    or key[0] != "current" or binding.get("role") != "change_target"
                    or "evidence" in binding
                    or "target_document_sha256" in binding
                    or not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("prerequisite_document_sha256", "")))):
                raise ValueError("invalid canonical contribution effect qualification")
        bindings[key] = binding
        if "locator_review" in binding:
            review = binding["locator_review"]
            if (binding.get("role", "consumption") != "consumption" or not isinstance(review, dict)
                    or set(review) != {"change_id", "consumption", "rationale"}
                    or not isinstance(review["change_id"], str) or review["change_id"] not in locator_ids
                    or review["consumption"] != "historical_observation_without_locator"
                    or not isinstance(review["rationale"], str) or not review["rationale"].strip()):
                raise ValueError("invalid locator-specific historical consumption qualification")
    used = set()
    annotation_context = contract.get("canonical_log_annotation_context")
    context_bindings = {}
    if "canonical_log_annotation_context" in contract:
        if (version != "document_record.v2" or not isinstance(annotation_context, dict)
                or set(annotation_context) != {"log_path", "bindings"}
                or not isinstance(annotation_context["log_path"], str)
                or modes.get(annotation_context["log_path"]) != "h2_v1"
                or not isinstance(annotation_context["bindings"], list)
                or not annotation_context["bindings"]):
            raise ValueError("invalid canonical log annotation context qualification")
        for qualification in annotation_context["bindings"]:
            if (not isinstance(qualification, dict)
                    or set(qualification) != {"edge_sha256", "consumer_record", "rationale"}
                    or any(not isinstance(v, str) or not v.strip() for v in qualification.values())
                    or qualification["consumer_record"] in {"document", "remainder"}):
                raise ValueError("invalid canonical log annotation context qualification")
            key = ("current", qualification["edge_sha256"], qualification["consumer_record"])
            binding = bindings.get(key)
            if (any(k[1] == key[1] for k in context_bindings)
                    or binding is None or binding.get("role") != "change_target"
                    or any(k in binding for k in ("evidence", "contribution_effect", "target_document_sha256"))
                    or not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("prerequisite_document_sha256", "")))):
                raise ValueError("invalid canonical log annotation context qualification")
            context_bindings[key] = qualification
    used_context = set()
    for origin, graph in graphs.items():
        projected = []
        for raw_index, raw in enumerate(graph["edges"]):
            edge = dict(raw)
            path = raw["path"]
            partition = partitions[origin].get(path)
            variants = [edge]
            if partition and edge["type"] not in STRUCTURAL | ASSOCIATION:
                if raw["basis"] == "markdown_body":
                    line = raw["body_line"] - 1
                    rid = next((rid for start, end, rid in partition["ranges"]
                                if start <= line < end), "remainder")
                    edge["source"] = node_id(path, rid)
                    # References in the document introduction are common
                    # premises. H2 siblings require explicit authored context.
                    inside_section = any(start <= line < end for start, end in partition["section_ranges"])
                    header_consumers = {part for start, end, part in partition.get("shared_body_context", [])
                                        if start <= line < end}
                    if header_consumers:
                        # A table header defines its selected rows even within
                        # H2. Keep the common remainder occurrence too.
                        variants = [{**edge, "source": node_id(path, part),
                                     "inherited_document_context": True}
                                    for part in sorted(header_consumers | {rid})]
                    elif not inside_section and not (modes.get(path) == "explicit_view_v2" and rid != "remainder"):
                        variants = [{**edge, "source": node_id(path, part),
                                     "inherited_document_context": True}
                                    for part in partition["parts"]]
                else:
                    # Page-level factual metadata applies to every record.
                    endpoint = "source" if edge["type"] in REFERENCE else "target"
                    if edge[endpoint] == path:
                        field_part = partition.get("fm_fields", {}).get(raw.get("field")) if raw.get("basis") == "frontmatter" else None
                        inherited = [field_part] if field_part else partition["parts"]
                        variants = [{**edge, endpoint: node_id(path, rid),
                                     "inherited_document_context": True}
                                    for rid in inherited]
            inherited_variants = []
            for variant in variants:
                dependent = "source" if variant["type"] in REFERENCE else "target"
                consumer_parts = partitions[origin].get(variant[dependent])
                if consumer_parts and variant["type"] not in STRUCTURAL | ASSOCIATION:
                    # Factual context can be authored on the prerequisite's
                    # page (e.g. an event's consolidated_into), not only here.
                    inherited_variants.extend({**variant,
                        dependent: node_id(variant[dependent], rid),
                        "inherited_document_context": True} for rid in consumer_parts["parts"])
                else:
                    inherited_variants.append(variant)
            for variant_index, variant in enumerate(inherited_variants):
                before = copy.deepcopy(variant) if trace is not None else None
                output_start = len(projected)
                dependent = "source" if variant["type"] in REFERENCE else "target"
                prerequisite = "target" if variant["type"] in REFERENCE else "source"
                consumer = graph["nodes"].get(variant[dependent], {}).get("document_record_id", "document")
                key = (origin, edge_digest(raw), consumer)
                binding = bindings.get(key)
                if binding:
                    if key in context_bindings:
                        # An authored exception for one historical destination
                        # occurrence is not a wildcard over the log's premises.
                        # The port may reuse it only for its receipt-proved H2.
                        log = annotation_context["log_path"]
                        if (raw.get("basis") != "frontmatter" or raw.get("field") != "consolidated_into"
                                or raw.get("type") != "impact" or raw.get("direction") != "directed"
                                or raw.get("source") != path or raw.get("target") != log or path == log
                                or variant[dependent] != node_id(log, consumer)
                                or variant[prerequisite] != path
                                or graph["nodes"].get(path, {}).get("page_type") != "ingestion_event"):
                            raise ValueError("invalid canonical log annotation context occurrence")
                        used_context.add(key)
                    if (modes.get(path) == "explicit_view_v2"
                            and raw.get("classification") == "reference_style_citation"):
                        raise ValueError("reference-style occurrence has no unambiguous v2 row location")
                    if variant["type"] in STRUCTURAL | ASSOCIATION:
                        raise ValueError("binding requires an authored factual relation")
                    target = variant[prerequisite]
                    role = binding.get("role", "consumption")
                    if role == "consumption":
                        if target not in partitions[origin]:
                            raise ValueError("consumption target requires declared records")
                        rid = binding.get("target_record")
                        part = partitions[origin][target]["parts"].get(rid)
                        if not part or part["content_sha256"] != binding.get("consumed_sha256"):
                            raise ValueError("consumption target record/hash mismatch")
                        variant[prerequisite] = node_id(target, rid)
                        if "locator_review" in binding:
                            locator = locator_changes.get(target)
                            if locator is None or locator["id"] != binding["locator_review"]["change_id"]:
                                raise ValueError("locator qualification requires the same changed document as its target")
                            declaration = next(d for d in declarations if d["path"] == target)
                            record = next((r for r in declaration["records"] if r["id"] == rid), None)
                            if record is None or record["epistemic_status"] != "observation":
                                raise ValueError("locator qualification requires an explicit observation record, never WHOLE/remainder")
                            variant["locator_review"] = copy.deepcopy(binding["locator_review"])
                    elif role in {"navigation", "change_target", "provenance"}:
                        target_text = graphs[origin]["documents"].get(target)
                        if target_text is None or digest(target_text) != binding.get("prerequisite_document_sha256", binding.get("target_document_sha256")):
                            raise ValueError("occurrence role target snapshot mismatch")
                        required = binding.get("evidence", [])
                        if role == "provenance" and not required:
                            raise ValueError("provenance requires verified replacement evidence")
                        for aid in required:
                            if (origin, aid) not in artifacts:
                                raise ValueError("occurrence evidence missing")
                            projected.append(dict(source=variant[dependent], target=artifacts[(origin, aid)],
                                type="source_ref", direction="directed", basis="document_record.v1",
                                path=path, field="occurrence_evidence"))
                        variant["type"] = "record_context_reference"
                        variant["authored_role"] = role
                    else:
                        raise ValueError("unknown occurrence role")
                    variant["consumption_binding"] = dict(binding)
                    used.add(key)
                if variant["type"] in STRUCTURAL | ASSOCIATION:
                    projected.append(variant)
                else:
                    # A whole-document reference consumes ALL assertions.
                    prerequisite = "target" if variant["type"] in REFERENCE else "source"
                    whole = partitions[origin].get(variant[prerequisite])
                    if whole and modes.get(variant[prerequisite]) != "explicit_view_v2":
                        projected.extend({**variant,
                                          prerequisite: node_id(variant[prerequisite], rid),
                                          "whole_document_consumption": True}
                                         for rid in whole["parts"])
                    else:
                        projected.append(variant)
                if trace is not None:
                    trace.append(dict(origin=origin, raw_index=raw_index,
                        variant_index=variant_index, edge_sha256=edge_digest(raw),
                        raw=copy.deepcopy(raw), before=before, consumer_record=consumer,
                        binding=copy.deepcopy(binding),
                        projected=copy.deepcopy(projected[output_start:])))
        # A v2 WHOLE consumes the retained raw document. Raw document in turn
        # consumes all its parts. Keeping this direction preserves raw seeds and
        # upstream freshness without re-expanding unchanged parts downstream.
        raw_count = len(graph["edges"])
        for path, partition in partitions[origin].items():
            if modes.get(path) != "explicit_view_v2":
                continue
            for rid in partition["parts"]:
                relation = dict(source=path, target=node_id(path, rid), type="source_ref",
                                direction="directed", basis="document_record.v2",
                                path=path, field="document_components")
                projected.append(relation)
                if trace is not None:
                    trace.append(dict(origin=origin, raw_index=raw_count, variant_index=0,
                        edge_sha256=edge_digest(relation), raw=copy.deepcopy(relation),
                        before=copy.deepcopy(relation), consumer_record="document", binding=None,
                        projected=[copy.deepcopy(relation)]))
                raw_count += 1
        graph["edges"] = projected
        if locator_changes:
            graph["verified_locator_changes"] = copy.deepcopy(locator_changes)
            # This graph-root lineage is built from validated partitions, never
            # inherited from ordinary page frontmatter or synthetic-looking flags.
            graph["verified_locator_record_documents"] = {
                node_id(path, rid): path for path in locator_changes
                for rid in partitions[origin].get(path, {}).get("parts", {})}
    # Preserve the raw representation seeds even when v1 isolated an H2 delta.
    # Nothing here assigns factual freshness or removes a declared dependency.
    changes.update(locator_changes)
    if set(bindings) != used:
        raise ValueError("record contract has stale or unmatched consumption bindings")
    if set(context_bindings) != used_context:
        raise ValueError("canonical log annotation context has unmatched occurrences")
    # Projector-owned scope, independent of content bytes. A remainder with a
    # newly excluded record is a different interpretation even if its name and
    # incoming binding are unchanged. Never trust equivalent frontmatter keys.
    for origin, graph in graphs.items():
        graph["verified_record_documents"] = {}
        graph["verified_record_shapes"] = {}
        graph["verified_record_substantive_sha256"] = {}
        for declaration in declarations:
            path = declaration["path"]
            partition = partitions[origin][path]
            text = graph["documents"][path]
            selection_lines = (text if modes.get(path) == "explicit_view_v2" else
                               sections(text)[0]).splitlines(keepends=True)
            shapes = {}
            for record in declaration["records"] + declaration.get("envelope", []):
                rid = record["id"]
                if rid not in partition["parts"]:
                    continue
                shapes[rid] = dict(
                    selector=copy.deepcopy(record["selectors"][origin]) if "selectors" in record else
                        dict(kind="h2", heading=record["heading"], leading_blank_lines=record.get("leading_blank_lines", 0)),
                    context_records=record["context_records"],
                    epistemic_status=record.get("epistemic_status"), claim=record.get("claim"),
                    value_shape=record.get("value_shape"))
            shapes["remainder"] = dict(excluded=copy.deepcopy(shapes))
            for rid in partition["parts"]:
                nid = node_id(path, rid)
                graph["verified_record_documents"][nid] = path
                graph["verified_record_shapes"][nid] = copy.deepcopy(shapes[rid])
                part = partition["parts"][rid]
                content = (partition["remainder"] if rid == "remainder" else
                           "".join(selection_lines[part["start"]:part["end"]]))
                graph["verified_record_substantive_sha256"][nid] = substantive_digest(
                    content, selector=shapes[rid].get("selector"), claim=shapes[rid].get("claim"))
    from wiki_core.causal_reconciliation import append_only_partitions
    append_proofs = append_only_partitions(graphs, partitions, declarations, modes)
    for graph in graphs.values():
        graph['verified_append_only_partitions'] = copy.deepcopy(append_proofs)
    # A precise v2 edit retains its raw identity for WHOLE consumers. Record
    # separately that this raw seed is a representation carrier, not a request
    # to revalidate independent, untouched siblings. Only the projector may
    # establish this after complete delta/anchor/order/reference validation.
    # Changed selection/context shape, added/removed parts, or uncovered bytes
    # conservatively keep the ordinary full-document obligation.
    precise_components = {}
    for item in evidence:
        path = item["path"]
        if not (item.get("mode") == "explicit_view_v2" and item.get("precise_component_seeds")):
            continue
        shapes = [{n: shape for n, shape in graph["verified_record_shapes"].items()
                   if graph["verified_record_documents"][n] == path} for graph in (graphs["base"], graphs["current"])]
        if shapes[0] != shapes[1]:
            continue
        parts = sorted(n for n in shapes[0] if graphs["base"]["nodes"][n]["record_sha256"]
                       != graphs["current"]["nodes"][n]["record_sha256"])
        from wiki_core.causal_review import _interpretation
        stable_context = all(_interpretation(graphs["base"], n) == _interpretation(graphs["current"], n)
                             for n in shapes[0] if n not in parts)
        if parts and set(parts) <= changes and stable_context:
            precise_components[path] = parts
    for graph in graphs.values():
        graph["verified_precise_component_seeds"] = copy.deepcopy(precise_components)
    from wiki_core.record_observations import apply_observations
    apply_observations(graphs, contract, changes, artifact_inputs or {})
    if contract.get("causal_review") is not None:
        from wiki_core.causal_review import verify
        causal = verify(graphs["current"], graphs["base"], changes, contract, artifact_inputs or {})
        for graph in graphs.values():
            graph["verified_causal_review"] = copy.deepcopy(causal)
    if review_trace is not None:
        review_trace.extend(trace)
    return graphs["current"], graphs["base"], changes, evidence
