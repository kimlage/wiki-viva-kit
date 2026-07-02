---
title: "Plan - Codex agentic missions: draft, commit and PR from inside the cockpit"
page_id: plan-codex-agentic-missions-2026-07-02
page_type: methodology_plan
aliases:
  - Codex missions plan
  - Codex-as-local-job plan
  - Agentic flows from the cockpit
  - Let Codex draft this
tags:
  - wiki/methodology
  - wiki/operations
  - wiki/interface
  - wiki/agents
  - wiki/codex
  - status/plan
date: "2026-07-02"
status: plan
context: system
visibility: private_reference
related_pages:
  - docs/references/proposals/cockpit-3d-navigation-plan-2026-07-01.md
  - docs/references/proposals/threejs-operational-dashboard-plan-2026-07-01.md
  - AGENTS.md
  - wiki.config.yaml
  - memories/system/git-approvals.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/daily-operation.md
target_version: "wiki-viva v7.2 candidate"
audience: "wiki-viva maintainers, downstream wiki owners and implementation agents"
scope: "design plan for launching, grounding, monitoring and gating local Codex agent jobs from the cockpit Missions surface, producing proposal branches + draft PRs through the existing git_workflows, with no cloud service, no API keys, and the human PR gate unchanged"
---

# Plan - Codex Agentic Missions: Draft, Commit and PR From Inside the Cockpit

Updated on: 2026-07-02.

> Status (2026-07-02): plan only. Nothing in this document is implemented yet.
> It extends the local operator API (`wiki_core/web/server.py`) and the cockpit
> Missions/reader/packet surfaces already shipped by the
> [3D navigation plan](cockpit-3d-navigation-plan-2026-07-01.md) and the
> [Three.js cockpit plan](threejs-operational-dashboard-plan-2026-07-01.md).
> The safety contract of both — deterministic core stays LLM-free, every
> mutating change lands as a `wiki/<theme>` branch + commits + draft PR, the
> human approve/merge gate is untouched — is non-negotiable here and is the
> spine of the whole design.

The owner's brief, translated and honored:

> "Updates and new data keep coming from OUTSIDE, so from inside the wiki I have
> little ability to act. I want to use CODEX (OAuth — sign in with my existing
> ChatGPT account, not an API key). From the cockpit I want to include context
> and ask Codex — already connected with my credentials and this wiki's context —
> to edit and create the commits and PRs to be approved and merged. Make it EASY
> and INTEGRATED INTO THE MISSIONS, so I can update data, TRIGGER AGENTIC FLOWS
> and MONITOR them."

## North star

The cockpit gains a hand that can actually type. Today the operator can *see*
everything (freshness radar, atlas, districts, trails, the in-world reader) and
can run deterministic, zero-token checks and git plumbing — but the actual
*writing* of memory (the deep read, the edit, the new page) is a manual handoff
to an agent in a terminal. This plan closes that seam: from any mission or any
locked page/packet/source, one click spawns a **scoped, local Codex job** that
is pre-loaded with the wiki's conventions (AGENTS.md, `wiki.config.yaml`, the
relevant skills, `wiki.page-types.yaml`) plus the concrete target (page content,
packet, raw-source context package) plus the operator's free-text intent. Codex
runs as a local agent on the operator's own machine — exactly the way Claude
Code runs today — authed once via `codex login` (ChatGPT OAuth, token in
`~/.codex`, never in the repo). It edits files inside a sandboxed workspace,
then the operator API drives the **existing** `git_workflows` to open a
`wiki/<theme>` branch, commit, and open a **draft PR**. The operator watches a
live JSONL log in a new Jobs tray (queued → running → awaiting-review → failed),
and the finished job materializes as a draft PR in the approval inbox and a new
`approve` mission. **Codex proposes; the human disposes.** The deterministic core
never gains an LLM client; if Codex is not installed or not authed, the mission
honestly shows "Codex not available" rather than faking a run.

## Critical findings

Four lenses (operator server surface, git/PR guardrails, cockpit Missions/reader
plumbing, Codex CLI/auth reality) were consolidated against the live repo. The
findings that motivate this plan, ranked:

