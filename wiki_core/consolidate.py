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
from wiki_core.config import WikiConfig, freshness_for
from wiki_core.frontmatter import parse_frontmatter
from wiki_core.index.sqlite import sanitize_fts_query, search
from wiki_core.index.page_collection import current_page_signature
from wiki_core.llm.context_pass import read_matching_result
from wiki_core.paths import WikiPaths

REQUEST_SUFFIX = "-llm-context-request.json"
PACKET_SUFFIX = "-integration-packet.json"
PACKET_SCHEMA_VERSION = "wiki_integration_packet.v2"


def _compare_selected_inputs(root, *, source_page, candidates, repo_root, identity,
                             revision, repo_path, entry_folder, source_file, entry_index):
    """Validate the complete explicit selection before opening any body."""
    from wiki_core.context_policy import safe_path
    from wiki_core.llm.context_pass import validate_local_entry_source
    from wiki_core.repo_read import contains_access_secrets, remote_identity
    from wiki_core.repository_reader import canonical_path
    from wiki_core.traversal import require_wiki_path

    if (not isinstance(candidates, list) or not 1 <= len(candidates) <= 128
            or any(not isinstance(ref, str) for ref in candidates)
            or len(candidates) != len(set(candidates))
            or contains_access_secrets([source_page, candidates, repo_root, identity, revision,
                                        repo_path, entry_folder, entry_index, source_file])):
        raise ValueError('comparison unavailable')
    if (not isinstance(repo_root, str) or not Path(repo_root).is_absolute()
            or not isinstance(identity, str) or not isinstance(revision, str)
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision)
            or canonical_path(repo_path) != repo_path
            or remote_identity('https://' + identity)[0] != identity):
        raise ValueError('comparison unavailable')
    selected_root = Path(repo_root).resolve(strict=True)
    if not selected_root.is_dir() or selected_root == root.resolve():
        raise ValueError('comparison unavailable')
    folder = safe_path(entry_folder, allow_root=True)
    if not require_wiki_path(root, folder).is_dir():
        raise ValueError('comparison unavailable')
    if entry_index is None:
        if folder == '.':
            raise ValueError('comparison unavailable')
    else:
        selected_index = safe_path(entry_index)
        if not require_wiki_path(root, selected_index).is_file():
            raise ValueError('comparison unavailable')
    selected_source = validate_local_entry_source(root, source_file)
    if not Path(selected_source).is_absolute() or Path(selected_source).stat().st_size > 16_000_000:
        raise ValueError('selected source exceeds comparison limit')
    refs = [safe_path(source_page), *(safe_path(ref) for ref in candidates)]
    if len(set(refs)) != len(refs):
        raise ValueError('comparison unavailable')
    selected = [require_wiki_path(root, ref) for ref in refs]
    if any(not item.is_file() or item.suffix.lower() != '.md' for item in selected):
        raise ValueError('comparison unavailable')
    if sum(item.stat().st_size for item in selected) > 1_000_000:
        raise ValueError('comparison unavailable')
    return refs, selected, selected_source, str(selected_root)


def compare_repository_candidates(source_page, candidates, metadata, changed):
    """Classify only selected page declarations; file consumption remains unknown."""
    from wiki_core.information_relations import information_requirements
    result = []
    for ref, values in zip(candidates, metadata):
        requirements = information_requirements(values, lambda target: [target])
        declared = any(item['target'] == source_page and item['temporal'] == 'current' for item in requirements)
        result.append({'path': ref, 'state': 'review_pending' if changed and declared else 'unknown',
            'source_page_requirement': 'declared' if declared else 'unknown',
            'reason': ('operator_selected_page_requirement_file_consumption_unknown'
                       if changed and declared else 'insufficient_file_consumption_evidence'),
            'blocking': False, 'file_consumption': 'unknown', 'verification_performed': False})
    return result


