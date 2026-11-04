"""Consolidation: turn recorded deep-read results into wiki integration.

This is the missing half of ingestion. The deterministic pipeline gathers and
the agent deep-reads; consolidation takes the RECORDED results (llm-cache) and
scaffolds the integration so the agent updates the wiki's CONCEPTS — instead of
the source being merely cataloged:

- aggregate_results: merge the per-chunk results of one source (quadrants,
  claims, decisions, actions, risks, uncertainties, relationships, entities).
- build_event_markdown: generate the normalized EVENT page from the aggregate
  (quadrants filled from the deep read — never placeholders), with
  `consolidated_into: []` for the agent to close during integration.
- build_packet: the INTEGRATION packet — for each claim/entity, the related
  existing pages (FTS + page catalog), overlapping claims and potential
  conflicts, so the agent integrates with context instead of re-reading the
  whole wiki. Judgment stays with the agent; this only narrows candidates.
- pending_consolidations: sources whose deep read is complete but whose event
  is missing or whose consolidation is not closed (consumed by the CLI --check,
  the CI and the cockpit).

No LLM client here: deterministic scaffolding only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from wiki_core.traversal import wiki_markdown_files
from wiki_core.config import WikiConfig, freshness_for, load_config
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.index.sqlite import sanitize_fts_query, search
from wiki_core.index.page_collection import current_page_signature
from wiki_core.llm.context_pass import read_matching_result
from wiki_core.paths import WikiPaths

REQUEST_SUFFIX = "-llm-context-request.json"
PACKET_SUFFIX = "-integration-packet.json"
PACKET_SCHEMA_VERSION = "wiki_integration_packet.v2"

# Output strings per language (generated event; drives config.language).
CONSOLIDATE_STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "event_title": "# Evento - {name}",
        "h_source": "## Fuente",
        "row_source_page": "- Fuente canónica: [{label}]({href}).",
        "row_source_id": "- source_id: `{source_id}`.",
        "row_generated": "- Evento generado a partir de la lectura profunda registrada (llm-cache) por [scripts/wiki_consolidate.py]({script}); revisar e INTEGRAR antes de consolidar.",
        "h_quadrants": "## Cuadrantes",
        "th_quadrants": "| Cuadrante | Contenido extraído | Ausencia/límite |",
        "q_ii": "Interior individual",
        "q_ei": "Exterior individual",
        "q_ic": "Interior colectivo",
        "q_ec": "Exterior colectivo",
        "h_claims": "## Afirmaciones candidatas",
        "h_decisions": "## Decisiones candidatas",
        "h_actions": "## Acciones candidatas",
        "h_risks": "## Riesgos",
        "h_conflicts": "## Conflictos y ambigüedades",
        "conflicts_note": "Incertidumbres de la lectura profunda; complételas con los conflictos del paquete de integración y registre la resolución.",
        "h_relationships": "## Relaciones extraídas",
        "th_relationships": "| De | A | Relación |",
        "h_integration": "## Integración",
        "integration_note": "Complete `consolidated_into:` en el frontmatter con las páginas ACTUALIZADAS por esta ingestión (cada destino que no sea `source` debe referenciar la fuente en `source_refs:`; las páginas de identidad de la fuente se vinculan mediante el evento/ciclo de vida y nunca deben autorreferenciarse). Incluya al menos un destino que no sea `source`: catalogar la fuente NO es ingerirla.",
        "empty": "- (ninguno)",
    },
    "pt": {
        "event_title": "# Evento - {name}",
        "h_source": "## Fonte",
        "row_source_page": "- Fonte canonica: [{label}]({href}).",
        "row_source_id": "- source_id: `{source_id}`.",
        "row_generated": "- Evento gerado da leitura profunda gravada (llm-cache) por [scripts/wiki_consolidate.py]({script}); revisar e INTEGRAR antes de consolidar.",
        "h_quadrants": "## Quadrantes",
        "th_quadrants": "| Quadrante | Conteudo extraido | Ausencia/limite |",
        "q_ii": "Interior individual",
        "q_ei": "Exterior individual",
        "q_ic": "Interior coletivo",
        "q_ec": "Exterior coletivo",
        "h_claims": "## Claims candidatos",
        "h_decisions": "## Decisoes candidatas",
        "h_actions": "## Acoes candidatas",
        "h_risks": "## Riscos",
        "h_conflicts": "## Conflitos e ambiguidades",
        "conflicts_note": "Incertezas da leitura profunda; complete com os conflitos do pacote de integracao e registre a resolucao.",
        "h_relationships": "## Relacoes extraidas",
        "th_relationships": "| De | Para | Relacao |",
        "h_integration": "## Integracao",
        "integration_note": "Preencha `consolidated_into:` no frontmatter com as paginas ATUALIZADAS por esta ingestao (cada alvo que nao seja `source` deve referenciar a fonte em `source_refs:`; paginas de identidade da fonte usam o fechamento do evento/lifecycle e nunca autorreferencia). Inclua ao menos um alvo que nao seja `source`: catalogar a fonte NAO e ingerir.",
        "empty": "- (nenhum)",
    },
    "en": {
        "event_title": "# Event - {name}",
        "h_source": "## Source",
        "row_source_page": "- Canonical source: [{label}]({href}).",
        "row_source_id": "- source_id: `{source_id}`.",
        "row_generated": "- Event generated from the recorded deep read (llm-cache) by [scripts/wiki_consolidate.py]({script}); review and INTEGRATE before consolidating.",
        "h_quadrants": "## Quadrants",
        "th_quadrants": "| Quadrant | Extracted content | Absence/limit |",
        "q_ii": "Interior individual",
        "q_ei": "Exterior individual",
        "q_ic": "Interior collective",
        "q_ec": "Exterior collective",
        "h_claims": "## Candidate claims",
        "h_decisions": "## Candidate decisions",
        "h_actions": "## Candidate actions",
        "h_risks": "## Risks",
        "h_conflicts": "## Conflicts and ambiguities",
        "conflicts_note": "Uncertainties from the deep read; complete with the integration packet's conflicts and record the resolution.",
        "h_relationships": "## Extracted relationships",
        "th_relationships": "| From | To | Relationship |",
        "h_integration": "## Integration",
        "integration_note": "Fill `consolidated_into:` in the frontmatter with the pages UPDATED by this ingestion (each non-source target must reference the source in `source_refs:`; source identity pages are linked by the event/lifecycle and must not self-reference). Include at least one non-source target: cataloging the source is NOT ingesting.",
        "empty": "- (none)",
    },
}

QUADRANT_KEYS = (
    "interior_individual",
    "exterior_individual",
    "interior_collective",
    "exterior_collective",
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]{3,}")
# Generic words excluded from the keyword-overlap heuristic (pt+en).
_STOPWORDS = {
    "para", "como", "deve", "devem", "with", "that", "this", "from", "have",
    "sobre", "entre", "quando", "where", "which", "their",
    "fonte", "source", "wiki", "pagina", "page", "memoria", "memory",
}


def _strings(language: str) -> dict[str, str]:
    return CONSOLIDATE_STRINGS.get(language, CONSOLIDATE_STRINGS["en"])


def _read_frontmatter(path: Path) -> dict[str, object]:
    try:
        values, _body = parse_frontmatter(path)
    except OSError:
        return {}
    return values


def load_requests(paths: WikiPaths) -> list[dict[str, object]]:
    """Emitted context requests (skips ad-hoc query- packets)."""
    out: list[dict[str, object]] = []
    events_dir = paths.extraction_events
    if not events_dir.is_dir():
        return out
    for req_file in sorted(events_dir.glob(f"*{REQUEST_SUFFIX}")):
        try:
            request = json.loads(req_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_id = str(request.get("source_id") or "")
        if not source_id or source_id.startswith("query-"):
            continue
        out.append(request)
    return out


def deep_read_complete(request: dict[str, object], cache_dir: Path) -> bool:
    chunks = request.get("chunks") or []
    if not isinstance(chunks, list) or not chunks:
        return False
    for row in chunks:
        key = str(row.get("cache_key") or "")
        if not key or read_matching_result(cache_dir, request, row) is None:
            return False
    return True


def _merge_quadrant(values: list[str]) -> str:
    """Join non-absent chunk texts; if every chunk marked absence, keep the note."""
    real = [v.strip() for v in values if v.strip() and not v.strip().lower().startswith("absent")]
    if real:
        seen: list[str] = []
        for value in real:
            if value not in seen:
                seen.append(value)
        return " ".join(seen)
    for value in values:
        if value.strip():
            return value.strip()
    return ""


def _dedup(items: list[object]) -> list[object]:
    seen: list[object] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def aggregate_results(request: dict[str, object], cache_dir: Path) -> dict[str, object]:
    """Merge the per-chunk deep-read results of one source (order = chunk order)."""
    resolved = [read_matching_result(cache_dir, request, row) for row in request.get("chunks") or []]
    return _aggregate_resolved_results(request, resolved)


def _aggregate_resolved_results(request: dict[str, object], resolved: list[dict | None]) -> dict[str, object]:
    """Merge already selected results; validation belongs to the calling route."""
    quadrants: dict[str, list[str]] = {key: [] for key in QUADRANT_KEYS}
    confidence: dict[str, str] = {}
    lists: dict[str, list[object]] = {
        "claims": [], "decisions": [], "actions": [], "risks": [],
        "uncertainties": [], "relationships": [], "entities": [],
    }
    rank = {"low": 0, "medium": 1, "high": 2}
    for result in resolved:
        if not result:
            continue
        q = result.get("quadrants")
        if isinstance(q, dict):
            for key in QUADRANT_KEYS:
                quadrants[key].append(str(q.get(key) or ""))
        qc = result.get("quadrant_confidence")
        if isinstance(qc, dict):
            for key in QUADRANT_KEYS:
                value = str(qc.get(key) or "").lower()
                if value in rank:
                    prev = confidence.get(key)
                    if prev is None or rank[value] < rank[prev]:
                        confidence[key] = value  # keep the WORST (honest floor)
        for name in lists:
            value = result.get(name)
            if isinstance(value, list):
                lists[name].extend(value)
    return {
        "source_id": request.get("source_id"),
        "prompt_version": request.get("prompt_version"),
        "chunk_count": len(request.get("chunks") or []),
        "root_entity": request.get("root_entity") or {},
        "input_channel": request.get("input_channel") or {},
        "quadrant_map": request.get("quadrant_map") or {},
        "target_pages": request.get("target_pages") or [],
        "input_stage_status": request.get("input_stage_status") or "",
        "quadrants": {key: _merge_quadrant(values) for key, values in quadrants.items()},
        "quadrant_confidence": confidence,
        **{name: _dedup(values) for name, values in lists.items()},
    }


def prepare_folder_consolidation(root: Path, binding, request: dict, results: list,
                                 *, candidates: list[str], max_age_days: int,
                                 page_metadata: dict) -> dict[str, object]:
    """Return a reviewable Markdown proposal from explicit, bound v2 results.

    This preview never scans a global catalogue or FTS index, invokes a model,
    writes a file, attests an observed read or performs preflight or merge. A
    trusted host must be authorized for the complete selected Git blobs.
    """
    import yaml
    from wiki_core.context_policy import safe_path
    from wiki_core.folder_coordination_v2 import _bound_policy, _output_authorized, prepare_folder_packet
    from wiki_core.folder_ingestion_v2 import (_check_local_boundaries, FolderIngestionSelection,
        authorize_folder_ingestion_source, validate_folder_artifact_paths, independent_repo_selection_for_request,
        additional_repo_selections_for_request)
    from wiki_core.llm.context_pass import (result_matches_request, read_matching_result,
        revalidate_ingestion_source)
    from wiki_core.page_types import validate_shape
    from wiki_core.repo_read import contains_access_secrets
    from wiki_core.repository_reader import RepositoryReader
    from scripts.wiki_audit import REQUIRED_KEYS, RELATION_KEYS, RELATION_PREFIXES

    try:
        if (not isinstance(request, dict) or request.get('context_binding_version') != 2
                or not isinstance(results, list) or not isinstance(candidates, list)
                or len(candidates) > 128 or not isinstance(page_metadata, dict) or type(max_age_days) is not int
                or not 0 <= max_age_days <= 3650
                or contains_access_secrets((request, results, candidates, page_metadata))):
            raise ValueError('invalid inputs')
        metadata_keys = {'page_id', 'context', 'visibility', 'updated_at', 'stale_after_days',
                         'sources_policy', 'gate', 'sensitive_data_policy', 'moc_parent', 'owner'}
        if (set(page_metadata) != metadata_keys
                or any(not isinstance(page_metadata[key], str) or not page_metadata[key].strip() for key in metadata_keys)):
            raise ValueError('explicit page metadata required')
        dt.date.fromisoformat(page_metadata['updated_at'])
        if len(json.dumps((request, results, candidates, page_metadata), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')).encode()) > 2_000_000:
            raise ValueError('input budget exceeded')
        packet = request['block_context_package']
        if not isinstance(packet, dict) or packet.get('schema_version') != 'wiki.folder-task-context/v2':
            raise ValueError('invalid packet')
        folder = safe_path(packet['context_folder'], allow_root=True)
        policy = _bound_policy(root, binding, folder, packet['policy_revision'])
        root = binding.root
        context = policy.folder_ids[folder]
        if (packet.get('context_id') != context or packet.get('start_folder') is not None
                or packet.get('content_revision') != policy.policy_revision):
            raise ValueError('unsupported context')
        output = safe_path(packet['output'])
        _output_authorized(policy, folder, output)
        chosen = [safe_path(path) for path in candidates]
        if len(chosen) != len(set(chosen)):
            raise ValueError('duplicate candidate')
        reader = RepositoryReader(root, policy.policy_revision)
        _check_local_boundaries(Path(root), output)
        if (output in reader.paths or any(output == path or output.startswith(path + '/') for path in reader.unsupported_paths)
                or (Path(root) / output).exists() or (Path(root) / output).is_symlink()):
            raise ValueError('existing output requires a separate proposal')
        for path in chosen:
            if (path not in reader.paths or not path.endswith('.md')
                    or policy.owner_of(path) != context or not policy.permits(context, 'read', path)):
                raise ValueError('candidate unavailable')
        if sum(reader.blob_size(path) for path in chosen) > 1_000_000:
            raise ValueError('candidate budget exceeded')

        chunks = request['chunks']
        if not isinstance(chunks, list) or not 1 <= len(chunks) <= 256 or len(results) != len(chunks):
            raise ValueError('incomplete results')
        keys = [row.get('cache_key') for row in chunks if isinstance(row, dict)]
        if len(keys) != len(chunks) or len(keys) != len(set(keys)):
            raise ValueError('invalid chunk selection')
        if any(not result_matches_request(result, request, row, recording=True)
               for row, result in zip(chunks, results)):
            raise ValueError('unmatched result')
        auth = request.get('source_authorization')
        if not isinstance(auth, dict) or auth.get('source_kind') not in ('git', 'staged_raw'):
            raise ValueError('source kind unavailable')

        by_id = {identifier: path for path, identifier in policy.folder_ids.items()}
        evidence = []
        for row in packet['inputs']:
            if not isinstance(row, dict):
                raise ValueError('invalid packet input')
            if row.get('kind') != 'evidence':
                continue
            item = {key: row[key] for key in ('path', 'reason', 'use', 'classification')}
            item['producer_folder'] = by_id[row['producer_context']]
            for key in ('section', 'field'):
                if row.get(key) is not None:
                    item[key] = row[key]
            evidence.append(item)
        task = {key: packet[key] for key in ('index_path', 'task_id', 'goal', 'output', 'integrator', 'max_bytes')}
        task['evidence'] = evidence
        task['ingestion_binding'] = packet.get('ingestion_binding')
        if packet.get('index_section') is not None:
            task['index_section'] = packet['index_section']
        rebuilt = prepare_folder_packet(root, binding, {'folder': folder,
                   'approved_revision': policy.policy_revision, 'content_revision': packet['content_revision'],
                   'task': task})['packet']
        if rebuilt != packet:
            raise ValueError('packet changed')
        registry_rows = [row for row in packet['inputs'] if row['path'] == 'wiki.page-types.yaml'
                         and row['kind'] == 'mandatory']
        if len(registry_rows) != 1:
            raise ValueError('authorized page registry required')
        from wiki_core.context_policy import UniqueLoader
        registry = yaml.load(registry_rows[0]['text'], Loader=UniqueLoader)
        shape = registry['page_types']['claim']
        if not isinstance(shape, dict):
            raise ValueError('claim registry unavailable')
        template_path = safe_path(shape['template'])
        template_rows = [row for row in packet['inputs'] if row['path'] == template_path and row['kind'] == 'mandatory']
        if len(template_rows) != 1:
            raise ValueError('authorized claim template required')
        fenced = re.search(r'(?ms)^```yaml\s*\n---\s*\n(.*?)\n---\s*\n```', template_rows[0]['text'])
        if not fenced:
            raise ValueError('claim template frontmatter unavailable')
        relation_fields = RELATION_KEYS - {'owner', 'source_refs'}
        empty_fields = re.findall(r'(?m)^([A-Za-z_][A-Za-z0-9_]*):\s*\[\]\s*(?:#.*)?$', fenced.group(1))
        if any(empty_fields.count(key) != 1 for key in relation_fields):
            raise ValueError('claim template relations unavailable')
        independent = independent_repo_selection_for_request(binding, folder, auth)
        additional = additional_repo_selections_for_request(binding, folder, auth)
        selection = FolderIngestionSelection(binding, folder, packet['index_path'], output,
                      auth['canonical_ref'] if auth['source_kind'] == 'staged_raw' else None, independent, additional)
        guard = authorize_folder_ingestion_source(root, auth['ref'], policy.policy_revision,
                                                   selection, context_max_bytes=packet['max_bytes'])
        if (guard['authorization'] != auth or guard['hash_sha256'] != request.get('source_hash_sha256')
                or guard.get('independent_repo_content') != request.get('independent_repo_content')
                or guard.get('independent_repo_additional_content') != request.get('independent_repo_additional_content')):
            raise ValueError('source authorization changed')
        paths = WikiPaths(root, load_config(root))
        validate_folder_artifact_paths(root, paths, request['source_id'])
        for row, result in zip(chunks, results):
            if read_matching_result(paths.llm_cache, request, row, root=root) != result:
                raise ValueError('matching recorded result unavailable')
        pages = []
        for path in chosen:
            item = reader.read(path)
            if contains_access_secrets(item['text']):
                raise ValueError('secret in selected page')
            pages.append({'path': path, 'revision': reader.revision,
                          'sha256': item['content_sha256'], 'text': item['text']})
        aggregate = _aggregate_resolved_results(request, results)
        # Model-produced target suggestions are not authorized selections.
        aggregate['target_pages'] = []
        source = safe_path(auth['canonical_ref'])
        source_rows = [row for row in packet['inputs'] if row.get('kind') == 'evidence'
                       and row.get('path') == source and row.get('section') is None and row.get('field') is None]
        if len(source_rows) != 1:
            raise ValueError('canonical source evidence unavailable')
        source_document = reader.read(source)
        from wiki_core.frontmatter import FRONTMATTER_RE
        source_match = FRONTMATTER_RE.match(source_document['text'])
        if source_match is None:
            raise ValueError('canonical source identity unavailable')
        source_values = yaml.load(source_match.group(1), Loader=UniqueLoader)
        if not isinstance(source_values, dict):
            raise ValueError('canonical source identity unavailable')
        source_id = source_values.get('page_id')
        if (source_values.get('page_type') != 'source'
                or not isinstance(source_id, str) or not source_id.strip()):
            raise ValueError('canonical source identity unavailable')
        if (not source_id.startswith(RELATION_PREFIXES['source_refs'])
                or not page_metadata['owner'].startswith(RELATION_PREFIXES['owner'])):
            raise ValueError('relation identity unavailable')
        if page_metadata['moc_parent'] not in set(chosen) | {packet['index_path']}:
            raise ValueError('parent was not explicitly selected')
        frontmatter = {**{key: [] for key in sorted(relation_fields)}, **page_metadata,
                       'page_type': 'claim', 'source_refs': [source_id], 'information_requirements': [{
            'target': source, 'fields': ['*'], 'temporal': 'current', 'max_age_days': max_age_days,
            'consumed_revision': policy.policy_revision, 'use': 'interpretation', 'classification': 'source'}]}
        if auth['source_kind'] == 'staged_raw':
            # Persist only existing capture metadata, never source text or an
            # access-bearing URL; raw's external association stays unverified.
            capture_keys = ('source_kind', 'ref', 'source_revision', 'source_sha256', 'source_origin',
                            'canonical_ref', 'canonical_revision', 'canonical_sha256', 'association',
                            'external_origin_verification', 'external_freshness')
            frontmatter['source_authorization'] = {key: auth[key] for key in capture_keys}
        if auth.get('independent_repo_read') is not None:
            receipt = auth['independent_repo_read']
            frontmatter['independent_repo_read'] = {
                'identity': receipt['repository']['identity'],
                **{key: receipt[key] for key in ('revision', 'path', 'blob', 'document_sha256',
                                                   'content_sha256', 'section', 'field')},
            }
        if auth.get('independent_repo_additional_reads'):
            frontmatter['independent_repo_additional_reads'] = [
                {'identity': receipt['repository']['identity'],
                 **{key: receipt[key] for key in ('revision', 'path', 'blob', 'document_sha256',
                                                  'content_sha256', 'section', 'field')}}
                for receipt in auth['independent_repo_additional_reads']]
        provenance = {key: auth.get(key) for key in ('source_kind', 'ref', 'source_revision', 'source_sha256',
                      'canonical_ref', 'canonical_revision', 'association',
                      'external_origin_verification', 'external_freshness')}
        lines = ['---', yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip(), '---',
                 '', '# Interpretação proposta', '', '## Statement', '',
                 'Conteúdo relatado para revisão independente.', '', '## Related', '',
                 '> ' + json.dumps(provenance, ensure_ascii=False, sort_keys=True),
                 '', '## Conflicts and ambiguities', '', 'Revisão independente pendente.']
        for label, key in (('Quadrantes', 'quadrants'), ('Afirmações', 'claims'), ('Decisões', 'decisions'),
                           ('Ações', 'actions'), ('Riscos', 'risks'), ('Incertezas', 'uncertainties'),
                           ('Relações', 'relationships'), ('Entidades', 'entities')):
            value = aggregate[key]
            if value:
                lines.extend(['', '## ' + label, '', '> ' + json.dumps(value, ensure_ascii=False, sort_keys=True)])
        markdown = '\n'.join(lines) + '\n'
        repo_texts = [request.get('independent_repo_content'), *(request.get('independent_repo_additional_content') or [])]
        if any(isinstance(text, str) and text and (text in markdown
                or json.dumps(text, ensure_ascii=False)[1:-1] in markdown) for text in repo_texts):
            raise ValueError('complete repository text cannot be persisted')
        if not REQUIRED_KEYS <= set(frontmatter) or validate_shape(root, output, frontmatter, markdown, shape):
            raise ValueError('claim does not satisfy the selected registry')
        result = {'schema_version': 'wiki.folder-consolidation-preview/v2',
                  'state': 'independent_review_required', 'folder': folder,
                  'policy_revision': policy.policy_revision, 'output': packet['output'],
                  'packet_digest': packet['packet_digest'], 'selected_pages': pages,
                  'markdown': markdown, 'coverage': 'explicit_selected_pages_only',
                  'reads': 'reported_not_independently_verified', 'execution': 'not_proven',
                  'preflight': 'not_performed', 'write': 'not_performed', 'merge': 'not_performed'}
        if contains_access_secrets(result):
            raise ValueError('secret in proposal')
        revalidate_ingestion_source(guard, captured_hash=request['source_hash_sha256'])
        policy.fresh()
        return result
    except (ValueError, OSError, TypeError, KeyError, AttributeError, RecursionError, yaml.YAMLError):
        raise ValueError('folder consolidation unavailable or unauthorized') from None


def _source_slug(source_id: str) -> str:
    """source-<name>-<digest12> -> <name>; tolerate non-canonical ids."""
    value = str(source_id)
    if value.startswith("source-"):
        value = value[len("source-"):]
    parts = value.rsplit("-", 1)
    if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{8,64}", parts[1]):
        value = parts[0]
    return value or "source"


def _claim_text(claim: object) -> str:
    if isinstance(claim, dict):
        return str(claim.get("claim") or claim.get("text") or "")
    return str(claim)


def _entity_name(entity: object) -> str:
    if isinstance(entity, dict):
        return str(entity.get("name") or "")
    return str(entity)


def build_event_markdown(
    aggregated: dict[str, object],
    *,
    config: WikiConfig,
    context: str,
    date: dt.date,
    source_page: str | None = None,
    source_ref: str | None = None,
    source_type: str = "file",
    risk_level: str = "medium",
    event_dir: Path | None = None,
    root: Path | None = None,
    impact: dict[str, object] | None = None,
) -> str:
    """The normalized event, generated from the recorded deep read."""
    source_page = str(source_page or "").strip() or None
    source_ref = str(source_ref or "").strip() or None
    canonical_source_parent = source_page or source_ref
    if canonical_source_parent is None:
        raise ValueError(
            "normalized ingestion event requires source_page or source_ref"
        )
    s = _strings(config.language)
    source_id = str(aggregated.get("source_id") or "source")
    slug = _source_slug(source_id)
    name = f"{date.isoformat()}-{slug}"
    quadrants = aggregated.get("quadrants") or {}
    confidence = aggregated.get("quadrant_confidence") or {}
    impact = impact or {}
    must_update = [str(p) for p in impact.get("must_update") or []]
    should_review = [str(p) for p in impact.get("should_review") or []]

    def q_row(label: str, key: str) -> str:
        content = str(quadrants.get(key) or "").replace("|", "\\|").replace("\n", " ").strip()
        absent = ""
        if content.lower().startswith("absent"):
            absent, content = content, ""
        conf = confidence.get(key)
        if conf and content:
            content = f"{content} (confidence: {conf})"
        return f"| {label} | {content} | {absent} |"

    def bullet_list(name_: str) -> list[str]:
        items = aggregated.get(name_) or []
        rows: list[str] = []
        for item in items:
            text = _claim_text(item) if name_ == "claims" else (
                str(item.get("decision") or item.get("action") or item) if isinstance(item, dict) else str(item)
            )
            text = text.strip()
            if text:
                rows.append(f"- {text}")
        return rows or [s["empty"]]

    rel_rows: list[str] = []
    for rel in aggregated.get("relationships") or []:
        if isinstance(rel, dict):
            frm = str(rel.get("from") or "").replace("|", "\\|")
            to = str(rel.get("to") or "").replace("|", "\\|")
            kind = str(rel.get("kind") or "").replace("|", "\\|")
            if frm or to:
                rel_rows.append(f"| {frm} | {to} | {kind} |")

    script_href = "../../../../scripts/wiki_consolidate.py"
    source_rows: list[str] = []
    if source_page and root is not None and event_dir is not None:
        import os

        href = os.path.relpath(root / source_page, event_dir).replace(os.sep, "/")
        source_rows.append(s["row_source_page"].format(label=source_page, href=href))
    source_rows.append(s["row_source_id"].format(source_id=source_id))
    source_rows.append(s["row_generated"].format(script=script_href))

    fm: list[str] = [
        "---",
        f"event_id: evt-{name}",
        f"page_id: evento-{name}" if config.language in {"es", "pt"} else f"page_id: event-{name}",
        "page_type: ingestion_event",
        f"context: {context}",
        "visibility: private_self",
        f"updated_at: {date.isoformat()}",
        f"stale_after_days: {freshness_for(context, 'ingestion_event', config)}",
        "sources_policy: evento_normalizado_com_quadrantes",
    ]
    # The registry is an index/collection of source pages, never the
    # hierarchical parent of every ingestion event. Keep the normalized event
    # under its canonical source so the journey is registry -> source -> event
    # without flattening the event ledger.
    fm.append(f"moc_parent: {canonical_source_parent}")
    fm.extend(
        [
            "gate: github_pr",
            "sensitive_data_policy: private_sensitive_allowed",
            f"source_id: {source_id}",
        ]
    )
    if source_ref:
        fm.append(f"source_ref: {source_ref}")
    fm.extend(
        [
            f"source_type: {source_type}",
            f"captured_at: {date.isoformat()}",
            f"verified_at: {date.isoformat()}",
            "status_epistemologico: proposta",
            f"risk_level: {risk_level}",
            "requires_gate: true",
            "target_pages: []",
            "consolidated_into: []",
        ]
    )
    if must_update or should_review:
        fm.append("affected_pages:")
        if must_update:
            fm.append("  must_update:")
            fm.extend(f"    - {page}" for page in must_update)
        else:
            fm.append("  must_update: []")
        if should_review:
            fm.append("  should_review:")
            fm.extend(f"    - {page}" for page in should_review)
        else:
            fm.append("  should_review: []")
    else:
        fm.append("affected_pages: {must_update: [], should_review: []}")
    fm.extend(
        [
            "impact_closure:",
            "  updated: []",
            "  no_change: []",
            "  blocked: []",
            "---",
        ]
    )

    uncertainties = [str(u).strip() for u in (aggregated.get("uncertainties") or []) if str(u).strip()]
    body: list[str] = [
        *fm,
        "",
        s["event_title"].format(name=slug),
        "",
        s["h_source"],
        "",
        *source_rows,
        "",
        s["h_quadrants"],
        "",
        s["th_quadrants"],
        "| --- | --- | --- |",
        q_row(s["q_ii"], "interior_individual"),
        q_row(s["q_ei"], "exterior_individual"),
        q_row(s["q_ic"], "interior_collective"),
        q_row(s["q_ec"], "exterior_collective"),
        "",
        s["h_claims"],
        "",
        *bullet_list("claims"),
        "",
        s["h_decisions"],
        "",
        *bullet_list("decisions"),
        "",
        s["h_actions"],
        "",
        *bullet_list("actions"),
        "",
        s["h_risks"],
        "",
        *bullet_list("risks"),
        "",
        s["h_conflicts"],
        "",
        s["conflicts_note"],
        "",
        *([f"- {u}" for u in uncertainties] or [s["empty"]]),
        "",
    ]
    if rel_rows:
        body.extend([s["h_relationships"], "", s["th_relationships"], "| --- | --- | --- |", *rel_rows, ""])
    return "\n".join(body)


def _page_catalog(root: Path, config: WikiConfig) -> dict[str, dict[str, object]]:
    """page_id -> {rel, title, aliases, page_type, source_refs} for memory pages."""
    memory_root = root / config.paths["memory_root"]
    catalog: dict[str, dict[str, object]] = {}
    if not memory_root.is_dir():
        return catalog
    for md in sorted(wiki_markdown_files(memory_root, wiki_root=root)):
        fm = _read_frontmatter(md)
        page_id = str(fm.get("page_id") or "")
        if not page_id:
            continue
        aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
        catalog[page_id] = {
            "rel": md.relative_to(root).as_posix(),
            "title": str(fm.get("title") or ""),
            "aliases": [str(a) for a in aliases],
            "page_type": str(fm.get("page_type") or ""),
            "source_refs": [str(x) for x in fm.get("source_refs") or []] if isinstance(fm.get("source_refs"), list) else [],
        }
    return catalog


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def build_packet(
    aggregated: dict[str, object], root: Path, config: WikiConfig, paths: WikiPaths
) -> dict[str, object]:
    """Integration packet: candidate targets and overlaps for the agent."""
    catalog = _page_catalog(root, config)
    db_path = paths.indexes / "wiki.sqlite"
    packet_warnings: list[str] = []
    initial_signature: str | None = None
    signature_error: Exception | None = None

    def fts(query: str, limit: int = 3) -> list[dict[str, object]]:
        nonlocal initial_signature, signature_error
        if not db_path.exists() or not query.strip():
            return []
        try:
            if signature_error is not None:
                raise signature_error
            if initial_signature is None:
                try:
                    initial_signature = current_page_signature(paths)
                except Exception as exc:
                    signature_error = exc
                    raise
            hits = search(db_path, sanitize_fts_query(query), limit=limit,
                          page_signature=initial_signature)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, but VISIBLY
            note = (
                f"fts lookup failed ({type(exc).__name__}: {exc}); "
                "related excerpts omitted from this packet"
            )
            if note not in packet_warnings:
                packet_warnings.append(note)
            return []
        return [
            {"source_id": h.get("source_id"), "chunk_id": h.get("chunk_id"),
             "excerpt": str(h.get("text") or "")[:240]}
            for h in hits
        ]

    # Entity -> page candidates (exact name/alias containment, case-insensitive).
    entity_matches: list[dict[str, object]] = []
    for entity in aggregated.get("entities") or []:
        name = _entity_name(entity).strip()
        if len(name) < 4:
            continue
        low = name.lower()
        pages = [
            {"page_id": pid, "rel": meta["rel"]}
            for pid, meta in catalog.items()
            if low in str(meta["title"]).lower()
            or any(low == str(a).lower() for a in meta["aliases"])
            or low.replace(" ", "-") in pid
        ]
        entity_matches.append({"entity": name, "pages": pages})

    # Claim -> related content (FTS over sources+pages) + overlapping claim pages.
    claim_pages = {pid: meta for pid, meta in catalog.items() if meta["page_type"] == "claim"}
    claim_rows: list[dict[str, object]] = []
    for claim in aggregated.get("claims") or []:
        text = _claim_text(claim).strip()
        if not text:
            continue
        kw = _keywords(text)
        overlaps = [
            {"page_id": pid, "rel": meta["rel"],
             "shared_keywords": sorted(kw & _keywords(str(meta["title"])))}
            for pid, meta in claim_pages.items()
            if len(kw & _keywords(str(meta["title"]))) >= 2
        ]
        claim_rows.append(
            {
                "claim": text,
                "related": fts(text),
                "overlapping_claims": overlaps,
                "potential_conflict": bool(overlaps),
            }
        )

    # Validate again before returning: one scan serves all lookups, while a
    # changed/unreadable wiki cannot leave earlier page excerpts in the packet.
    if initial_signature is not None:
        try:
            stable = current_page_signature(paths) == initial_signature
        except Exception:  # noqa: BLE001 - fail closed and report coverage
            stable = False
        if not stable:
            for row in claim_rows:
                row['related'] = []
            packet_warnings.append('fts lookup failed (wiki page index changed during packet); related excerpts omitted from this packet')

    should_review = sorted(
        {
            str(page["rel"])
            for row in entity_matches
            for page in row.get("pages", [])
            if isinstance(page, dict) and page.get("rel")
        }
        | {
            str(page["rel"])
            for row in claim_rows
            for page in row.get("overlapping_claims", [])
            if isinstance(page, dict) and page.get("rel")
        }
    )
    target_pages = {
        str(page)
        for page in (aggregated.get("target_pages") or [])
        if str(page).strip()
    }
    must_update = sorted(
        {
            str(meta["rel"])
            for meta in catalog.values()
            if str(aggregated.get("source_id") or "") in (meta.get("source_refs") or [])
        }
        | target_pages
    )
    root_entity = aggregated.get("root_entity") if isinstance(aggregated.get("root_entity"), dict) else {}
    input_channel = aggregated.get("input_channel") if isinstance(aggregated.get("input_channel"), dict) else {}

    return {
        "kind": "wiki_integration_packet",
        "schema_version": PACKET_SCHEMA_VERSION,
        "source_id": aggregated.get("source_id"),
        "root_impact": {
            "root_entity": root_entity,
            "input_channel": input_channel,
            "input_stage_status": aggregated.get("input_stage_status") or "",
            "quadrant_map": aggregated.get("quadrant_map") or {},
            "target_pages": sorted(target_pages),
        },
        "impact": {
            "must_update": must_update,
            "should_review": [page for page in should_review if page not in must_update],
        },
        "claims": claim_rows,
        "entities": entity_matches,
        "uncertainties": aggregated.get("uncertainties") or [],
        "relationships": aggregated.get("relationships") or [],
        # Degradations that happened while building THIS packet (e.g. a broken
        # FTS index): empty on the happy path, never silently dropped.
        "warnings": packet_warnings,
        "instructions": (
            "Integrate: update the candidate target pages (hubs/concepts) with the new "
            "information; create/update load-bearing claim pages (conflict fields when "
            "they collide); resolve or record each potential_conflict and uncertainty; "
            "then fill the event's consolidated_into with the pages you updated (at "
            "least one non-source target; every non-source target must reference the "
            "source in source_refs, while source identities remain acyclic)."
        ),
    }


def find_event_for_source(paths: WikiPaths, source_id: str) -> Path | None:
    events_dir = paths.ingest_events_dir
    if not events_dir.is_dir():
        return None
    for md in sorted(events_dir.glob("*.md")):
        if md.name == "README.md":
            continue
        fm = _read_frontmatter(md)
        if str(fm.get("source_id") or "") == source_id:
            return md
    return None


def pending_consolidations(root: Path, config: WikiConfig) -> list[dict[str, object]]:
    """Sources with a COMPLETE deep read whose consolidation is not closed.

    States reported: missing_event (no event references the source_id) and
    missing_consolidated_into (event exists but integration not closed).
    """
    paths = WikiPaths(root, config)
    cache_dir = paths.llm_cache
    out: list[dict[str, object]] = []
    for request in load_requests(paths):
        source_id = str(request.get("source_id"))
        if not deep_read_complete(request, cache_dir):
            continue  # the context-pass gate already covers incomplete reads
        event = find_event_for_source(paths, source_id)
        if event is None:
            out.append({"source_id": source_id, "state": "missing_event"})
            continue
        fm = _read_frontmatter(event)
        consolidated = fm.get("consolidated_into")
        if not isinstance(consolidated, list) or not consolidated:
            out.append(
                {
                    "source_id": source_id,
                    "state": "missing_consolidated_into",
                    "event": event.relative_to(root).as_posix(),
                }
            )
    return out