1. **CRITICAL — the operator is powerless against outside-in change.** New data
   arrives from outside the wiki (statements, documents, messages), but from
   inside the cockpit the only mutating capabilities are (a) allowlisted
   deterministic action cards (`run_action`), (b) fixed git plumbing
   (`run_git_workflow`), and (c) an ingestion pipeline whose last two steps
   merely *emit an LLM request package for an agent to pick up manually*
   (`ingestion_plan.py` `llm_request_preview`/`llm_request_emit`, calling
   `wiki_llm_context_pass.py --emit-request`). The intelligence — the deep read,
   the edit, the new page — is explicitly delegated to "the agent that runs the
   repo" (AGENTS.md:5-7), but the cockpit provides no way to *invoke* that agent.
   The operator must leave the cockpit, open a terminal, and drive Codex/Claude
   by hand. The loop is open.

2. **HIGH — every ingredient for a Codex job already exists except the launcher.**
   The grounding is served (`GET /api/pages/{id}/content`, the snapshot bundle,
   the decision packet in `?packet=`, the source triage `result.targets`). The
   git/PR machinery is battle-tested and structurally gated
   (`git_workflows.py`: sanitized `wiki/<theme>` themes, clean-worktree
   preconditions, prefix-gated commit/publish, always-`--draft` PR, `dry_run`
   default True). The UI patterns are proven (StatusPill tones, the ingestion
   pipeline rail, the packet/missions trays, `CommandOutput` streaming `<pre>`,
   honest demo-mode disabling). The one missing organ is an **async job runner
   with persistent job records** — the server today is purely synchronous
   request/response with only an 8s in-memory snapshot cache and no run history.

3. **HIGH — Codex has a first-class OAuth + headless mode that maps exactly onto
   the brief and the safety model.** `codex login` is "Sign in with ChatGPT" — no
   API key, draws on the operator's existing ChatGPT plan, token cached to
   `~/.codex/auth.json` (or OS keyring) *outside the repo*. `codex exec` runs
   headlessly with a task string; `--json` emits a JSONL event stream
   (`thread.started`/`turn.started`/`item.completed`/`turn.failed`,
   command/file-change items) that a job runner can tail for live status/log;
   `--sandbox workspace-write` fences edits to the working directory (network off
   by default); prompt + context can be fed via stdin (`codex exec - < prompt.txt`).
   This is precisely "launch a scoped job with a task prompt + attached context,
   stream it, and keep it fenced."

4. **MEDIUM — the human gate is enforced structurally, so a Codex job cannot
   escape it even by accident.** `commit_proposal`/`publish_proposal`/
   `open_draft_pr` all early-return an error unless the current branch starts
   with the `wiki/` prefix; PR creation is always `--draft`; `sync_main` only
   does an ff-only pull on the default branch. A Codex job that *only* orchestrates
   these operations physically cannot push to `main`, cannot open a non-draft PR,
   and cannot approve or merge. The gate is not a convention Codex must remember —
   it is a wall it runs into. This plan requires the Codex path to reuse these ops
   verbatim rather than issue raw `git`/`gh`.

5. **MEDIUM — credentials and the LLM-free core are already protected by existing
   backstops.** The server never reads secrets (git/gh use ambient operator auth);
   the same model extends to `codex` (ambient `~/.codex` session). If a token ever
   leaked into captured stdout it is scrubbed by `SECRET_VALUE_RE` redaction
   (`commands.py:13-15`, `git_workflows.py:15-16`); if it ever landed in a
   versioned file, `wiki_core/detectors/secrets.py` (openai_api_key, bearer_token,
   github_token, jwt, …) fails `wiki_audit.py --check` and CI. Codex is invoked as
   an *external local subprocess*, never a Python LLM client — the wiki-viva hard
   rule "determinism stays in the toolkit, intelligence stays in you; never add an
   LLM client to the Python" (SKILL.md:151-153) is preserved.

## Non-goals and guardrails

Non-negotiable. Any implementation that breaks one of these is wrong.

- **No cloud service.** The Codex job runner lives inside the existing LOCAL
  operator server (`127.0.0.1:8765`, CORS locked to the Vite dev origin). It
  shells out to the locally-installed `codex` binary as a subprocess, mirroring
  how `run_action`/`run_git_workflow` already `subprocess.run` allowlisted
  commands. No new network service, no remote runner, no Codex "cloud" mode.