def compare_selected_repo(root: Path, paths: WikiPaths, request: dict, *, source_page: str,
                          candidates: list[str], repo_root: str, identity: str,
                          revision: str, repo_path: str, entry_folder: str,
                          source_file: str, entry_index: str | None = None) -> dict:
    """Compare one explicitly selected Git file for operator-selected candidates.

    This diagnostic records no decision, changes no pages, and does not prove
    that an interpretation consumed the selected file or grant host access.
    """
    from wiki_core.context_selection import _metadata, strict_json_loads
    from wiki_core.llm.context_pass import is_local_folder_request, _folder_documents, validate_local_entry_source
    from wiki_core.repo_read import (contains_access_secrets, remote_identity,
                                    _prepare_repo_read, _read_prepared_repo)
    from wiki_core.traversal import require_wiki_path

    if not is_local_folder_request(request):
        raise ValueError('comparison unavailable')
    refs, selected, selected_source, selected_root = _compare_selected_inputs(root,
        source_page=source_page, candidates=candidates, repo_root=repo_root, identity=identity,
        revision=revision, repo_path=repo_path, entry_folder=entry_folder,
        entry_index=entry_index, source_file=source_file)
    package = request.get('block_context_package')
    if not isinstance(package, dict):
        raise ValueError('comparison unavailable')
    if (package.get('entry_folder') != entry_folder
            or (entry_index is not None and package.get('entry_index') != entry_index)):
        raise ValueError('selected folder context changed')
    from wiki_core.context_policy import safe_path
    retained_index = safe_path(package.get('entry_index'))
    if not require_wiki_path(root, retained_index).is_file():
        raise ValueError('selected folder context changed')
    documents = package.get('documents')
    if not isinstance(documents, list) or any(not isinstance(doc, dict) for doc in documents):
        raise ValueError('comparison unavailable')
    limits = request.get('request_limits')
    if (not isinstance(limits, dict) or type(limits.get('context_max_bytes')) is not int
            or not 1 <= limits['context_max_bytes'] <= 2_000_000):
        raise ValueError('comparison unavailable')
    local = _folder_documents(root, entry_folder, entry_index, limits['context_max_bytes'])
    if local != [doc for doc in documents if doc.get('origin') == 'working_tree']:
        raise ValueError('selected folder context changed')
    if package.get('entry_folder', entry_folder) != entry_folder or package.get('entry_index', local[-1]['path']) != local[-1]['path']:
        raise ValueError('selected folder context changed')
    matching = [doc for doc in documents if isinstance(doc, dict) and doc.get('origin') == 'independent_git'
                and doc.get('repository_root') == selected_root
                and isinstance(doc.get('repository_read'), dict)
                and isinstance(doc['repository_read'].get('repository'), dict)
                and doc['repository_read'].get('repository', {}).get('identity') == identity
                and doc['repository_read'].get('path') == repo_path]
    if len(matching) != 1:
        raise ValueError('comparison unavailable')
    receipt = matching[0]['repository_read']
    old_revision = receipt.get('revision')
    if not isinstance(old_revision, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', old_revision):
        raise ValueError('comparison unavailable')
    rows = request.get('chunks')
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows) or any(
            read_matching_result(paths.llm_cache, request, row, root=root) is None for row in rows):
        raise ValueError('recorded local result unavailable')

    # The retained source locator must identify the same capture before the
    # source body is reopened. URLs without observed content remain unknown.
    from wiki_core.source_manifest import source_id_for
    source_id, source_hash = request.get('source_id'), request.get('source_hash_sha256')
    if (not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id)
            or not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash)):
        raise ValueError('source capture unavailable')
    manifest_ref = (paths.source_manifests / f'{source_id}.json').relative_to(root).as_posix()
    manifest_path = require_wiki_path(root, manifest_ref)
    with manifest_path.open('rb') as stream:
        manifest_bytes = stream.read(2_000_001)
    if len(manifest_bytes) > 2_000_000:
        raise ValueError('source capture unavailable')
    manifest = strict_json_loads(manifest_bytes.decode('utf-8'))
    if not isinstance(manifest, dict) or not isinstance(manifest.get('source_uri'), str):
        raise ValueError('source capture unavailable')
    locator = manifest['source_uri']
    retained_source = Path(locator).expanduser()
    if not retained_source.is_absolute():
        retained_source = root.resolve() / retained_source
    if retained_source != Path(selected_source):
        raise ValueError('selected source differs')
    if (manifest.get('source_id') != source_id or manifest.get('hash_sha256') != source_hash
            or source_id_for(locator, source_hash, root=root) != source_id):
        raise ValueError('source capture unavailable')
    # Refuse large/growing inputs without silently hashing a prefix.
    source_limit = 16_000_000
    selected_path = Path(selected_source)
    if selected_path.stat().st_size > source_limit:
        raise ValueError('selected source exceeds comparison limit')
    validate_local_entry_source(root, source_file)
    with selected_path.open('rb') as stream:
        data = stream.read(source_limit + 1)
    if len(data) > source_limit:
        raise ValueError('selected source exceeds comparison limit')
    import hashlib
    if hashlib.sha256(data).hexdigest() != source_hash:
        raise ValueError('selected source changed')

    # Read only explicitly selected wiki pages and bound their aggregate size.
    metadata = []
    remaining = 1_000_000
    for ref, item in zip(refs, selected):
        require_wiki_path(root, ref)
        with item.open('rb') as stream:
            raw = stream.read(remaining + 1)
        if len(raw) > remaining:
            raise ValueError('comparison unavailable')
        remaining -= len(raw)
        text = raw.decode('utf-8')
        if contains_access_secrets(text):
            raise ValueError('comparison unavailable')
        metadata.append(_metadata({'text': text}))
    source = metadata[0]
    locator = source.get('source_locator')
    if (source.get('page_type') != 'source' or source.get('platform') != 'repo'
            or not isinstance(locator, str)
            or remote_identity(locator if '://' in locator or '@' in locator else 'https://' + locator)[0] != identity):
        raise ValueError('source repository identity unavailable')
    page_id = source.get('page_id')
    if not isinstance(page_id, str) or not page_id:
        raise ValueError('source identity unavailable')

    # Validate both revisions and object sizes before opening either blob.
    prepared = [_prepare_repo_read(Path(selected_root), identity, rev, repo_path, max_bytes=2_000_000)
                for rev in (old_revision, revision)]
    before, after = [_read_prepared_repo(item) for item in prepared]
    before_text = before.pop('text')
    after.pop('text')
    if before != receipt or matching[0].get('text') != before_text:
        raise ValueError('retained repository receipt differs')
    changed = before['content_sha256'] != after['content_sha256']
    result = compare_repository_candidates(source_page, candidates, metadata[1:], changed)
    return {'repository_comparison': {'identity': identity, 'path': repo_path,
                'before_revision': old_revision, 'after_revision': revision,
                'before_digest': before['content_sha256'], 'after_digest': after['content_sha256'],
                'changed': changed}, 'source_page': source_page, 'candidates': result,
            'coverage': 'explicit_candidates_only; selected_repository_only; file_consumption_unknown',
            'effect': 'manual_suggestion_only; no_gate_effect',
            'review': 'not_performed', 'write': 'not_performed'}

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


