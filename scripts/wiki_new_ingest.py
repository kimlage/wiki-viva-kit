#!/usr/bin/env python3
"""Create a private wiki ingestion proposal."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wiki_core.config import freshness_for, load_config
from wiki_core.detectors import scan_file
from wiki_core.gate import rebase_pending
from wiki_core.paths import WikiPaths
from wiki_core.source_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[1]
# Repo layout comes from wiki.config.yaml (English defaults; localized repos pin
# their own names). Tests may swap CONFIG/PATHS to exercise another layout.
CONFIG = load_config(ROOT)
PATHS = WikiPaths(ROOT, CONFIG)

# FUNCTIONAL fallback for a source whose URL/path yields no file name. It feeds
# page_id, rebase_key, event_file and the proposal file name, so build_proposal
# and main() MUST agree on it (a divergence breaks the rebase/supersede match).
DEFAULT_SOURCE_NAME = "source"

# PROPOSAL string table per language (drives the generated output via config.language).
PROPOSAL_STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "risk_url": "comprobar la vigencia de la fuente antes de consolidar",
        "risk_raw_local": "el archivo local puede contener datos sin procesar o estructurados; tratarlo como privado por defecto",
        "risk_raw_doc": "privado por defecto; los datos personales son bienvenidos en la memoria, redactar solo antes de exportar",
        "risk_artifact": "el tipo de fuente requiere clasificación manual",
        "risk_none": "la clasificación automática no identificó riesgos adicionales",
        "risk_secret_header": "Secretos de acceso detectados (BLOQUEAN hasta que se eliminen):",
        "risk_pii_header": "Datos personales detectados (admitidos en una página privada; redactar solo antes de exportar):",
        "rec_memory": "evaluar la síntesis y consolidarla en el hub de contexto mediante un PR",
        "rec_reference": "mantener como referencia o citar solo si la fuente es estable",
        "rec_artifact": "mantener como artefacto operativo y consolidar solo lo que cambie el comportamiento",
        "rec_raw": "leer la fuente original cuando sea necesario y extraer fragmentos privados útiles, conservando el enlace original",
        "rec_no_ingest": "no ingerir",
        "meta_type_url": "- Tipo: URL externa",
        "meta_content_note": "- Contenido: no copiado automáticamente; la extracción privada depende de la lectura dirigida.",
        "meta_path": "- Ruta: {link}",
        "meta_type_file": "- Tipo: archivo `{suffix}`",
        "meta_size": "- Tamaño: {size} bytes",
        "meta_path_provided": "- Ruta proporcionada: {path}",
        "meta_not_found": "- Estado: archivo no encontrado al crear la propuesta",
        "prop_title": "# Propuesta de ingestión - {name}",
        "prop_updated": "Actualizado el: {date}",
        "h_source": "## Fuente consultada",
        "h_target_context": "## Contexto de destino",
        "h_classification": "## Clasificación",
        "row_type": "- Tipo: `{type}`",
        "row_epistemic": "- Estado epistémico: `proposal`",
        "h_event": "## Evento normalizado",
        "row_manifest": "- Manifiesto esperado: [data/derived/wiki/source-manifests/{sid}.json](../../../data/derived/wiki/source-manifests/{sid}.json)",
        "row_chunks": "- Texto/chunks esperados: [data/derived/wiki/chunks/{sid}.json](../../../data/derived/wiki/chunks/{sid}.json)",
        "row_event": "- Evento esperado (a crear) en [{events_dir}/]({events_dir}/README.md): archivo `{event_file}`.",
        "row_llm": "- Pasada LLM contextual: pendiente o en caché mediante [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py).",
        "h_quadrants": "## Cuadrantes",
        "th_quadrants": "| Cuadrante | Contenido extraído | Ausencia/límite |",
        "quad_ii": "| Interior individual |  |  |",
        "quad_ei": "| Exterior individual |  |  |",
        "quad_ic": "| Interior colectivo |  |  |",
        "quad_ec": "| Exterior colectivo |  |  |",
        "pending": "<!-- pendiente: se completa mediante la lectura profunda contextual (consulte el evento normalizado) -->",
        "h_synthesis": "## Síntesis propuesta",
        "synthesis_note": "<!-- pendiente: se completa mediante la lectura profunda contextual (consulte el evento normalizado) -->",
        "h_pages": "## Páginas afectadas",
        "h_entities": "## Entidades afectadas",
        "h_risks": "## Riesgos de privacidad",
        "h_decision": "## Decisión recomendada",
        "h_checklist": "## Lista de verificación",
        "chk_1": "- [ ] Trató la fuente como privada por defecto; promoverla a pública requiere redacción y un gate.",
        "chk_2": "- [ ] No copió un volcado completo sin criterio.",
        "chk_3": "- [ ] No copió tokens, cookies, contraseñas, códigos de acceso, credenciales ni enlaces seguros individualizados.",
        "chk_4": "- [ ] Indicó la fuente y el contexto.",
        "chk_5": "- [ ] Indicó las páginas afectadas.",
        "chk_6": "- [ ] Escribió las rutas locales como enlaces Markdown navegables.",
        "chk_7": "- [ ] Indicó el gate de PR.",
        "chk_8": "- [ ] Completó los cuadrantes o declaró su ausencia.",
        "chk_9": "- [ ] Indicó el manifiesto, los chunks y la aprobación LLM contextual o una justificación.",
    },
    "pt": {
        "risk_url": "verificar frescor da fonte antes de consolidar",
        "risk_raw_local": "arquivo local pode conter dados brutos ou estruturados; tratados como privado por padrao",
        "risk_raw_doc": "privado por padrao; dados pessoais sao bem-vindos na memoria, redigir so antes de exportar",
        "risk_artifact": "tipo de fonte exige triagem manual",
        "risk_none": "nenhum risco adicional identificado pela triagem automatica",
        "risk_secret_header": "Segredos de acesso detectados (BLOQUEIA ate remover):",
        "risk_pii_header": "Dados pessoais detectados (ok em pagina privada; redigir so antes de exportar):",
        "rec_memory": "avaliar sintese e consolidar no hub de contexto via PR",
        "rec_reference": "preservar como referencia ou citar apenas se a fonte for estavel",
        "rec_artifact": "manter como artefato operacional e consolidar somente o que muda comportamento",
        "rec_raw": "ler a fonte original quando necessario e extrair recortes privados uteis, mantendo o original linkado",
        "rec_no_ingest": "nao ingerir",
        "meta_type_url": "- Tipo: URL externa",
        "meta_content_note": "- Conteudo: nao copiado automaticamente; extracao privada depende de leitura dirigida",
        "meta_path": "- Caminho: {link}",
        "meta_type_file": "- Tipo: arquivo `{suffix}`",
        "meta_size": "- Tamanho: {size} bytes",
        "meta_path_provided": "- Caminho informado: {path}",
        "meta_not_found": "- Estado: arquivo nao encontrado no momento da proposta",
        "prop_title": "# Proposta de ingestao - {name}",
        "prop_updated": "Atualizado em: {date}",
        "h_source": "## Fonte consultada",
        "h_target_context": "## Contexto alvo",
        "h_classification": "## Classificacao",
        "row_type": "- Tipo: `{type}`",
        "row_epistemic": "- Status epistemologico: `proposta`",
        "h_event": "## Evento normalizado",
        "row_manifest": "- Manifesto esperado: [data/derived/wiki/source-manifests/{sid}.json](../../../data/derived/wiki/source-manifests/{sid}.json)",
        "row_chunks": "- Texto/chunks esperados: [data/derived/wiki/chunks/{sid}.json](../../../data/derived/wiki/chunks/{sid}.json)",
        "row_event": "- Evento esperado (a criar) em [{events_dir}/]({events_dir}/README.md): arquivo `{event_file}`.",
        "row_llm": "- Passagem LLM contextual: pendente ou cacheada conforme [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py).",
        "h_quadrants": "## Quadrantes",
        "th_quadrants": "| Quadrante | Conteudo extraido | Ausencia/limite |",
        "quad_ii": "| Interior individual |  |  |",
        "quad_ei": "| Exterior individual |  |  |",
        "quad_ic": "| Interior coletivo |  |  |",
        "quad_ec": "| Exterior coletivo |  |  |",
        "pending": "<!-- pendente: preenchido pela leitura contextual profunda (ver evento normalizado) -->",
        "h_synthesis": "## Sintese proposta",
        "synthesis_note": "<!-- pendente: preenchido pela leitura contextual profunda (ver evento normalizado) -->",
        "h_pages": "## Paginas impactadas",
        "h_entities": "## Entidades impactadas",
        "h_risks": "## Riscos de privacidade",
        "h_decision": "## Decisao recomendada",
        "h_checklist": "## Checklist",
        "chk_1": "- [ ] Tratou a fonte como privada por padrao; promocao a publico exige redacao e gate.",
        "chk_2": "- [ ] Nao copiou dump integral sem criterio.",
        "chk_3": "- [ ] Nao copiou token, cookie, senha, codigo de acesso, credencial ou link seguro individualizado.",
        "chk_4": "- [ ] Indicou fonte e contexto.",
        "chk_5": "- [ ] Indicou paginas impactadas.",
        "chk_6": "- [ ] Caminhos locais foram escritos como links Markdown clicaveis.",
        "chk_7": "- [ ] Indicou gate por PR.",
        "chk_8": "- [ ] Preencheu quadrantes ou explicitou ausencia.",
        "chk_9": "- [ ] Indicou manifesto, chunks e passagem LLM contextual ou justificativa.",
    },
    "en": {
        "risk_url": "check source freshness before consolidating",
        "risk_raw_local": "local file may contain raw or structured data; treated as private by default",
        "risk_raw_doc": "private by default; personal data is welcome in memory, redact only before exporting",
        "risk_artifact": "source type requires manual triage",
        "risk_none": "no additional risk identified by automatic triage",
        "risk_secret_header": "Access secrets detected (BLOCKS until removed):",
        "risk_pii_header": "Personal data detected (ok on a private page; redact only before exporting):",
        "rec_memory": "evaluate the synthesis and consolidate into the context hub via PR",
        "rec_reference": "keep as reference or cite only if the source is stable",
        "rec_artifact": "keep as an operational artifact and consolidate only what changes behavior",
        "rec_raw": "read the original source when needed and extract useful private excerpts, keeping the original linked",
        "rec_no_ingest": "do not ingest",
        "meta_type_url": "- Type: external URL",
        "meta_content_note": "- Content: not copied automatically; private extraction depends on directed reading",
        "meta_path": "- Path: {link}",
        "meta_type_file": "- Type: `{suffix}` file",
        "meta_size": "- Size: {size} bytes",
        "meta_path_provided": "- Provided path: {path}",
        "meta_not_found": "- State: file not found at proposal time",
        "prop_title": "# Ingestion proposal - {name}",
        "prop_updated": "Updated at: {date}",
        "h_source": "## Source consulted",
        "h_target_context": "## Target context",
        "h_classification": "## Classification",
        "row_type": "- Type: `{type}`",
        "row_epistemic": "- Epistemic status: `proposal`",
        "h_event": "## Normalized event",
        "row_manifest": "- Expected manifest: [data/derived/wiki/source-manifests/{sid}.json](../../../data/derived/wiki/source-manifests/{sid}.json)",
        "row_chunks": "- Expected text/chunks: [data/derived/wiki/chunks/{sid}.json](../../../data/derived/wiki/chunks/{sid}.json)",
        "row_event": "- Expected event (to create) in [{events_dir}/]({events_dir}/README.md): file `{event_file}`.",
        "row_llm": "- Contextual LLM pass: pending or cached per [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py).",
        "h_quadrants": "## Quadrants",
        "th_quadrants": "| Quadrant | Extracted content | Absence/limit |",
        "quad_ii": "| Interior individual |  |  |",
        "quad_ei": "| Exterior individual |  |  |",
        "quad_ic": "| Interior collective |  |  |",
        "quad_ec": "| Exterior collective |  |  |",
        "pending": "<!-- pending: filled by the contextual deep-read (see the normalized event) -->",
        "h_synthesis": "## Proposed synthesis",
        "synthesis_note": "<!-- pending: filled by the contextual deep-read (see the normalized event) -->",
        "h_pages": "## Impacted pages",
        "h_entities": "## Impacted entities",
        "h_risks": "## Privacy risks",
        "h_decision": "## Recommended decision",
        "h_checklist": "## Checklist",
        "chk_1": "- [ ] Treated the source as private by default; promotion to public requires redaction and a gate.",
        "chk_2": "- [ ] Did not copy a full dump without criteria.",
        "chk_3": "- [ ] Did not copy a token, cookie, password, access code, credential, or individualized secure link.",
        "chk_4": "- [ ] Indicated source and context.",
        "chk_5": "- [ ] Indicated impacted pages.",
        "chk_6": "- [ ] Local paths were written as clickable Markdown links.",
        "chk_7": "- [ ] Indicated the PR gate.",
        "chk_8": "- [ ] Filled the quadrants or stated their absence.",
        "chk_9": "- [ ] Indicated manifest, chunks, and contextual LLM pass or a justification.",
    },
}


def _ps(language: str) -> dict[str, str]:
    return PROPOSAL_STRINGS.get(language, PROPOSAL_STRINGS["en"])


def _minimal_target() -> dict[str, list[str]]:
    """Synthesized fallback target: the memory index page, no entities. Used when
    wiki.targets.yaml is absent or does not cover the requested context — the
    proposal must still be generated (it degrades, it does not crash)."""
    return {"pages": [PATHS.rel(PATHS.memory_root / "index.md")], "entities": []}


def _load_targets(root: Path) -> dict[str, dict[str, list[str]]]:
    """Load the context -> pages/entities map from wiki.targets.yaml (the repo's
    local profile). Keeps the script generic: repo-specific entities live outside
    the code, in a per-repo profile file."""
    path = root / "wiki.targets.yaml"
    if not path.exists():
        return {CONFIG.default_context: _minimal_target()}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    targets = {
        str(ctx): {"pages": list(spec.get("pages", [])), "entities": list(spec.get("entities", []))}
        for ctx, spec in data.items()
        if isinstance(spec, dict)
    }
    return targets or {CONFIG.default_context: _minimal_target()}


TARGETS = _load_targets(ROOT)


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or DEFAULT_SOURCE_NAME


def classify_source(source: str, s: dict[str, str]) -> tuple[str, list[str]]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return "reference", [s["risk_url"]]

    path = Path(source).expanduser()
    suffix = path.suffix.lower()
    raw_markers = {"data/raw", "data/derived"}
    if any(marker in str(path) for marker in raw_markers):
        return "raw", [s["risk_raw_local"]]
    if suffix in {".pdf", ".csv", ".xlsx", ".xls", ".json", ".tsv"}:
        return "raw", [s["risk_raw_doc"]]
    if suffix in {".md", ".txt"}:
        return "memory", []
    return "artifact", [s["risk_artifact"]]


def repo_link(repo_rel: str, base_dir: Path | None = None) -> str:
    # Default base resolved at call time (not def time) so a swapped PATHS in
    # tests keeps links consistent with the configured ingest directory.
    base_dir = base_dir or PATHS.ingest_dir
    href = os.path.relpath(ROOT / repo_rel, base_dir).replace(os.sep, "/")
    href = quote(href, safe="/.-_#")
    return f"[{repo_rel}]({href})"


def source_link(path: Path, base_dir: Path | None = None) -> str:
    base_dir = base_dir or PATHS.ingest_dir
    resolved = path.expanduser().resolve()
    try:
        repo_rel = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        href = os.path.relpath(resolved, base_dir).replace(os.sep, "/")
        href = quote(href, safe="/.-_#")
        return f"[{path}]({href})"
    return repo_link(repo_rel, base_dir)


def source_metadata(source: str, s: dict[str, str]) -> list[str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return [
            f"- URI: [{source}]({source})",
            s["meta_type_url"],
            s["meta_content_note"],
        ]
    path = Path(source).expanduser()
    if path.exists():
        rows = [s["meta_path"].format(link=source_link(path))]
        stat = path.stat()
        rows.append(s["meta_type_file"].format(suffix=path.suffix or "no extension"))
        rows.append(s["meta_size"].format(size=stat.st_size))
        manifest = build_manifest(source, CONFIG.default_context)
        if manifest.get("hash_sha256"):
            rows.append(f"- SHA256: `{manifest['hash_sha256']}`")
    else:
        rows = [s["meta_path_provided"].format(path=path.expanduser())]
        rows.append(s["meta_not_found"])
    rows.append(s["meta_content_note"])
    return rows


def build_proposal(source: str, context: str, date: dt.date, status: str, language: str = "en") -> str:
    s = _ps(language)
    source_type, risks = classify_source(source, s)
    source_name = Path(urlparse(source).path).name or DEFAULT_SOURCE_NAME
    # The page_id prefix follows the configured ingest dirname, so a localized
    # repo (e.g. pt: "ingestao") keeps generating ids in its own vocabulary.
    page_id = f"{CONFIG.paths['ingest_dirname']}-{date.isoformat()}-{slugify(context)}-{slugify(source_name)}"
    # Unknown context must not crash proposal generation: fall back to the
    # configured default context's target, then to a synthesized minimal one.
    target = TARGETS.get(context) or TARGETS.get(CONFIG.default_context) or _minimal_target()
    target_pages = target["pages"]
    target_entities = target["entities"]
    risk_rows = risks or [s["risk_none"]]
    # Pre-triage at capture: access secrets BLOCK (real risk, anywhere); personal
    # data (PII) is only REPORTED -- welcome on a private page (operational memory),
    # just redact before exporting/publishing.
    _src_path = Path(source).expanduser()
    _findings = scan_file(_src_path) if _src_path.is_file() else []
    secret_rows = [f"`{f.kind}` (line {f.line}): {f.excerpt}" for f in _findings if f.category == "secret"]
    pii_rows = [f"`{f.kind}` (line {f.line}): {f.excerpt}" for f in _findings if f.category == "pii"]
    if secret_rows:
        risk_rows = risk_rows + [s["risk_secret_header"]] + secret_rows
    if pii_rows:
        risk_rows = risk_rows + [s["risk_pii_header"]] + pii_rows
    manifest = build_manifest(source, context)
    source_id = str(manifest["source_id"])
    recommendation = {
        "memory": s["rec_memory"],
        "reference": s["rec_reference"],
        "artifact": s["rec_artifact"],
        "raw": s["rec_raw"],
        "no_ingest": s["rec_no_ingest"],
    }[source_type]
    event_file = f"{date.isoformat()}-{slugify(context)}-{slugify(source_name)}.md"

    return "\n".join(
        [
            "---",
            f"page_id: {page_id}",
            "page_type: source_catalog",
            f"context: {context}",
            "visibility: private_self",
            f"updated_at: {date.isoformat()}",
            f"stale_after_days: {freshness_for(context, 'source_catalog', CONFIG)}",
            "sources_policy: proposta_privada_com_links_reais",
            "gate: github_pr",
            "sensitive_data_policy: private_sensitive_allowed",
            f"status: {status}",
            "gate_state: created",
            f"created_at: {date.isoformat()}",
            f"rebase_key: {slugify(context)}-{slugify(source_name)}",
            f"manifest_ref: {PATHS.rel(PATHS.source_manifests / f'{source_id}.json')}",
            f"event_ref: {PATHS.rel(PATHS.ingest_events_dir / event_file)}",
            "llm_context_status: pending",
            "---",
            "",
            s["prop_title"].format(name=source_name),
            "",
            s["prop_updated"].format(date=date.isoformat()),
            "",
            s["h_source"],
            "",
            *source_metadata(source, s),
            "",
            s["h_target_context"],
            "",
            f"- `{context}`",
            "",
            s["h_classification"],
            "",
            s["row_type"].format(type=source_type),
            s["row_epistemic"],
            "",
            s["h_event"],
            "",
            s["row_manifest"].format(sid=source_id),
            s["row_chunks"].format(sid=source_id),
            s["row_event"].format(
                event_file=event_file, events_dir=CONFIG.paths["events_dirname"]
            ),
            s["row_llm"],
            "",
            s["h_quadrants"],
            "",
            s["pending"],
            "",
            s["th_quadrants"],
            "| --- | --- | --- |",
            s["quad_ii"],
            s["quad_ei"],
            s["quad_ic"],
            s["quad_ec"],
            "",
            s["h_synthesis"],
            "",
            s["synthesis_note"],
            "",
            s["h_pages"],
            "",
            *[f"- {repo_link(page)}" for page in target_pages],
            "",
            s["h_entities"],
            "",
            *[f"- `{entity}`" for entity in target_entities],
            "",
            s["h_risks"],
            "",
            *[f"- {risk}" for risk in risk_rows],
            "",
            s["h_decision"],
            "",
            f"- {recommendation}.",
            "",
            s["h_checklist"],
            "",
            s["chk_1"], s["chk_2"], s["chk_3"], s["chk_4"], s["chk_5"],
            s["chk_6"], s["chk_7"], s["chk_8"], s["chk_9"],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument(
        "--context",
        default=CONFIG.default_context,
        choices=sorted(set(TARGETS) | {CONFIG.default_context}),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", default="draft")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date)
    proposal = build_proposal(args.source, args.context, date, args.status, CONFIG.language)
    src_path = Path(args.source).expanduser()
    secrets = [f for f in scan_file(src_path) if f.category == "secret"] if src_path.is_file() else []
    if args.dry_run:
        print(proposal)
        return 2 if secrets else 0
    if secrets:
        print(
            f"BLOCKED: {len(secrets)} secret(s) in the source; remove before proposing.",
            file=sys.stderr,
        )
        return 2

    source_name = Path(urlparse(args.source).path).name or DEFAULT_SOURCE_NAME
    ingest_dir = PATHS.ingest_dir
    if not ingest_dir.is_dir():
        # Fail loud: a missing configured ingest directory means the layout in
        # wiki.config.yaml does not match the repo — never write blind.
        print(f"ERROR: configured ingest directory does not exist: {ingest_dir}", file=sys.stderr)
        return 1
    path = ingest_dir / f"{date.isoformat()}-{slugify(args.context)}-{slugify(source_name)}.md"
    if path.exists():
        print(f"Refusing to overwrite existing proposal: {path}", file=sys.stderr)
        return 1
    path.write_text(proposal, encoding="utf-8")
    print(path)
    # Rebase: supersede earlier pending proposals for the same logical target.
    rebase_key = f"{slugify(args.context)}-{slugify(source_name)}"
    result = rebase_pending(ingest_dir, rebase_key=rebase_key)
    for superseded in result.get("superseded", []):
        print(f"superseded: {Path(superseded).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
