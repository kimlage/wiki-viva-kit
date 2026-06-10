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

from wiki_core.config import load_config
from wiki_core.detectors import scan_file
from wiki_core.gate import rebase_pending
from wiki_core.source_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[1]
INGEST_DIR = ROOT / "memorias/sistema/ingestao"

# PROPOSAL string table per language (drives the generated output via config.language).
PROPOSAL_STRINGS: dict[str, dict[str, str]] = {
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
        "row_event": "- Evento esperado (a criar) em [eventos/](eventos/README.md): arquivo `{event_file}`.",
        "row_llm": "- Passagem LLM contextual: pendente ou cacheada conforme [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py).",
        "h_quadrants": "## Quadrantes",
        "th_quadrants": "| Quadrante | Conteudo extraido | Ausencia/limite |",
        "quad_ii": "| Interior individual | A preencher apos leitura contextual. | Explicitar se ausente. |",
        "quad_ei": "| Exterior individual | Metadados da fonte ja registrados. | Conteudo depende de extracao. |",
        "quad_ic": "| Interior coletivo | A preencher apos leitura contextual. | Explicitar se ausente. |",
        "quad_ec": "| Exterior coletivo | Gate por PR e paginas impactadas ja previstos. | Sistema afetado depende da consolidacao. |",
        "h_synthesis": "## Sintese proposta",
        "synthesis_note": "- Proposta gerada por metadados; revisar a fonte e extrair conteudo privado quando isso melhorar memoria operacional.",
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
        "row_event": "- Expected event (to create) in [eventos/](eventos/README.md): file `{event_file}`.",
        "row_llm": "- Contextual LLM pass: pending or cached per [scripts/wiki_llm_context_pass.py](../../../scripts/wiki_llm_context_pass.py).",
        "h_quadrants": "## Quadrants",
        "th_quadrants": "| Quadrant | Extracted content | Absence/limit |",
        "quad_ii": "| Interior individual | To fill in after contextual reading. | State if absent. |",
        "quad_ei": "| Exterior individual | Source metadata already recorded. | Content depends on extraction. |",
        "quad_ic": "| Interior collective | To fill in after contextual reading. | State if absent. |",
        "quad_ec": "| Exterior collective | PR gate and impacted pages already foreseen. | Affected system depends on consolidation. |",
        "h_synthesis": "## Proposed synthesis",
        "synthesis_note": "- Proposal generated from metadata; review the source and extract private content when it improves operational memory.",
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


def _load_targets(root: Path) -> dict[str, dict[str, list[str]]]:
    """Load the context -> pages/entities map from wiki.targets.yaml (the repo's
    local profile). Keeps the script generic: repo-specific entities live outside
    the code, in a per-repo profile file."""
    default = {"sistema": {"pages": ["memorias/index.md"], "entities": ["holon-sistema"]}}
    path = root / "wiki.targets.yaml"
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    targets = {
        str(ctx): {"pages": list(spec.get("pages", [])), "entities": list(spec.get("entities", []))}
        for ctx, spec in data.items()
        if isinstance(spec, dict)
    }
    return targets or default


TARGETS = _load_targets(ROOT)


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "fonte"


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


def repo_link(repo_rel: str, base_dir: Path = INGEST_DIR) -> str:
    href = os.path.relpath(ROOT / repo_rel, base_dir).replace(os.sep, "/")
    href = quote(href, safe="/.-_#")
    return f"[{repo_rel}]({href})"


def source_link(path: Path, base_dir: Path = INGEST_DIR) -> str:
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
        manifest = build_manifest(source, "sistema")
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
    source_name = Path(urlparse(source).path).name or "source"
    page_id = f"ingestao-{date.isoformat()}-{slugify(context)}-{slugify(source_name)}"
    target = TARGETS.get(context, TARGETS["sistema"])
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
            "stale_after_days: 30",
            "sources_policy: proposta_privada_com_links_reais",
            "gate: github_pr",
            "sensitive_data_policy: private_sensitive_allowed",
            f"status: {status}",
            "gate_state: created",
            f"created_at: {date.isoformat()}",
            f"rebase_key: {slugify(context)}-{slugify(source_name)}",
            f"manifest_ref: data/derived/wiki/source-manifests/{source_id}.json",
            f"event_ref: memorias/sistema/ingestao/eventos/{event_file}",
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
            s["row_event"].format(event_file=event_file),
            s["row_llm"],
            "",
            s["h_quadrants"],
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
    parser.add_argument("--context", required=True, choices=sorted(TARGETS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", default="draft")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    args = parser.parse_args()

    date = dt.date.fromisoformat(args.date)
    language = load_config(ROOT).language
    proposal = build_proposal(args.source, args.context, date, args.status, language)
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

    source_name = Path(urlparse(args.source).path).name or "fonte"
    path = INGEST_DIR / f"{date.isoformat()}-{slugify(args.context)}-{slugify(source_name)}.md"
    if path.exists():
        print(f"Refusing to overwrite existing proposal: {path}", file=sys.stderr)
        return 1
    path.write_text(proposal, encoding="utf-8")
    print(path)
    # Rebase: supersede earlier pending proposals for the same logical target.
    rebase_key = f"{slugify(args.context)}-{slugify(source_name)}"
    result = rebase_pending(INGEST_DIR, rebase_key=rebase_key)
    for superseded in result.get("superseded", []):
        print(f"superseded: {Path(superseded).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