def load_requests(paths: WikiPaths, *, root: Path | None = None) -> list[dict[str, object]]:
    """Emitted context requests (skips ad-hoc query- packets)."""
    out: list[dict[str, object]] = []
    events_dir = paths.extraction_events
    if root is not None:
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(root, directories=(events_dir,))
    if not events_dir.is_dir():
        return out
    for req_file in sorted(events_dir.glob(f"*{REQUEST_SUFFIX}")):
        if root is not None:
            require_wiki_boundaries(root, files=(req_file,))
        if re.fullmatch(r'folder-[0-9a-f]{64}-[0-9a-f]{64}-llm-context-request\.json', req_file.name):
            from wiki_core.llm.context_pass import load_local_request
            out.append(load_local_request(paths, req_file))
            continue
        try:
            request = json.loads(req_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source_id = str(request.get("source_id") or "")
        if not source_id or source_id.startswith("query-"):
            continue
        out.append(request)
    return out


def deep_read_complete(request: dict[str, object], cache_dir: Path, *, root: Path | None = None) -> bool:
    chunks = request.get("chunks") or []
    if not isinstance(chunks, list) or not chunks:
        return False
    for row in chunks:
        key = str(row.get("cache_key") or "")
        if not key or read_matching_result(cache_dir, request, row, root=root) is None:
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


def aggregate_results(request: dict[str, object], cache_dir: Path, *, root: Path | None = None,
                      result_reader=None) -> dict[str, object]:
    """Merge the per-chunk deep-read results of one source (order = chunk order)."""
    quadrants: dict[str, list[str]] = {key: [] for key in QUADRANT_KEYS}
    confidence: dict[str, str] = {}
    lists: dict[str, list[object]] = {
        "claims": [], "decisions": [], "actions": [], "risks": [],
        "uncertainties": [], "relationships": [], "entities": [],
    }
    rank = {"low": 0, "medium": 1, "high": 2}
    for row in request.get("chunks") or []:
        result = (result_reader(row) if result_reader is not None
                  else read_matching_result(cache_dir, request, row, root=root))
        if not result:
            raise ValueError('deep read result disappeared or is invalid')
        if request.get('protected_request_id') and 'protected_historical_review' in result:
            raise ValueError('historical review unavailable; artifact preserved')
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
    git_sources = []
    if request.get('folder_request_id'):
        source_hash = request.get('source_hash_sha256')
        if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash):
            raise ValueError('local source hash unavailable')
        from wiki_core.repo_read import contains_access_secrets, remote_identity
        from wiki_core.repository_reader import canonical_path
        package = request.get('block_context_package') or {}
        documents = package.get('documents') if isinstance(package, dict) else None
        if not isinstance(documents, list):
            raise ValueError('local request provenance unavailable')
        for document in documents:
            if not isinstance(document, dict):
                raise ValueError('local request provenance unavailable')
            if document.get('origin') != 'independent_git':
                continue
            try:
                receipt = document['repository_read']
                identity = receipt['repository']['identity']
                selected = {'identity': identity, **{key: receipt[key] for key in
                    ('revision', 'path', 'blob', 'document_sha256', 'content_sha256')}}
                if (any(not isinstance(value, str) or not value for value in selected.values())
                        or remote_identity('https://' + identity)[0] != identity
                        or canonical_path(selected['path']) != selected['path']
                        or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', selected['revision'])
                        or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', selected['blob'])
                        or not all(re.fullmatch(r'[0-9a-f]{64}', selected[key]) for key in
                                   ('document_sha256', 'content_sha256'))
                        or contains_access_secrets(selected)):
                    raise ValueError('local request provenance unavailable')
            except (KeyError, TypeError, AttributeError, ValueError):
                raise ValueError('local request provenance unavailable') from None
            git_sources.append(selected)
    return {
        "source_id": request.get("source_id"),
        **({'folder_request_id': request['folder_request_id']} if request.get('folder_request_id') else {}),
        **({'source_hash_sha256': source_hash} if request.get('folder_request_id') else {}),
        **({'independent_git_sources': git_sources} if git_sources else {}),
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
    yaml_safe: bool = False,
    protected_provenance: dict[str, object] | None = None,
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
    request_id = aggregated.get('folder_request_id')
    if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id)):
        raise ValueError('invalid contextual request identity')
    if request_id:
        import hashlib
        name = f"{date.isoformat()}-{hashlib.sha256(source_id.encode()).hexdigest()}-{request_id}"
    else:
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
        label = source_page
        if yaml_safe:
            from urllib.parse import quote
            href = quote(href, safe='/._-')
            label = label.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
        source_rows.append(s["row_source_page"].format(label=label, href=href))
    source_rows.append(s["row_source_id"].format(source_id=source_id))
    source_rows.append(s["row_generated"].format(script=script_href))
    manifest_ref = None
    if request_id and root is not None and event_dir is not None:
        import os
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
            raise ValueError('invalid source identity')
        manifest = WikiPaths(root, config).source_manifests / f'{source_id}.json'
        manifest_ref = manifest.relative_to(root).as_posix()
        href = os.path.relpath(manifest, event_dir).replace(os.sep, '/')
        source_rows.append(f'- [Source capture manifest]({href}) (consult only with host authorization).')
    if impact.get('coverage') == 'explicit_candidates_only':
        source_rows.append('- Impact coverage: only explicitly selected candidates; global catalog and FTS were not searched.')

    def scalar(value):
        return json.dumps(str(value), ensure_ascii=False) if yaml_safe else str(value)

    fm: list[str] = [
        "---",
        f"event_id: evt-{name}",
        f"page_id: evento-{name}" if config.language in {"es", "pt"} else f"page_id: event-{name}",
        "page_type: ingestion_event",
        f"context: {scalar(context)}",
        "visibility: private_self",
        f"updated_at: {date.isoformat()}",
        f"stale_after_days: {freshness_for(context, 'ingestion_event', config)}",
        "sources_policy: evento_normalizado_com_quadrantes",
    ]
    # The registry is an index/collection of source pages, never the
    # hierarchical parent of every ingestion event. Keep the normalized event
    # under its canonical source so the journey is registry -> source -> event
    # without flattening the event ledger.
    fm.append(f"moc_parent: {scalar(canonical_source_parent)}")
    fm.extend(
        [
            "gate: github_pr",
            "sensitive_data_policy: private_sensitive_allowed",
            f"source_id: {source_id}",
        ]
    )
    if source_ref:
        fm.append(f"source_ref: {scalar(source_ref)}")
    if protected_provenance is not None:
        required = {'source_locator', 'policy_revision', 'executor_context', 'integrator_context', 'source_page_association'}
        limitations = protected_provenance.get('extraction_limitations', [])
        if (not yaml_safe or not required <= set(protected_provenance)
                or set(protected_provenance) - (required | {'extraction_limitations', 'csv_delimiter'})
                or any(not isinstance(protected_provenance[k], str) or not protected_provenance[k] for k in required)
                or ('csv_delimiter' in protected_provenance and
                    protected_provenance['csv_delimiter'] not in ('comma', 'semicolon', 'tab'))
                or not isinstance(limitations, list) or len(limitations) > 16
                or any(not isinstance(item, str) or not item or len(item) > 1024 for item in limitations)):
            raise ValueError('protected provenance unavailable')
        fm.append('protected_provenance: ' + json.dumps(protected_provenance, ensure_ascii=False, sort_keys=True))
    if request_id:
        source_hash = aggregated.get('source_hash_sha256')
        if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash):
            raise ValueError('local source hash unavailable')
        fm.append(f"folder_request_id: {request_id}")
        fm.append(f"source_hash_sha256: {source_hash}")
        if manifest_ref:
            fm.append('manifest_ref: ' + json.dumps(manifest_ref, ensure_ascii=False))
        if aggregated.get('independent_git_sources'):
            fm.append('independent_git_sources: ' + json.dumps(aggregated['independent_git_sources'], ensure_ascii=False, sort_keys=True))
    if impact.get('coverage') == 'explicit_candidates_only':
        fm.append('impact_coverage: explicit_candidates_only')
    fm.extend(
        [
            f"source_type: {source_type}",
            *([] if request_id else [f"captured_at: {date.isoformat()}", f"verified_at: {date.isoformat()}"]),
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
            fm.extend(f"    - {scalar(page)}" for page in must_update)
        else:
            fm.append("  must_update: []")
        if should_review:
            fm.append("  should_review:")
            fm.extend(f"    - {scalar(page)}" for page in should_review)
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


def _page_catalog(root: Path, config: WikiConfig, candidates: list[str] | None = None,
                  *, candidate_documents: dict | None = None) -> dict[str, dict[str, object]]:
    """Read the legacy catalog or the explicitly selected candidate files."""
    memory_root = root / config.paths["memory_root"]
    catalog: dict[str, dict[str, object]] = {}
    if candidates is None:
        if candidate_documents is not None:
            raise ValueError('candidate documents require explicit candidates')
        files = sorted(wiki_markdown_files(memory_root, wiki_root=root)) if memory_root.is_dir() else []
    else:
        from wiki_core.context_policy import safe_path
        from wiki_core.repo_read import contains_access_secrets
        from wiki_core.traversal import require_wiki_path
        if len(candidates) > 128 or contains_access_secrets(candidates):
            raise ValueError('candidate limit exceeded')
        refs = [safe_path(ref) for ref in candidates]
        if len(refs) != len(set(refs)):
            raise ValueError('duplicate candidate')
        if candidate_documents is not None and (not isinstance(candidate_documents, dict)
                or set(candidate_documents) != set(refs)):
            raise ValueError('candidate documents unavailable')
        for ref in refs:
            require_wiki_path(root, ref)
        files = [root / ref for ref in refs]
        if any(path.suffix.lower() != '.md' or (candidate_documents is None and not path.is_file()) for path in files):
            raise ValueError('candidate unavailable')
        if candidate_documents is None and sum(path.stat().st_size for path in files) > 1_000_000:
            raise ValueError('candidate budget exceeded')
    remaining = 1_000_000
    for md in files:
        if candidates is None:
            fm = _read_frontmatter(md)
        else:
            from wiki_core.context_selection import _metadata
            from wiki_core.repo_read import contains_access_secrets
            from wiki_core.traversal import require_wiki_path
            ref = md.relative_to(root).as_posix()
            require_wiki_path(root, ref)
            if candidate_documents is None:
                with md.open('rb') as stream:
                    raw = stream.read(remaining + 1)
            else:
                import hashlib
                document = candidate_documents[ref]
                if not isinstance(document, dict) or not isinstance(document.get('text'), str):
                    raise ValueError('candidate unavailable')
                raw = document['text'].encode('utf-8')
                if (document.get('path') != ref or document.get('content_sha256') != hashlib.sha256(raw).hexdigest()
                        or not isinstance(document.get('revision'), str)
                        or re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', document['revision']) is None
                        or not isinstance(document.get('blob'), str)
                        or re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', document['blob']) is None):
                    raise ValueError('candidate unavailable')
            if len(raw) > remaining:
                raise ValueError('candidate budget exceeded')
            remaining -= len(raw)
            text = raw.decode('utf-8')
            if contains_access_secrets(text):
                raise ValueError('candidate unavailable')
            fm = _metadata({'text': text})
        page_id = str(fm.get("page_id") or "")
        if not page_id:
            if candidates is not None:
                raise ValueError('candidate identity unavailable')
            continue
        if candidates is not None and page_id in catalog:
            raise ValueError('candidate identity ambiguous')
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
    aggregated: dict[str, object], root: Path, config: WikiConfig, paths: WikiPaths,
    *, candidates: list[str] | None = None, candidate_documents: dict | None = None,
) -> dict[str, object]:
    """Build a packet; supplied candidate documents require caller authorization."""
    catalog = _page_catalog(root, config, candidates, candidate_documents=candidate_documents)
    db_path = paths.indexes / "wiki.sqlite"
    packet_warnings: list[str] = ([] if candidates is None else
        ['Only explicit candidates were inspected; global catalog and FTS were not searched.'])
    initial_signature: str | None = None
    signature_error: Exception | None = None

    def fts(query: str, limit: int = 3) -> list[dict[str, object]]:
        nonlocal initial_signature, signature_error
        if candidates is not None or not query.strip():
            return []
        try:
            if not db_path.exists():
                # Check the boundary even for a missing index, without
                # calculating the page signature for an absent database.
                return search(db_path, query, limit=limit, wiki_root=paths.root)
            if signature_error is not None:
                raise signature_error
            if initial_signature is None:
                try:
                    initial_signature = current_page_signature(paths)
                except Exception as exc:
                    signature_error = exc
                    raise
            hits = search(db_path, sanitize_fts_query(query), limit=limit,
                          page_signature=initial_signature, wiki_root=paths.root)
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
        **({'source_hash_sha256': aggregated['source_hash_sha256']}
           if aggregated.get('source_hash_sha256') else {}),
        **({'independent_git_sources': aggregated['independent_git_sources']}
           if aggregated.get('independent_git_sources') else {}),
        **({'candidate_provenance': [{'path': ref, 'revision': candidate_documents[ref]['revision'],
              'blob': candidate_documents[ref]['blob'], 'sha256': candidate_documents[ref]['content_sha256']}
              for ref in candidates]} if candidate_documents is not None else {}),
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
            **({'coverage': 'explicit_candidates_only'} if candidates is not None else {}),
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


def find_event_for_source(paths: WikiPaths, source_id: str, *, root: Path | None = None,
                          request_id: str | None = None) -> Path | None:
    events_dir = paths.ingest_events_dir
    if root is not None:
        from wiki_core.traversal import require_wiki_boundaries
        require_wiki_boundaries(root, directories=(events_dir,))
    if not events_dir.is_dir():
        return None
    if request_id is not None:
        import hashlib
        if not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id):
            raise ValueError('invalid contextual request identity')
        source_digest = hashlib.sha256(source_id.encode()).hexdigest()
        candidates = events_dir.glob(f'*-{source_digest}-{request_id}.md')
    else:
        candidates = events_dir.glob("*.md")
    found = None
    for md in sorted(candidates):
        if md.name == "README.md":
            continue
        if root is not None:
            require_wiki_boundaries(root, files=(md,))
        fm = _read_frontmatter(md)
        if str(fm.get("source_id") or "") == source_id and fm.get('folder_request_id') == request_id:
            if request_id is None:
                return md  # Preserve the historical source-only lookup.
            if found is not None:
                raise ValueError('ambiguous contextual ingestion events')
            found = md
    return found


def pending_consolidations(root: Path, config: WikiConfig) -> list[dict[str, object]]:
    """Sources with a COMPLETE deep read whose consolidation is not closed.

    States reported: missing_event (no event references the source_id) and
    missing_consolidated_into (event exists but integration not closed).
    """
    paths = WikiPaths(root, config)
    cache_dir = paths.llm_cache
    out: list[dict[str, object]] = []
    for request in load_requests(paths, root=root):
        source_id = str(request.get("source_id"))
        from wiki_core.llm.context_pass import is_local_folder_request
        if is_local_folder_request(request) and not request.get('folder_request_id'):
            out.append({'source_id': source_id, 'state': 'local_request_requires_reemit'})
            continue
        if not deep_read_complete(request, cache_dir, root=root):
            continue  # the context-pass gate already covers incomplete reads
        request_id = request.get('folder_request_id')
        event = find_event_for_source(paths, source_id, root=root, request_id=request_id)
        if event is None:
            out.append({"source_id": source_id, **({'folder_request_id': request_id} if request_id else {}), "state": "missing_event"})
            continue
        fm = _read_frontmatter(event)
        consolidated = fm.get("consolidated_into")
        if not isinstance(consolidated, list) or not consolidated:
            out.append(
                {
                    "source_id": source_id,
                    **({'folder_request_id': request_id} if request_id else {}),
                    "state": "missing_consolidated_into",
                    "event": event.relative_to(root).as_posix(),
                }
            )
    return out