- **OAuth credentials stay entirely outside the repo and the PR boundary.** Auth
  is obtained by the human running `codex login` (ChatGPT sign-in) once; the token
  lives in `~/.codex/auth.json` (or OS keyring; `CODEX_HOME`-overridable). The
  wiki server never receives, reads, stores, forwards, or versions a token or API
  key. Credentials never appear in a branch, commit, PR body, snapshot, or job
  log. This matches the repo's established `.env`/`.gitignore` boundary (personal
  config untracked; `~/.codex` already treated as a per-user out-of-repo location
  by `.env.example`). No API-key mode is offered by the cockpit.

- **The human PR gate is unchanged.** Every Codex action lands as a `wiki/<theme>`
  branch + commits + a **draft** PR, exclusively through the existing
  `git_workflows` operation set. Codex can open/update a draft PR; it can never
  approve, mark ready, or merge. No direct writes to `main` or to generated
  operational pages (those are recompiled, not hand-edited).
  `--dangerously-bypass-approvals-and-sandbox` / `--yolo` is **forbidden**; the
  deprecated `--full-auto` is not used.

- **Deterministic core stays LLM-free.** No LLM client is added to `wiki_core`.
  Codex is an external process. The zero-token honesty gates
  (`wiki_audit`, `wiki_quality_report`, `wiki_check_methodology_coverage`,
  `wiki_operation_compile`, `wiki_consolidate --check`, `pytest`, …) remain the
  guarantee, and a Codex-produced branch must pass them before draft→ready.

- **Honest degradation, no fabricated capability.** If `codex` is not installed
  or not authed, the cockpit surfaces "Codex not available" and disables the
  spawn CTAs — never a fake run, spinner, or invented PR. Codex affordances only
  render when `mode === 'local_operator'` (Codex is a local agent) and the
  capability probe passes, mirroring the existing `demo.actionsOff`/`demo.gitOff`
  pattern. "A green gate is a real guarantee; a disabled gate is a silent lie."

- **Scope is one serialized job stream.** Reusing a ChatGPT-plan `auth.json` for
  automation is only valid on trusted private infra, single serialized stream, no
  concurrency. The runner enforces a queue of one active job (see Data contract).
  This integration is explicitly unsuitable for public/open-source multi-user
  deployments; the cockpit gates it behind `local_operator` mode.

## The design

### (a) Codex-as-local-job

**Auth (once, by the human).** The operator runs `codex login` in a terminal and
signs in with ChatGPT. The token caches to `~/.codex/auth.json`
(`auth_mode: "chatgpt"`, auto-refreshing). The cockpit never touches it. A
**capability probe** in the operator server checks (i) `codex --version` succeeds
and (ii) a valid auth session exists (presence of a non-expired `~/.codex/auth.json`
or `codex login status` if available). The probe result
(`{installed, authed, auth_mode, version}`) is surfaced through runtime config so
the UI can advertise Codex only when it is truly available.

**Launch endpoint.** A new `POST /api/codex/jobs` is registered in the server's
POST allowlist (`server.py:119-125`, alongside the existing five paths). It
accepts a job spec (see schema below), writes a persistent job record, enqueues
it, and returns `{job_id, status: "queued"}` immediately (non-blocking). Because
the server is synchronous today, this introduces the **one genuinely new organ**:
an in-process **job runner** — a single worker thread draining a queue of one,
with a job-state store on disk.

**The Codex invocation.** For each job the runner:
1. **Assembles a prompt file** on disk (`derived_root/codex-jobs/<job_id>/prompt.txt`)
   from the grounding (section b) — conventions, targets, intent, and for ingest
   jobs the deep-read template + context package.
2. **Runs Codex headlessly, sandboxed, streamed:**
   `codex exec - --cd <repo> --sandbox workspace-write -a on-request --json -o <final.md> < prompt.txt`
   - `-` reads the whole prompt from stdin.
   - `--cd <repo>` scopes the job to the wiki working tree.
   - `--sandbox workspace-write` lets Codex edit files and run commands inside the
     workdir only; network stays off (macOS Seatbelt / Linux bubblewrap). `--yolo`
     is never used.
   - `-a on-request` keeps it running unattended while still refusing to leave scope.
   - `--json` streams JSONL events; the runner tails them into
     `codex-jobs/<job_id>/log.jsonl` (redacted via `SECRET_VALUE_RE`) to drive
     status and the live log.
   - `-o final.md` captures Codex's final summary message for the PR body.
