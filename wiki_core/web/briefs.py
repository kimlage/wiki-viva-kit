"""Work-brief composer — the boundary object between the operator and an agent.

A *work brief* is a complete, human-readable prompt assembled DETERMINISTICALLY
from the state of the wiki: the conventions an agent must follow, the concrete
evidence for *why* the work exists (the same numbers the cockpit shows), the
targets, the operator's intent, and a pinned output contract. The operator reads
it, edits it, and chooses an exit — copy it into any agent, save it, or (Phase 2)
execute it locally with Codex.

Two hard rules shape this module:

* **Zero tokens, no subprocess, no LLM.** The composer only reads the snapshot
  payloads + page files already on disk and concatenates them. Determinism is a
  feature: the same spec against the same snapshot yields byte-identical text
  (and therefore the same ``brief_sha``), which is what makes "what you saw is
  what ran" verifiable at launch. The generation timestamp is NEVER embedded —
  the header cites the *snapshot's* ``generated_at`` instead.

* **Never invent.** Every evidence line names its provenance (which snapshot
  file/field produced it). A file that does not exist is not referenced.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig
from wiki_core.paths import WikiPaths
from wiki_core.web.content import build_page_content

BRIEF_SCHEMA_VERSION = "wiki_web_brief.v1"

_MISSION_KINDS = {"refresh", "verify", "evidence", "ingest", "state", None}
_MATERIALIZE = {"refs", "full"}
_THEME_RE = re.compile(r"[^a-z0-9]+")
_BODY_EXCERPT_CHARS = 1600
_STATE_LIMIT_DEFAULT = 6
_STATE_LIMIT_MAX = 20

# Content-family page types that are expected to cite a source (drives the
# "evidence" state selector). Mirrors the spirit of the cockpit's raw/source
# distinction without importing presentation config.
_CONTENT_LIKE = {
    "context_note",
    "context_hub",
    "concept",
    "process",
    "decision",
    "journal_entry",
    "relationship_map",
}


# --------------------------------------------------------------------------- #
# Spec normalization
# --------------------------------------------------------------------------- #
def sanitize_theme(theme: str, *, fallback: str = "update") -> str:
    """Lowercase slug for ``wiki/<theme>``; git_workflows sanitizes again at
    branch time, this is only for display in the brief."""
    slug = _THEME_RE.sub("-", str(theme or "").lower()).strip("-")
    slug = slug[:48].strip("-")
    return slug or fallback


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    spec = spec or {}
    mission_kind = spec.get("mission_kind")
    if mission_kind not in _MISSION_KINDS:
        mission_kind = None
    grounding = spec.get("grounding") or {}
    page_ids = [str(p) for p in (grounding.get("page_ids") or []) if str(p).strip()]
    source = grounding.get("source") or None
    if source is not None and not isinstance(source, dict):
        source = None
    state_report = grounding.get("state_report") or None
    if state_report is not None:
        if not isinstance(state_report, dict):
            state_report = None
        else:
            scope = state_report.get("scope")
            if scope not in {"missions", "quality", "audit"}:
                state_report = None
            else:
                limit = state_report.get("limit")
                try:
                    limit = int(limit)
                except (TypeError, ValueError):
                    limit = _STATE_LIMIT_DEFAULT
                state_report = {
                    "scope": scope,
                    "context": (str(state_report["context"]) if state_report.get("context") else None),
                    "limit": max(1, min(limit, _STATE_LIMIT_MAX)),
                }
    # Return/resume grounding: continue an existing proposal branch rather than
    # opening a new one (the "hand it back with feedback" loop).
    resume = grounding.get("resume") or None
    if resume is not None:
        if not isinstance(resume, dict) or not resume.get("branch"):
            resume = None
        else:
            resume = {
                "branch": str(resume["branch"]),
                "parent_job_id": (str(resume["parent_job_id"]) if resume.get("parent_job_id") else None),
            }
    materialize = spec.get("materialize")
    if materialize not in _MATERIALIZE:
        materialize = "refs"
    fallback_theme = mission_kind or "update"
    return {
        "mission_kind": mission_kind,
        "grounding": {
            "page_ids": page_ids,
            "source": ({"path": str(source.get("path") or source.get("url") or ""),
                        "context": (str(source.get("context")) if source.get("context") else None)}
                       if source else None),
            "attach_context_package": bool(grounding.get("attach_context_package")),
            "state_report": state_report,
            "resume": resume,
        },
        "intent": str(spec.get("intent") or "").strip(),
        "theme": sanitize_theme(spec.get("theme") or "", fallback=fallback_theme),
        "materialize": materialize,
    }


# --------------------------------------------------------------------------- #
# Small deterministic helpers
# --------------------------------------------------------------------------- #
def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _overdue_days(page: dict[str, Any], ref: date | None) -> int | None:
    if ref is None:
        return None
    updated = _parse_date(page.get("updated_at", ""))
    if updated is None:
        return None
    try:
        window = int(page.get("stale_after_days") or 0)
    except (TypeError, ValueError):
        return None
    if window <= 0:
        return None
    overdue = (ref - updated).days - window
    return overdue if overdue > 0 else None


def _fence(text: str, lang: str = "") -> str:
    body = text.rstrip("\n")
    return f"```{lang}\n{body}\n```"


def _read_if_exists(root: Path, rel: str) -> str | None:
    path = (root / rel)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #
def _section_conventions(root: Path, config: WikiConfig, materialize: str, ingest: bool) -> str:
    prefix = str(config.approval.get("branch_prefix", "wiki/"))
    lines = ["## 1 · Conventions — the rules you operate under", ""]
    files = [
        ("AGENTS.md", "the canonical operating brief for agents in this repo"),
        ("wiki.config.yaml", f"contexts, approval gate (branch prefix `{prefix}`, draft PR), visibility"),
        ("wiki.page-types.yaml", "the frontmatter contract; create typed pages via scripts/wiki_new.py, never blank files"),
    ]
    present = [(rel, note) for rel, note in files if (root / rel).is_file()]
    for rel, note in present:
        lines.append(f"- `{rel}` — {note}.")
    skills = ["`wiki-viva` (\"Hard rules\")"]
    if ingest:
        skills.append("`wiki-ingestion-agent` + `wiki-llm-context-agent` (ingest flow)")
    lines.append(f"- Skills: {', '.join(skills)}.")
    if materialize == "full":
        lines.append("")
        for rel, _ in present:
            text = _read_if_exists(root, rel)
            if text is None:
                continue
            lang = "yaml" if rel.endswith((".yaml", ".yml")) else "markdown"
            lines.append(f"<details><summary>{rel}</summary>\n\n{_fence(text, lang)}\n\n</details>")
    else:
        lines.append("")
        lines.append("_(Referenced by path — read them in the repo. Ask for `materialize: full` to embed them.)_")
    return "\n".join(lines)


def _page_evidence_line(page: dict[str, Any], ref: date | None) -> list[str]:
    title = str(page.get("title") or page.get("id") or "?")
    pid = str(page.get("id") or "")
    state = str(page.get("freshness_state") or "unknown")
    updated = str(page.get("updated_at") or "—")
    window = str(page.get("stale_after_days") or "—")
    overdue = _overdue_days(page, ref)
    bits = [f"freshness_state={state}", f"updated_at={updated}", f"stale_after_days={window}"]
    if overdue is not None:
        bits.append(f"~{overdue}d past its window")
    refs = page.get("source_refs") or []
    bits.append(f"source_refs={len(refs)}")
    risks = page.get("risk_flags") or []
    if risks:
        bits.append(f"risk_flags={','.join(str(r) for r in risks)}")
    approved = str(page.get("approved_state") or "")
    if approved and approved != "approved":
        bits.append(f"approved_state={approved}")
    return [f"- **{title}** (`{pid}`): " + "; ".join(bits) + ".  _[pages.json / freshness.json]_"]


def _select_state_pages(
    snapshot: dict[str, dict[str, Any]], scope: str, context: str | None, limit: int
) -> list[dict[str, Any]]:
    pages = list(snapshot.get("pages.json", {}).get("pages", []))
    if context:
        pages = [p for p in pages if str(p.get("context")) == context]
    if scope in {"missions", "audit"}:
        stale = [p for p in pages if str(p.get("freshness_state")) == "stale"]
        unknown = [p for p in pages if str(p.get("freshness_state")) == "unknown"]
        no_evidence = [
            p
            for p in pages
            if str(p.get("page_type")) in _CONTENT_LIKE and not (p.get("source_refs") or [])
        ]
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in (stale, no_evidence, unknown):
            for p in group:
                pid = str(p.get("id"))
                if pid not in seen:
                    seen.add(pid)
                    ordered.append(p)
        return ordered[:limit]
    # quality scope: lowest information density first
    quality_pages = {str(p.get("path")): p for p in snapshot.get("quality.json", {}).get("pages", [])}
    def density(p: dict[str, Any]) -> float:
        qp = quality_pages.get(str(p.get("path")), {})
        try:
            return float(qp.get("information_density_per_1000_words", 1e9))
        except (TypeError, ValueError):
            return 1e9
    return sorted(pages, key=density)[:limit]


def _section_state(
    snapshot: dict[str, dict[str, Any]],
    ref: date | None,
    *,
    page_ids: list[str],
    state_report: dict[str, Any] | None,
    index: dict[str, dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    lines = ["## 2 · State of the wiki — deterministic evidence", ""]
    fresh = snapshot.get("freshness.json", {}).get("summary", {})
    lines.append(
        f"- Freshness across the wiki: {fresh.get('fresh', 0)} fresh · "
        f"{fresh.get('stale', 0)} stale · {fresh.get('unknown', 0)} without data.  _[freshness.json → summary]_"
    )
    targeted: list[dict[str, Any]] = []
    for pid in page_ids:
        page = index.get(pid)
        if page:
            targeted.append(page)
            lines.extend(_page_evidence_line(page, ref))
    if state_report:
        scope = state_report["scope"]
        picked = _select_state_pages(snapshot, scope, state_report.get("context"), state_report["limit"])
        ctx = f" · context `{state_report['context']}`" if state_report.get("context") else ""
        lines.append("")
        lines.append(f"- Top {len(picked)} problem page(s) for scope `{scope}`{ctx}:")
        for page in picked:
            targeted.append(page)
            lines.extend("  " + ln for ln in _page_evidence_line(page, ref))
        if scope == "quality":
            flags = snapshot.get("quality.json", {}).get("quality_flags", {})
            active = [name for name, items in flags.items() if items]
            if active:
                lines.append(f"- Quality flags with findings: {', '.join(active)}.  _[quality.json → quality_flags]_")
        if scope == "audit":
            gates = snapshot.get("gates.json", {})
            statuses = ", ".join(f"{g.get('id')}={g.get('status')}" for g in gates.get("gates", []))
            lines.append(f"- Gate status (last run): {statuses or 'not run yet'}.  _[gates.json]_")
    # de-dup targeted pages by id, preserve order
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for page in targeted:
        pid = str(page.get("id"))
        if pid not in seen:
            seen.add(pid)
            unique.append(page)
    return "\n".join(lines), unique


def _section_targets(
    root: Path,
    config: WikiConfig,
    snapshot: dict[str, dict[str, Any]],
    *,
    pages: list[dict[str, Any]],
    source: dict[str, Any] | None,
    materialize: str,
) -> tuple[str, list[str]]:
    lines = ["## 3 · Targets — the concrete object of the work", ""]
    target_paths: list[str] = []
    if not pages and not source:
        lines.append("_(No page/packet/source attached — this brief is grounded only in the intent and state above.)_")
    for page in pages:
        pid = str(page.get("id"))
        content = build_page_content(root, config, pid, snapshot)
        path = str(page.get("path") or "")
        if path:
            target_paths.append(path)
        lines.append(f"### `{path}` — {page.get('title') or pid}")
        if not content.get("ok"):
            lines.append(f"_(content unavailable: {content.get('error', 'unknown')})_")
            continue
        refs = content.get("source_refs") or []
        backlinks = content.get("backlinks") or []
        lines.append(
            f"- context={page.get('context')} · type={page.get('page_type')} · "
            f"cited sources={len(refs)} · backlinks={len(backlinks)}"
        )
        body = str(content.get("body") or "")
        if materialize == "full" or len(body) <= _BODY_EXCERPT_CHARS:
            lines.append(_fence(body, "markdown"))
        else:
            lines.append(_fence(body[:_BODY_EXCERPT_CHARS] + f"\n… (truncated; full text in {path})", "markdown"))
    if source:
        spath = str(source.get("path") or "")
        target_paths.append(spath)
        lines.append(f"### Raw source — `{spath}`")
        lines.append(f"- context={source.get('context') or config.default_context}")
        lines.append(
            "- The deterministic context package (chunks + provenance) is attached at run time by the "
            "ingestion chain; do not invent context beyond the excerpts."
        )
    return "\n".join(lines), target_paths


def _section_intent(intent: str, resume: dict[str, Any] | None) -> str:
    lines = ["## 4 · Operator intent — in your own words", ""]
    if resume:
        lines.append(
            f"**This is a RETURN.** You are continuing an existing proposal on branch "
            f"`{resume['branch']}`. Inspect its current diff, apply the feedback below, and commit "
            f"onto the SAME branch — do NOT open a new one."
        )
        lines.append("")
        lines.append("Reviewer feedback:")
    lines.append(intent.strip() or "_(none provided — state your intent before delegating.)_")
    return "\n".join(lines)


def _section_contract(config: WikiConfig, theme: str, resume: dict[str, Any] | None) -> str:
    prefix = str(config.approval.get("branch_prefix", "wiki/")).rstrip("/")
    if resume:
        branch_line = f"- Continue on the EXISTING `{resume['branch']}` branch; do not create a new branch."
    else:
        branch_line = f"- Work on a `{prefix}/{theme}` branch (create it; never commit to the default branch)."
    return (
        "## 5 · Output contract — ships with every brief (pinned)\n\n"
        f"{branch_line}\n"
        "- Edit files directly; create typed pages ONLY via `scripts/wiki_new.py`, never from blank files.\n"
        "- Summarize your changes in a short paragraph suitable for a draft-PR body.\n"
        "- **NEVER** push to the default branch, mark a PR ready, or merge. A human owns the gate.\n"
        "- The deterministic gates (`wiki_audit --check`, `wiki_consolidate --check`, `pytest tests/`) "
        "must pass before the draft leaves review."
    )


# --------------------------------------------------------------------------- #
# Public compose
# --------------------------------------------------------------------------- #
def compose_brief(
    root: Path,
    config: WikiConfig,
    snapshot: dict[str, dict[str, Any]],
    *,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the full work brief deterministically. Returns text + metadata;
    persistence (id, disk) is the store's job. Same spec + same snapshot ⇒
    byte-identical ``text`` and ``brief_sha``."""
    norm = normalize_spec(spec)
    generated_at = str(snapshot.get("manifest.json", {}).get("generated_at") or "")
    ref = _parse_date(generated_at) or (_parse_date(generated_at[:10]) if generated_at else None)
    index = {str(p.get("id")): p for p in snapshot.get("pages.json", {}).get("pages", [])}

    grounding = norm["grounding"]
    resume = grounding.get("resume")
    ingest = norm["mission_kind"] == "ingest" or grounding["source"] is not None

    header = (
        f"# Work brief — {norm['mission_kind'] or 'freeform'} — {config.approval.get('branch_prefix', 'wiki/')}"
        f"{norm['theme']}\n\n"
        f"_Composed from snapshot `{generated_at or 'unknown'}` (repo `{config.repo_id}`). "
        f"Composer {BRIEF_SCHEMA_VERSION}. This is a proposed work order — read it, edit it, then choose "
        f"to copy, save or execute it._"
    )

    section2, targeted_pages = _section_state(
        snapshot, ref, page_ids=grounding["page_ids"], state_report=grounding["state_report"], index=index
    )
    section3, target_paths = _section_targets(
        root, config, snapshot, pages=targeted_pages, source=grounding["source"], materialize=norm["materialize"]
    )

    text = "\n\n".join(
        [
            header,
            _section_conventions(root, config, norm["materialize"], ingest),
            section2,
            section3,
            _section_intent(norm["intent"], resume),
            _section_contract(config, norm["theme"], resume),
        ]
    ).rstrip() + "\n"

    brief_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "schema_version": BRIEF_SCHEMA_VERSION,
        "spec": norm,
        "text": text,
        "brief_sha": brief_sha,
        "size_chars": len(text),
        "snapshot_generated_at": generated_at,
        "target_paths": sorted(set(p for p in target_paths if p)),
        "context_pages": [str(p.get("id")) for p in targeted_pages],
    }


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_targets(root: Path, target_paths: list[str]) -> dict[str, str]:
    """Content hash of each target file — the baseline for the launch-time
    staleness guard. Missing files hash to the sentinel ``"absent"``."""
    hashes: dict[str, str] = {}
    for rel in target_paths:
        path = root / rel
        if path.is_file():
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            hashes[rel] = "absent"
    return hashes