3. **Hands off to `git_workflows`.** After Codex finishes editing, the runner calls
   the **existing** operations in order:
   `start_proposal(theme)` → `stage_paths(paths)` → `commit_proposal(msg)` →
   `publish_proposal` → `open_draft_pr(title, body=final.md summary)`.
   No new git logic; the sanitized-theme, clean-worktree, prefix-gated,
   always-draft guardrails apply unchanged. `dry_run` respects the job spec (dry
   preview by default; the operator confirms to actually push/open).
4. **Records outcome.** The job record is updated with the produced branch name,
   `draft_pr_url`, final status, and log path.

**Job lifecycle:** `queued → running → committing → awaiting-review → done`
(with `failed`/`cancelled` terminals). `awaiting-review` is reached the moment a
draft PR exists — from there the human gate owns it.

### (b) Context inclusion from the UI

Every job carries a **grounding packet** assembled from two layers:

**Auto-attached conventions (always, by the runner).** So Codex inherits the same
rules Claude does:
- `AGENTS.md` (verbatim or by path reference) — the canonical operating brief.
- `wiki.config.yaml` — contexts, `default_visibility`, `private_sensitive_allowed`,
  `approval.gate`/`branch_prefix: wiki/`, `llm.required_context_pass: true`.
- `wiki.page-types.yaml` — the frontmatter contract, so typed pages are created via
  `scripts/wiki_new.py`, never from blank files; `source_refs` ≠ `moc_parent`.
- The relevant skill(s): `wiki-viva` (single entry, "Hard rules") always; plus
  `wiki-ingestion-agent` + `wiki-llm-context-agent` for ingest jobs; plus
  `wiki-privacy-publication` when a public boundary is in play.

**Operator-supplied targets + intent (per mission / per surface):**
- **Locked page** — from the PageReader dock, the job is grounded in the current
  `page` + loaded `PageContent` (body, `source_refs`, resolved_links, backlinks,
  path, context, freshness_state). A new "Ask Codex to draft edits" button joins
  the `readerActions` row; `onSpawnCodexJob(page, intent)` threads up to WorldView
  exactly as `onRunAction` does.
- **Decision packet** — from the `packetTray` actions in WorldView, "Send packet
  to Codex" grounds the job in the whole multi-page selection (`route.query.packet`
  ids → `packetPages` content). The packet is deep-linkable, so the grounding set
  is shareable.
- **Raw source** — from SourcesView, "Let Codex draft the ingestion" grounds the
  job in the source + `context` + the triage `result.targets` (target_pages /
  target_entities / next_steps) and the deterministic **context package**
  (per-chunk `chunk_id`/`cache_key`/text, `root_entity`/`input_channel`/
  `quadrant_map`/`target_pages`/`input_stage_status`) emitted by
  `wiki_llm_context_pass.py --emit-request`. Codex reads real excerpts and cannot
  invent context.
- **Free-text intent** — a new textarea (mirroring the existing `prBody` textarea)
  on each spawn surface lets the operator type grounding intent
  ("re-verify the price, it changed to X"; "this source supersedes page Y").
  Optional but always offered.

The assembled prompt is: `[conventions] + [deep-read template if ingest] +
[targets] + [operator intent] + [expected output: edit files on a wiki/ branch,
summarize for the PR body, do NOT push/merge]`.

### (c) Missions integration — "let Codex draft this"

`MissionsPanel.deriveMissions()` already emits `Mission` objects with
`kind ∈ {refresh, verify, evidence, approve}`, each carrying a `pageId` (except
`approve`, which routes to `/review`). Each row already renders one "open" button;
this plan adds a **second action per row: a Codex CTA**, mapped 1:1 to the task
semantics already encoded in i18n:

- **`refresh` / `verify`** → "Codex: refresh this page" — grounded in
  `mission.pageId` + its content; intent seeded from the existing i18n why
  ("{days}d past its freshness window; re-verify facts and bump `updated_at`" /
  "set `updated_at` + `stale_after_days`").
- **`evidence`** → "Codex: find & cite a source" — grounded in the page + its empty
  `source_refs`; intent "content page with no cited source; locate and cite
  provenance". (Network is off in `workspace-write`; if the source must be fetched,
  the operator attaches it first via SourcesView — the honest limitation is stated
  in the UI.)
- **`ingest`** (new mission kind, or the SourcesView affordance) → "Codex: draft
  the ingestion" — runs the full agentic flow in (e).
- **`approve`** → **no Codex job.** This kind *is* the human gate; it keeps routing
  to `/review`. Spawning a job here would be a category error.

New i18n keys (`missions.codex.draft`, `missions.codex.spawn`,
`missions.codex.unavailable`, …) are added to both EN and PT dicts following the
existing full-parity pattern. The Codex CTA renders only in `local_operator`
mode with a passing capability probe; otherwise it is hidden or disabled with an
honest "Codex not available" tooltip.

### (d) Monitoring — the Jobs tray

A third command-bar tray joins the existing packet and missions trays in
`worldCommandBar`: a **Jobs** `trayButton` (e.g. `TerminalSquare`/`Activity`,
both already imported) with `setJobsOpen` state that closes the other two, and a
`jobsTray` panel rendered in the same slot. Contents:

- **Job rows** with a StatusPill reusing the proven tone vocabulary:
  queued→muted, running→info, committing→info, awaiting-review→warn, failed→bad,
  done→good.
- **A step timeline** modeled on the ingestion `pipelineRail` (numbered stages:
  ground → run Codex → stage/commit → publish → open draft PR), each with its own
  StatusPill — directly reusing `gateStepTone`/`gateStatusLabel`.
- **A live log** `<pre>` streaming the redacted JSONL (reusing the
  `CommandOutput`/`worldOutputDock` stdout pattern), with agent messages, command
  executions, and file-change items.
- **The produced branch + draft PR link** — the same `draft_pr_url` the approval
  inbox shows.
- **A "usage" note** — a job draws on the operator's ChatGPT plan quota; when
  limits are hit, the row degrades honestly to `failed` with a "plan limit reached"
  reason.

**Composition with the approval inbox (zero new plumbing).** Because a Codex job's
output *is* a proposal branch + draft PR via `git_workflows`, its `draft_pr_url`
flows into `bundle.git.proposal` → the inbox's stage-4 "Human gate" item and the
`PrHandoffPanel` gate track unchanged. The finished job materializes as a new
`approve` mission (`kind='approve'`, `href='/review'`). The Jobs tray's "land on
the draft PR" link and the inbox's "Open request" link are the same URL. Monitoring
and approval are two views of one object.

### (e) Agentic flows — chaining ingest → deep-read → propose

The richest flow is source ingestion, which the plan expresses as a **chained
Codex job** that walks the deterministic-first pipeline and the delegated deep-read
protocol without ever writing canonical memory directly:

1. **Deterministic prep (server, zero-token, already exists).** input-stage compile
   → manifest → text/chunks → index → `wiki_llm_context_pass.py --emit-request`
   produces the machine-readable context package. This is prerequisite state, run
   via the existing `run_ingestion_step` (WRITE steps stay `dry_run`, stage must be
   `ready`).
2. **Delegated deep read (Codex).** The job's prompt embeds the context package +
   the `context_deep_read.v3` template. Codex fills all four quadrants or declares
   explicit absence, sets `sensitivity.has_pii`/`has_secret` **without echoing raw
   values**, records each claim's `status_epistemologico` + `chunk_id`, and when the
   excerpt is insufficient records an uncertainty rather than inventing context.
3. **Record + consolidate (Codex, via toolkit).** `--record-result` to the
   llm-cache, then `wiki_consolidate.py --emit-event --packet`, then **integrate**
   into target hubs and close `consolidated_into` / every `impact_closure` entry —
   because "ingesting = integrating" (cataloging is not ingesting; enforced by
   `wiki_consolidate --check`, audit and CI).
4. **Propose (runner, via `git_workflows`).** `wiki/ingest-YYYY-MM-DD-<topic>`
   branch → commit → draft PR.

The operator triggers this from SourcesView with one click and watches the whole
chain in the Jobs tray step timeline; each deterministic prep step and the Codex
deep-read/consolidate steps appear as timeline rows. The job refuses to reach
`awaiting-review` until the honesty gates pass locally (draft stays draft while any
chunk lacks a recorded deep-read result under `required_context_pass: true`).