class BriefStore:
    """On-disk work-brief store under ``derived_root/work-briefs/``.

    One ``<id>.json`` record + one ``<id>.md`` text per brief. Git-ignored
    (``data/derived/**``). No global mutable state — each call reads/writes the
    filesystem, so concurrent operator threads stay consistent."""

    def __init__(self, root: Path, config: WikiConfig) -> None:
        self.root = root
        self.config = config
        self.dir = WikiPaths(root, config).derived_root / "work-briefs"

    def _record_path(self, brief_id: str) -> Path:
        return self.dir / f"{brief_id}.json"

    def _text_path(self, brief_id: str) -> Path:
        return self.dir / f"{brief_id}.md"

    def _new_id(self) -> str:
        # Server runtime (not a workflow) — uuid is fine and avoids collisions.
        import uuid

        return "b" + uuid.uuid4().hex[:12]

    def save_new(self, composed: dict[str, Any]) -> dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        brief_id = self._new_id()
        now = _now_iso()
        record = {
            "brief_id": brief_id,
            "created_at": now,
            "updated_at": now,
            "status": "draft",
            "schema_version": BRIEF_SCHEMA_VERSION,
            "spec": composed["spec"],
            "brief_sha": composed["brief_sha"],
            "size_chars": composed["size_chars"],
            "snapshot_generated_at": composed["snapshot_generated_at"],
            "target_paths": composed["target_paths"],
            "target_hashes": hash_targets(self.root, composed["target_paths"]),
            "context_pages": composed["context_pages"],
            "job_id": None,
        }
        self._text_path(brief_id).write_text(composed["text"], encoding="utf-8")
        self._record_path(brief_id).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return {**record, "text": composed["text"]}

    def get(self, brief_id: str) -> dict[str, Any] | None:
        path = self._record_path(brief_id)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        text = ""
        tp = self._text_path(brief_id)
        if tp.is_file():
            text = tp.read_text(encoding="utf-8")
        return {**record, "text": text}

    def list(self) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for path in self.dir.glob("*.json"):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        records.sort(key=lambda r: str(r.get("created_at")), reverse=True)
        return records

    def update_text(self, brief_id: str, text: str) -> dict[str, Any] | None:
        record = self.get(brief_id)
        if record is None:
            return None
        if record.get("status") != "draft":
            return {"ok": False, "error": "only draft briefs can be edited", "brief_id": brief_id}
        record.pop("text", None)
        record["brief_sha"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        record["size_chars"] = len(text)
        record["updated_at"] = _now_iso()
        self._text_path(brief_id).write_text(text, encoding="utf-8")
        self._record_path(brief_id).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return {**record, "text": text}

    def set_status(self, brief_id: str, status: str, *, job_id: str | None = None) -> dict[str, Any] | None:
        record = self.get(brief_id)
        if record is None:
            return None
        record.pop("text", None)
        record["status"] = status
        if job_id is not None:
            record["job_id"] = job_id
        record["updated_at"] = _now_iso()
        self._record_path(brief_id).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        return self.get(brief_id)


def compose_and_save(
    root: Path, config: WikiConfig, snapshot: dict[str, dict[str, Any]], *, spec: dict[str, Any]
) -> dict[str, Any]:
    composed = compose_brief(root, config, snapshot, spec=spec)
    store = BriefStore(root, config)
    return store.save_new(composed)


def compose_return_brief(
    root: Path,
    config: WikiConfig,
    snapshot: dict[str, dict[str, Any]],
    *,
    parent_job: dict[str, Any],
    feedback: str,
) -> dict[str, Any] | None:
    """Compose + save a FOLLOW-UP brief that continues a delivered job's branch
    with reviewer feedback (the "return, not restart" loop). Returns None if the
    parent has no branch to continue."""
    branch = parent_job.get("branch")
    if not branch:
        return None
    spec = {
        "mission_kind": parent_job.get("mission_kind"),
        "theme": parent_job.get("theme") or "update",
        "intent": feedback,
        "grounding": {"resume": {"branch": branch, "parent_job_id": parent_job.get("job_id")}},
    }
    return compose_and_save(root, config, snapshot, spec=spec)