## Data-contract / API changes

**New endpoints (registered in `server.py` POST/GET dispatch):**
- `POST /api/codex/jobs` — launch. Body: the job spec below. Returns
  `{job_id, status}`. Non-blocking (enqueues; runner drains).
- `GET  /api/codex/jobs` — list job records (for the tray).
- `GET  /api/codex/jobs/{job_id}` — single job record (status + step timeline +
  branch/PR).
- `GET  /api/codex/jobs/{job_id}/log` — the redacted JSONL log (tail/stream; may
  be served via the existing `/api/snapshot/{name}` file convention or a dedicated
  streaming route).
- `POST /api/codex/jobs/{job_id}/cancel` — cooperative cancel (kills the subprocess,
  marks `cancelled`; never force-pushes or half-commits).
- **Capability probe** surfaced through `/api/health` and runtime config:
  `codex: {installed, authed, auth_mode, version}`.

**Job spec (request):**
```
{
  "intent": "free-text operator intent",
  "mission_kind": "refresh|verify|evidence|ingest|null",
  "grounding": {
    "page_ids": ["..."],        // locked page / packet
    "source": {"path|url, context}|null,  // ingest
    "attach_context_package": true|false  // ingest deep-read
  },
  "theme": "sanitized <topic> for wiki/<prefix>",
  "dry_run": true                // preview branch/PR ops before pushing
}
```

**Job record (`derived_root/codex-jobs/<job_id>.json`, mirrored into the snapshot):**
```
{
  "job_id", "created_at", "updated_at",
  "status": "queued|running|committing|awaiting-review|done|failed|cancelled",
  "reason": "…",                 // e.g. "plan limit reached", "codex not authed"
  "mission_kind", "intent",
  "grounding": {…},
  "steps": [{"id","label","status"}],   // ground/run/commit/publish/open-pr
  "codex": {"session_id","auth_mode","final_message_path"},
  "branch": "wiki/…"|null,
  "draft_pr_url": "…"|null,
  "log_path": "codex-jobs/<job_id>/log.jsonl",
  "human_gate_state": "…"        // mirrors git_ops proposal state once a PR exists
}
```

**Job store location.** A new derived-tree dir `derived_root/codex-jobs/`
(sibling of `source-manifests`, `llm-cache`, `web-snapshot`), holding per-job
`<job_id>.json`, `prompt.txt`, `log.jsonl`, `final.md`. It is git-ignored
(`data/derived/**` already blocked).

**Snapshot surface.** `codex_jobs.json` is added to `SNAPSHOT_FILES`
(`schemas.py`) and to the cockpit `FILES` map (`snapshot.ts`) so the tray loads
through the existing `loadFromBase()` path. `/api/snapshot/{name}` already serves
arbitrary snapshot files, so the tray's status/log surfacing reuses that route.

**Cockpit client wrappers (`snapshot.ts`).** `spawnCodexJob(spec)`,
`listCodexJobs()`, `pollCodexJob(id)`, `streamCodexLog(id)`, `cancelCodexJob(id)`
— each identical in shape to `runGitWorkflow`/`runIngestionStep` (POST/GET to
`apiUrl('/codex/…')`, parse JSON, throw on `!ok`). `App.tsx` wires them with the
existing `busyAction`/notice-toast + honest demo-mode disabling.

**No schema change to git.** `git_workflows` operations are reused as-is; no new
git op is added.

## Implementation phases

Each phase is independently shippable and leaves the cockpit honest.

### Phase 0 — Capability probe + honest degradation (ship first)
- **Deliverables:** `codex` capability probe in the server; `codex:{installed,
  authed,auth_mode,version}` in `/api/health` and runtime config; the UI reads it;
  a "Codex not available / not authed" state everywhere a future CTA will live;
  i18n keys (EN+PT). No job runner yet.
- **Acceptance:** with `codex` absent/unauthed, the cockpit shows the honest
  unavailable state and no spawn CTA is clickable; with `codex` authed, the probe
  reports `authed:true, auth_mode:"chatgpt"`. `pytest` covers the probe's three
  states (absent, installed-unauthed, authed) via a stubbed CLI.

### Phase 1 — Job runner + launch/read endpoints (no UI spawn yet)
- **Deliverables:** the in-process single-worker job runner + on-disk job store
  (`derived_root/codex-jobs/`); `POST/GET /api/codex/jobs`, `GET …/{id}`,
  `…/{id}/log`, `POST …/{id}/cancel`; `codex exec - --sandbox workspace-write -a
  on-request --json` invocation with JSONL tailing + `SECRET_VALUE_RE` redaction;
  `git_workflows` handoff (start→stage→commit→publish→open_draft_pr, `dry_run`
  honored); `codex_jobs.json` in the snapshot. Driven by a synthetic fixture
  (a fake `codex` shim emitting canned JSONL that "edits" a fixture file).
- **Acceptance:** a job launched via curl against the fixture shim reaches
  `awaiting-review` with a real `wiki/<theme>` branch + draft PR (against a test
  remote) or a faithful `dry_run` preview; the log is redacted; a second launch
  while one is running is queued, not run concurrently; cancel kills the subprocess
  and marks `cancelled` with no half-commit. `pytest tests/` green; the sandbox
  never leaves the workdir; no path can push to `main` or open a non-draft PR.

### Phase 2 — Jobs tray + monitoring
- **Deliverables:** the third `Jobs` `trayButton` + `jobsTray` panel; job rows
  with StatusPill; the step timeline (reusing `pipelineRail`/`gateStepTone`); the
  live JSONL log `<pre>` (reusing `CommandOutput`); branch/draft-PR links;
  `spawnCodexJob`/`listCodexJobs`/`pollCodexJob`/`streamCodexLog`/`cancelCodexJob`
  in `snapshot.ts`; honest demo/unavailable disabling.
- **Acceptance:** launching a job (dev/fixture) shows queued→running→awaiting-review
  with a streaming log and a working "open draft PR" link; the tray closes the
  packet/missions trays and vice-versa; in demo or Codex-unavailable mode the tray
  shows the honest state and no live job.

### Phase 3 — Missions + reader + packet spawn CTAs (grounding)
- **Deliverables:** the second Codex action per mission row (refresh/verify →
  "refresh this page"; evidence → "find & cite a source"; approve → **no CTA**);
  "Ask Codex to draft edits" in `PageReader.readerActions`; "Send packet to Codex"
  in the `packetTray` actions; the free-text intent textarea on each surface; the
  runner's auto-attach of AGENTS.md + `wiki.config.yaml` + `wiki.page-types.yaml` +
  `wiki-viva` skill into every prompt; `onSpawnCodexJob(page|packet, intent)`
  threaded through WorldView.
- **Acceptance:** clicking "Codex: refresh this page" on a `refresh` mission spawns
  a job whose prompt (inspectable in `codex-jobs/<id>/prompt.txt`) contains the
  page content + conventions + seeded intent, and produces a branch bumping
  `updated_at`; the `approve` mission shows no Codex CTA; every prompt embeds
  AGENTS.md by reference. `pytest` asserts prompt assembly for each grounding kind.

### Phase 4 — Ingestion chain (ingest → deep-read → consolidate → propose)
- **Deliverables:** the `ingest` job flow wiring SourcesView's "Let Codex draft the
  ingestion"; the runner chains the deterministic prep (via `run_ingestion_step`,
  WRITE steps `dry_run`) then a Codex deep-read prompt embedding the context package
  + `context_deep_read.v3` + ingestion skills, then consolidate/integrate, then the
  `wiki/ingest-…` proposal; the tray step timeline reflects the full chain; the job
  refuses `awaiting-review` until the LLM honesty gate passes.
- **Acceptance:** ingesting a fixture source produces a proposal branch with a
  normalized event whose `consolidated_into` is closed and target pages reference
  the source back; `wiki_consolidate.py --check` passes on the branch;
  `sensitivity` flags are set without raw values echoed; the deep read fills
  quadrants or declares explicit absence. Zero tokens are spent by the Python core.

### Phase 5 — Polish, honesty and downstream adoption
- **Deliverables:** plan-usage note in the tray (job draws ChatGPT plan quota;
  "plan limit reached" degradation); "no parallel branch for a page with an
  existing proposal — update/rebase, mark old superseded" honored by theme reuse;
  `docs/` operator note on `codex login` (and `--device-auth` for headless boxes);
  final gate wiring so a Codex branch runs the full deterministic gate set before
  draft→ready; downstream adaptation notes (the base kit ships the capability,
  private repos enable it).
- **Acceptance:** a plan-limit failure surfaces honestly as `failed` with a reason,
  not a stall; a second job on a page with an open proposal updates that branch
  rather than forking; a Codex branch cannot be marked ready while any honesty gate
  is red; the base cockpit with `codex` absent behaves identically to today.

## Risks and mitigations

- **Codex not installed or not authed.** → Capability probe + honest "Codex not
  available/not authed" state; CTAs hidden/disabled; no fake run (Phase 0). The
  operator is told to run `codex login` (or `--device-auth` on a headless box).

- **Secret / token leakage.** → Codex is invoked as a subprocess and never handed a
  token; auth lives in `~/.codex` outside the repo. All captured stdout/JSONL is
  scrubbed by `SECRET_VALUE_RE` before reaching the cockpit or the log file. Any
  token that ever lands in a versioned file fails `wiki_core/detectors/secrets.py`
  in `wiki_audit --check` and CI. Sandbox is `workspace-write` (network off), never
  `--yolo`.

- **Runaway or long jobs.** → `codex exec` with `-a on-request` and a
  `workspace-write` sandbox fenced to the workdir; a per-job timeout on the
  subprocess; cooperative cancel endpoint that kills the process cleanly (no
  half-commit); a queue of one so jobs cannot pile up or race the git tree.

- **Scope creep / wrong-scope edits.** → The job is grounded in explicit targets
  only; the prompt forbids pushing/merging and pins the `wiki/` prefix; `stage_paths`
  only stages files already in the changed-set, and the branch is a draft PR a human
  reviews. The sandbox prevents edits outside the workdir.

- **Concurrency / shared auth corruption.** → Single serialized job stream enforced
  by the runner; the plan states the ChatGPT-plan `auth.json` reuse is
  single-stream, private-infra-only, and that the seed file must not be overwritten
  (it holds refreshed tokens). Explicitly unsuitable for public multi-user deploys.

- **Plan-quota exhaustion.** → A job draws on the operator's ChatGPT plan; on limit
  the runner marks the job `failed` with a "plan limit reached" reason and the tray
  shows it honestly rather than stalling.

- **Determinism drift.** → No LLM client enters `wiki_core`; Codex only produces a
  proposal branch; the zero-token honesty gates and `wiki_operation_compile`
  (cockpit == recompile at HEAD) remain the guarantee; generated operational pages
  are recompiled, never hand-edited by Codex.

- **Human gate bypass.** → Structurally impossible via `git_workflows`
  (prefix-gated commit/publish, always-`--draft` PR, no merge op). The plan forbids
  raw `git`/`gh` from the Codex path.

## Definition of done

- From a mission, the locked page, a packet, or a raw source, one click spawns a
  scoped local Codex job pre-loaded with the wiki's conventions + the concrete
  target + free-text intent, and the operator watches it live and lands on the
  resulting draft PR — without leaving the cockpit or opening a terminal (after the
  one-time `codex login`).
- Auth is ChatGPT OAuth only; no API key is stored or requested; the token stays in
  `~/.codex` and never appears in any branch/commit/PR/snapshot/log.
- Every Codex action lands as a `wiki/<theme>` branch + commits + a **draft** PR
  through the existing `git_workflows`; Codex cannot approve, mark ready, or merge;
  no writes to `main` or generated operational pages.
- The Jobs tray shows queued/running/awaiting-review/failed with a redacted live log
  and the branch/PR link, and the produced draft PR composes into the existing
  approval inbox + a new `approve` mission with zero new plumbing.
- The ingestion chain (deterministic prep → Codex deep-read → consolidate/integrate
  → propose) runs and watches from one click, and refuses `awaiting-review` until
  the honesty gates pass; ingesting = integrating is enforced.
- With `codex` absent or unauthed, or in demo/static mode, the cockpit degrades
  honestly (no CTA, no fake job). The deterministic core remains LLM-free; all
  zero-token gates and `pytest tests/` stay green on every Codex-produced branch.
- Landed in the open-source kit first, covered by a synthetic `codex`-shim fixture
  and tests, passing CI, before any private downstream repo enables it.
