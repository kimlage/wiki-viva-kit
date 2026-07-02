---
title: "Plan - Codex agentic missions: work briefs, prompts and delegated work from inside the cockpit"
page_id: plan-codex-agentic-missions-2026-07-02
page_type: methodology_plan
aliases:
  - Codex missions plan
  - Codex-as-local-job plan
  - Agentic flows from the cockpit
  - Let Codex draft this
  - Work briefs
  - Prompt studio
  - Gerar prompt
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
scope: "design plan for composing complete, human-editable work briefs (prompts) from the state of the wiki, and for launching, grounding, monitoring, returning and gating local Codex agent jobs from the cockpit — producing proposal branches + draft PRs through the existing git_workflows, with no cloud service, no API keys, and the human PR gate unchanged"
---

# Plan - Codex Agentic Missions: Work Briefs, Prompts and Delegated Work From Inside the Cockpit

Updated on: 2026-07-02 (revision 2).

> Status (2026-07-02): plan only. Nothing in this document is implemented yet.
> It extends the local operator API (`wiki_core/web/server.py`) and the cockpit
> Missions/reader/packet surfaces already shipped by the
> [3D navigation plan](cockpit-3d-navigation-plan-2026-07-01.md) and the
> [Three.js cockpit plan](threejs-operational-dashboard-plan-2026-07-01.md).
> The safety contract of both — deterministic core stays LLM-free, every
> mutating change lands as a `wiki/<theme>` branch + commits + draft PR, the
> human approve/merge gate is untouched — is non-negotiable here and is the
> spine of the whole design.

The owner's brief, translated and honored. First directive (revision 1):

> "Updates and new data keep coming from OUTSIDE, so from inside the wiki I have
> little ability to act. I want to use CODEX (OAuth — sign in with my existing
> ChatGPT account, not an API key). From the cockpit I want to include context
> and ask Codex — already connected with my credentials and this wiki's context —
> to edit and create the commits and PRs to be approved and merged. Make it EASY
> and INTEGRATED INTO THE MISSIONS, so I can update data, TRIGGER AGENTIC FLOWS
> and MONITOR them."

Second directive (revision 2, same day):

> "Improve this plan so I can ask for a **complete prompt for Codex itself**,
> passing all the necessary info and context — that is, I want to be able to
> look at the STATE OF THE WIKI and request a complete prompt to solve a
> problem, with the option to **send / edit / execute** it, etc. Let's really
> think about **HUMAN ways of interacting with the WORK**, not just with the
> wiki."

## What revision 2 changes

Revision 1 designed a good machine (probe → job runner → git handoff → tray)
but a thin human: one click and an opaque spinner, with the prompt assembled
machine-side into `prompt.txt`, inspectable only after the fact. Revision 2
keeps every safety mechanism and re-centers the design on the **work brief** —
a complete, materialized prompt that the operator reads, edits, copies, saves
or executes. The deltas:

1. **The work brief becomes the boundary object between human and agent.** It
   is composed deterministically from the state of the wiki, shown in full
   *before* anything runs, and stored verbatim. Executing with local Codex is
   one exit among several — copy it into any agent, save it for later, or do
   the work yourself following the same brief.
2. **A new Brief studio surface + `briefs` API** (compose / edit / save /
   discard), shipped *before* the job runner — it is immediately useful with
   zero execution capability and degrades honestly.
3. **Wiki-state grounding.** A brief can be composed from the aggregate state
   (missions, freshness/quality report, audit findings), not only from a single
   page/packet/source — "look at the state of the wiki and ask for a prompt
   that solves a problem."
4. **The Jobs tray grows into a Work tray** modeled on the human delegation
   loop: brief → delegate → check in → deliverable → review → **accept or
   return with feedback** (a follow-up job on the same branch).
5. **Delegated work is visible in the 3D world** via the existing proposal
   salience encodings — the scene shows what is being worked on.
6. **Integrity guarantee: what you saw is what ran.** The executed prompt is
   byte-identical to the studio text (`brief_sha` verified at launch), and the
   runner refuses silently-stale briefs when targets changed underneath.

## North star

The cockpit learns to **write the perfect work order — and then hand you the
pen.** Today the operator can *see* everything (freshness radar, atlas,
districts, trails, the in-world reader) and can run deterministic, zero-token
checks and git plumbing — but the actual *writing* of memory (the deep read,
the edit, the new page) is a manual handoff to an agent in a terminal, where
the operator must reconstruct all the context from memory. This plan closes
that seam in two moves.

**First move — the brief.** From any point of the wiki's state (a mission, a
locked page, a decision packet, a raw source, or the aggregate health picture),
one click composes a **complete work brief**: the wiki's conventions
(AGENTS.md, `wiki.config.yaml`, `wiki.page-types.yaml`, the relevant skills),
the deterministic evidence for *why this work exists* (the same freshness
numbers and audit findings the cockpit displays), the concrete targets (page
content, packet, source context package), the operator's free-text intent, and
a pinned output contract (work on a `wiki/` branch, draft PR, never merge).
The operator reads it, edits it, and chooses the exit: **copy** it into any
agent anywhere (ChatGPT web, Codex CLI, Claude — the brief is portable),
**save** it as a draft, or **execute** it locally.

**Second move — the delegation.** The execute exit spawns a **scoped, local
Codex job** on the operator's own machine — authed once via `codex login`
(ChatGPT OAuth, token in `~/.codex`, never in the repo), sandboxed to the
working tree. It edits files, then the operator API drives the **existing**
`git_workflows` to open a `wiki/<theme>` branch, commit, and open a **draft
PR**. The operator watches a live JSONL log in the Work tray, receives the
deliverable as a draft PR in the approval inbox + a new `approve` mission, and
— when the result is close but not right — **returns it with feedback**,
spawning a follow-up job on the same branch instead of starting over.

**Codex proposes; the human disposes.** The deterministic core never gains an
LLM client; if Codex is not installed or not authed, the brief still composes
and copies — only the execute exit honestly reports "Codex not available".

## The human work loop

Revision 2's design principle, stated once and applied everywhere: the cockpit
should mirror **how humans already delegate work to a trusted collaborator**,
not invent a machine idiom. The loop:

1. **See the state** — the radar/missions already show what needs work and why.
2. **Name the problem** — pick a mission, a page, a packet, a source, or "the
   top problems of this context".
3. **Get a complete brief** — the cockpit writes the work order, with every
   piece of context materialized. Nothing is hidden in a black box.
4. **Adjust it** — the operator's words go in; sections can be trimmed or
   enriched. Writing the brief together is where delegation quality is decided.
5. **Choose who does it** — me (follow the brief by hand), the local Codex
   executor (sandboxed, gated), or any external agent (copy the brief out).
6. **Check in honestly** — a live, read-only log; `codex exec` is
   non-interactive, so mid-run steering is *not* pretended. Steering happens at
   review time.
7. **Receive a deliverable** — always a draft PR on a `wiki/` branch; never a
   silent mutation.
8. **Review and decide** — accept (the unchanged human gate: approve/merge) or
   **return with feedback** (a follow-up on the same branch, carrying the diff
   and your words).
9. **The wiki records the outcome** — the merged proposal feeds the existing
   missions/karma loop; delegated work is still your work, and closing it still
   counts.

Transparency (you always see exactly what the agent is told), control (edit
before send), portability (the brief works anywhere), reversibility (draft PR),
and feedback (returns, not restarts) — these five properties are the review
bar for every surface below.

## Critical findings

Four lenses (operator server surface, git/PR guardrails, cockpit
Missions/reader plumbing, Codex CLI/auth reality) were consolidated against the
live repo, plus the revision-2 human-interaction review. The findings that
motivate this plan, ranked:

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

2. **HIGH — revision 1 had no human-visible artifact between "click" and "agent
   runs".** The prompt — the single thing that determines the quality of the
   delegated work — was assembled server-side into `codex-jobs/<id>/prompt.txt`
   and inspectable only post-hoc. The operator could not read, correct, enrich,
   reuse or share the work order before committing plan quota to it. It also
   locked the wiki to one executor: an internal prompt serves only the built-in
   runner, while a materialized brief is portable to any agent the operator
   trusts. For a human, delegation starts with writing the brief together —
   not with a spinner.

3. **HIGH — every ingredient for a brief already exists except the composer.**
   The grounding is served (`GET /api/pages/{id}/content`, the snapshot bundle,
   the decision packet in `?packet=`, the source triage `result.targets`, the
   freshness/quality/audit reports that `deriveMissions()` and the status strip
   already read). The git/PR machinery is battle-tested and structurally gated
   (`git_workflows.py`: sanitized `wiki/<theme>` themes, clean-worktree
   preconditions, prefix-gated commit/publish, always-`--draft` PR, `dry_run`
   default True). The UI patterns are proven (StatusPill tones, the ingestion
   pipeline rail, the packet/missions trays, `CommandOutput` streaming `<pre>`,
   honest demo-mode disabling). The missing organs are (i) a deterministic
   **brief composer** and (ii) an **async job runner with persistent records** —
   the server today is purely synchronous request/response with only an 8s
   in-memory snapshot cache and no run history.

4. **HIGH — Codex has a first-class OAuth + headless mode that maps exactly onto
   the brief and the safety model.** `codex login` is "Sign in with ChatGPT" — no
   API key, draws on the operator's existing ChatGPT plan, token cached to
   `~/.codex/auth.json` (or OS keyring) *outside the repo*. `codex exec` runs
   headlessly with a task string; `--json` emits a JSONL event stream
   (`thread.started`/`turn.started`/`item.completed`/`turn.failed`,
   command/file-change items) that a job runner can tail for live status/log;
   `--sandbox workspace-write` fences edits to the working directory (network off
   by default); prompt + context can be fed via stdin (`codex exec - < brief.md`).
   This is precisely "execute a written brief, stream it, and keep it fenced."

5. **MEDIUM — the human gate is enforced structurally, so a Codex job cannot
   escape it even by accident.** `commit_proposal`/`publish_proposal`/
   `open_draft_pr` all early-return an error unless the current branch starts
   with the `wiki/` prefix; PR creation is always `--draft`; `sync_main` only
   does an ff-only pull on the default branch. A Codex job that *only* orchestrates
   these operations physically cannot push to `main`, cannot open a non-draft PR,
   and cannot approve or merge. The gate is not a convention Codex must remember —
   it is a wall it runs into. This matters twice in revision 2: it also means an
   **edited brief cannot break the gate** — the operator may rewrite the prompt
   freely, because the guarantees live in the execution harness, not in the
   prompt text. This plan requires the Codex path to reuse these ops verbatim
   rather than issue raw `git`/`gh`.

6. **MEDIUM — credentials and the LLM-free core are already protected by existing
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

- **No cloud service.** The brief composer and the Codex job runner live inside
  the existing LOCAL operator server (`127.0.0.1:8765`, CORS locked to the Vite
  dev origin). The runner shells out to the locally-installed `codex` binary as
  a subprocess, mirroring how `run_action`/`run_git_workflow` already
  `subprocess.run` allowlisted commands. No new network service, no remote
  runner, no Codex "cloud" mode.

- **OAuth credentials stay entirely outside the repo and the PR boundary.** Auth
  is obtained by the human running `codex login` (ChatGPT sign-in) once; the token
  lives in `~/.codex/auth.json` (or OS keyring; `CODEX_HOME`-overridable). The
  wiki server never receives, reads, stores, forwards, or versions a token or API
  key. Credentials never appear in a brief, branch, commit, PR body, snapshot, or
  job log. This matches the repo's established `.env`/`.gitignore` boundary
  (personal config untracked; `~/.codex` already treated as a per-user out-of-repo
  location by `.env.example`). No API-key mode is offered by the cockpit.

- **The prompt is never a black box.** The exact final prompt of every job is
  shown to the operator *before* launch and stored verbatim (`brief.md`,
  redaction rules applied to logs, not to the operator's own text). An edited
  brief is executed **as edited** — the runner never silently rewrites the
  operator's words. The only pinned part is the output-contract section,
  displayed locked in the studio with the note "this section ships with every
  brief" — pinning is honest here because the contract it states is enforced
  structurally anyway (finding 5).

- **Portability is honest.** The copy exit gives the full materialized text and
  the studio states plainly: outside the local executor, the sandbox, the queue,
  the redaction and the timeout do **not** apply — only the repo's own structural
  gates (prefix-gated `git_workflows`, `wiki_audit --check`, CI) still hold. No
  pretense that a brief pasted into ChatGPT web is supervised.

- **The human PR gate is unchanged.** Every executed brief lands as a
  `wiki/<theme>` branch + commits + a **draft** PR, exclusively through the
  existing `git_workflows` operation set. Codex can open/update a draft PR; it
  can never approve, mark ready, or merge. No direct writes to `main` or to
  generated operational pages (those are recompiled, not hand-edited).
  `--dangerously-bypass-approvals-and-sandbox` / `--yolo` is **forbidden**; the
  deprecated `--full-auto` is not used.

- **Deterministic core stays LLM-free.** No LLM client is added to `wiki_core`.
  The composer is pure deterministic Python (it reads files and reports and
  concatenates them — zero tokens); Codex is an external process. The zero-token
  honesty gates (`wiki_audit`, `wiki_quality_report`,
  `wiki_check_methodology_coverage`, `wiki_operation_compile`,
  `wiki_consolidate --check`, `pytest`, …) remain the guarantee, and a
  Codex-produced branch must pass them before draft→ready.

- **Honest degradation, no fabricated capability.** If `codex` is not installed
  or not authed, composing/editing/copying briefs still works fully; only the
  execute exit is disabled with an honest "Codex not available" state — never a
  fake run, spinner, or invented PR. Brief and job affordances only render when
  `mode === 'local_operator'` (the composer needs repo files; Codex is a local
  agent), mirroring the existing `demo.actionsOff`/`demo.gitOff` pattern. "A
  green gate is a real guarantee; a disabled gate is a silent lie."

- **Scope is one serialized job stream.** Reusing a ChatGPT-plan `auth.json` for
  automation is only valid on trusted private infra, single serialized stream, no
  concurrency. The runner enforces a queue of one active job (see Data contract).
  This integration is explicitly unsuitable for public/open-source multi-user
  deployments; the cockpit gates it behind `local_operator` mode.

## The design

### (a) The work brief — one artifact, five sections, four exits

**The composer** is a pure, deterministic Python module
(`wiki_core/web/briefs.py`) that turns a *brief spec* (grounding + intent +
theme) into a single markdown document. It is exposed via `POST /api/briefs`
and — crucially — **reused verbatim by the job runner**, so there is a single
source of truth: the text the operator saw in the studio is byte-identical to
the text fed to `codex exec` (`brief_sha` checked at launch). Every evidence
line in the brief carries its provenance (which snapshot file/field or report
produced it); the composer never invents.

**The brief document** always has the same five labeled sections:

```
# Work brief <id> — <mission kind> — <theme>
Generated <ts> from snapshot <generated_at> (repo <head_sha>). Composer v1.

## 1 · Conventions — the rules you operate under
AGENTS.md; wiki.config.yaml (contexts, approval gate wiki/ + draft PR,
llm.required_context_pass); wiki.page-types.yaml (typed pages are created via
scripts/wiki_new.py, never from blank files); skills: wiki-viva "Hard rules"
always, + wiki-ingestion-agent / wiki-llm-context-agent for ingest briefs,
+ wiki-privacy-publication when a public boundary is in play.

## 2 · State of the wiki — deterministic evidence
Why this work exists, in the same numbers the cockpit shows: freshness fields
("8d past stale_after_days"), audit findings, quality-report excerpts, mission
reasons, karma/mission counters. Each line cites its source file/field.

## 3 · Targets — the concrete object of the work
Page bodies + frontmatter + backlinks | packet pages | raw source + triage
result.targets + the deterministic context package (chunk_id/cache_key/text).

## 4 · Operator intent — in the operator's own words
Free text. Always editable; seeded from the mission's i18n "why" when spawned
from a mission row.

## 5 · Output contract — pinned; ships with every brief
Work on a `wiki/<theme>` branch. Edit files; create typed pages only via
scripts/wiki_new.py. Summarize your changes for a draft-PR body. NEVER push to
main, mark ready, or merge. The deterministic gates (wiki_audit,
wiki_consolidate --check, pytest) must pass before the draft leaves review.
```

**Materialization modes.** Section 1 (and large targets) can be embedded
`by-path` (compact — right for the local executor, which can read the repo) or
`full` (self-contained — right for the copy exit, where the receiving agent has
no repo access). The studio exposes this as a toggle, defaulting per exit; the
copy exit always offers the fully materialized text.

**Grounding sources** (the spec's `grounding`, one or more):

- **Locked page** — from the PageReader dock: the current `page` + loaded
  `PageContent` (body, `source_refs`, resolved_links, backlinks, path, context,
  freshness_state).
- **Decision packet** — from the `packetTray` in WorldView: the whole multi-page
  selection (`route.query.packet` ids → `packetPages` content). The packet is
  deep-linkable, so the grounding set is shareable.
- **Raw source** — from SourcesView: the source + `context` + the triage
  `result.targets` (target_pages / target_entities / next_steps) and the
  deterministic context package emitted by `wiki_llm_context_pass.py
  --emit-request`. Codex reads real excerpts and cannot invent context.
- **Wiki state** (new in rev 2) — the aggregate picture: `{scope:
  "missions"|"quality"|"audit", context?: <wedge>, limit: N}`. Composes a brief
  like "the 6 stalest pages of context *finance* with their overdue counts and
  the audit findings that touch them" — the operator looks at the radar, sees a
  sick cluster, and asks for one brief that addresses it as a unit.
- **Free-text intent** — a textarea (mirroring the existing `prBody` textarea)
  on every spawn surface; optional but always offered.

**The Brief studio** is the surface where the brief becomes the operator's.
It opens as a right-dock panel (same slot family as the reader dock) with:

- the five sections rendered collapsible, section 5 visibly **pinned**;
- **Intent** as a first-class textarea; the full text editable as raw markdown
  with a "restore composed version" reset;
- an honest size meter (characters/words — no fake token math);
- a staleness note ("composed from snapshot <generated_at>");
- the action row — the four exits:
  1. **Execute with Codex** (primary; only when the capability probe passes and
     mode is `local_operator`) → spawns the job with the exact studio text.
  2. **Copy prompt** (always available) → full materialized text to the
     clipboard, for ChatGPT web, Codex CLI by hand, Claude, anywhere.
  3. **Save draft** → persists the brief (status `draft`) to finish later; saved
     briefs are listed in the Work tray.
  4. **Discard.**
- when Codex is unavailable, exit 1 renders disabled with the honest reason
  ("codex not installed" / "not authed — run `codex login`"), and exits 2-3
  keep working: **the studio is useful with zero execution capability.**

### (b) Codex-as-local-job — the execute exit

**Auth (once, by the human).** The operator runs `codex login` in a terminal and
signs in with ChatGPT. The token caches to `~/.codex/auth.json`
(`auth_mode: "chatgpt"`, auto-refreshing). The cockpit never touches it. A
**capability probe** in the operator server checks (i) `codex --version`
succeeds and (ii) a valid auth session exists (presence of a non-expired
`~/.codex/auth.json` or `codex login status` if available). The probe result
(`{installed, authed, auth_mode, version}`) is surfaced through runtime config
so the UI can advertise the execute exit only when it is truly available.

**Launch endpoint.** `POST /api/codex/jobs` is registered in the server's POST
allowlist (`server.py:119-125`, alongside the existing five paths). It accepts
`{brief_id, brief_sha, parent_job_id?, dry_run}`, verifies the sha against the
stored brief (reject on mismatch — "what you saw is what runs"), re-hashes the
brief's target files and **blocks with an honest "targets changed since this
brief was composed — recompose or confirm"** when the wiki moved underneath
(operator can confirm-override), writes a persistent job record, enqueues it,
and returns `{job_id, status: "queued"}` immediately (non-blocking). Because
the server is synchronous today, this introduces the **one genuinely new
organ**: an in-process **job runner** — a single worker thread draining a
queue of one, with a job-state store on disk.

**The Codex invocation.** For each job the runner:
1. **Takes the brief verbatim** (`work-briefs/<brief_id>/brief.md`) — no
   reassembly, no silent rewriting. For follow-up jobs (returns), a follow-up
   brief is composed first (see section e).
2. **Runs Codex headlessly, sandboxed, streamed:**
   `codex exec - --cd <repo> --sandbox workspace-write -a on-request --json -o <final.md> < brief.md`
   - `-` reads the whole brief from stdin.
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

**Job lifecycle:** `queued → running → committing → delivered` (draft PR
exists; rev 1 called this `awaiting-review`) with `failed`/`cancelled`/
`returned` terminals-and-loops — from `delivered` the human gate owns the
object, and `returned` re-enters the queue as a follow-up job.

### (c) Missions integration — "gerar prompt" everywhere the work is named

`MissionsPanel.deriveMissions()` already emits `Mission` objects with
`kind ∈ {refresh, verify, evidence, approve}`, each carrying a `pageId` (except
`approve`, which routes to `/review`). Each row already renders one "open"
button; this plan adds a **second action per row: "Generate brief"** (opens the
studio pre-composed), mapped 1:1 to the task semantics already encoded in i18n:

- **`refresh` / `verify`** → brief grounded in `mission.pageId` + its content;
  intent seeded from the existing i18n why ("{days}d past its freshness window;
  re-verify facts and bump `updated_at`" / "set `updated_at` +
  `stale_after_days`").
- **`evidence`** → brief grounded in the page + its empty `source_refs`; intent
  "content page with no cited source; locate and cite provenance". (Network is
  off in `workspace-write`; if the source must be fetched, the operator attaches
  it first via SourcesView — the honest limitation is stated in the brief
  itself.)
- **`ingest`** (new mission kind, or the SourcesView affordance) → brief for
  the full agentic flow in (f).
- **`approve`** → **no brief, no CTA.** This kind *is* the human gate; it keeps
  routing to `/review`. Delegating it would be a category error.

The missions panel header gains one aggregate entry point — **"Brief the top
problems"** — composing a wiki-state brief from the current mission list
(scope `missions`, optionally filtered to a context wedge). The same
"Generate brief" affordance appears in the PageReader `readerActions` row
("Ask Codex to draft edits" in rev 1 — now it opens the studio first) and in
the `packetTray` actions ("Brief this packet"), threaded up through WorldView
exactly as `onRunAction` is today (`onComposeBrief(grounding, seedIntent)`).

For operators who trust the defaults, each CTA offers a long-press/secondary
**"Delegate now"** shortcut: compose + launch with the default brief in one
step — the brief is still recorded and inspectable in the tray; the studio is
skipped, never the artifact.

New i18n keys (`brief.studio.*`, `brief.exit.*`, `missions.brief.*`,
`work.tray.*`, `work.status.*`) are added to both EN and PT dicts following the
existing full-parity pattern. All CTAs render only in `local_operator` mode;
the execute exit additionally requires the passing capability probe; otherwise
honest disabled states, never hidden fakes.

### (d) Monitoring — the Work tray

A third command-bar tray joins the existing packet and missions trays in
`worldCommandBar`: a **Work** `trayButton` (e.g. `TerminalSquare`/`Activity`,
both already imported; badge = active jobs + saved drafts) with `setWorkOpen`
state that closes the other two, and a `workTray` panel rendered in the same
slot. Contents:

- **Saved briefs** (status `draft`) — resume in the studio, execute, or discard.
- **Job rows** in human lifecycle vocabulary, with a StatusPill reusing the
  proven tone vocabulary: draft→muted, queued→muted, running→info,
  committing→info, delivered→warn (it wants your review), returned→info,
  failed→bad, done→good.
- **The brief itself, one click away** — every job row links to the exact
  executed text (read-only once executed), because "what did I ask for?" is the
  first question a human asks about delegated work.
- **A step timeline** modeled on the ingestion `pipelineRail` (numbered stages:
  brief → run Codex → stage/commit → publish → open draft PR), each with its own
  StatusPill — directly reusing `gateStepTone`/`gateStatusLabel`.
- **A live log** `<pre>` streaming the redacted JSONL (reusing the
  `CommandOutput`/`worldOutputDock` stdout pattern), with agent messages, command
  executions, and file-change items. Read-only by design and labeled as such —
  no fake mid-run steering.
- **The produced branch + draft PR link** — the same `draft_pr_url` the approval
  inbox shows.
- **Review actions on `delivered`:** "Open draft PR" (the human gate) and
  **"Return with feedback"** (section e).
- **A "usage" note** — a job draws on the operator's ChatGPT plan quota; when
  limits are hit, the row degrades honestly to `failed` with a "plan limit
  reached" reason.

**Work visible in the world.** While a page is targeted by an active or
delivered job, the scene applies the **existing** proposal salience treatment
to its node (the encoding already exists for `approved_state === "proposal"` —
stem sparks + attention glow), so the radar honestly shows "this area is being
worked on" without inventing a new visual grammar. The tray button badge and
the node treatment clear together when the PR merges or the job is cancelled.

**Composition with the approval inbox (zero new plumbing).** Because an
executed brief's output *is* a proposal branch + draft PR via `git_workflows`,
its `draft_pr_url` flows into `bundle.git.proposal` → the inbox's stage-4
"Human gate" item and the `PrHandoffPanel` gate track unchanged. The finished
job materializes as a new `approve` mission (`kind='approve'`,
`href='/review'`). The Work tray's "open draft PR" link and the inbox's "Open
request" link are the same URL. Monitoring and approval are two views of one
object.

### (e) Returns — feedback instead of restarts

The missing human move in rev 1: the deliverable is *almost* right. Humans
don't re-brief from zero; they hand the work back with margin notes. On a
`delivered` job, **"Return with feedback"** opens a small intent box and:

1. Composes a **follow-up brief**: conventions (by path) + the branch's diff
   vs `main` (capped, with file list) + the draft PR state + the original
   intent + **the operator's feedback verbatim** + the pinned contract with one
   added line: *continue on the SAME `wiki/<theme>` branch; do not open a new
   one.*
2. The studio opens on it (same read/edit/copy/execute exits — a return can
   also be copied out to a different agent).
3. On execute, the runner uses one **new guarded git operation** —
   `resume_proposal(branch)`: prefix-checked (`wiki/` only), clean-worktree
   precondition, checks out the existing proposal branch. This is the single
   addition rev 2 makes to the `git_workflows` operation set; commit/publish
   then update the same draft PR (`open_draft_pr` already no-ops into "update"
   when the PR exists).
4. The job records `parent_job_id`; the tray renders the chain as one work
   thread (brief → delivered → returned → delivered …), not as unrelated jobs.

This also enforces the existing repo rule "no parallel branch for a page with
an open proposal — update it, mark superseded": a new brief targeting a page
with an open proposal is steered into a return on that branch instead of a
fresh theme.

### (f) Agentic flows — chaining ingest → deep-read → propose

The richest flow is source ingestion, which the plan expresses as a **chained
job** whose brief embeds the deterministic-first pipeline and the delegated
deep-read protocol without ever writing canonical memory directly:

1. **Deterministic prep (server, zero-token, already exists).** input-stage compile
   → manifest → text/chunks → index → `wiki_llm_context_pass.py --emit-request`
   produces the machine-readable context package. This is prerequisite state, run
   via the existing `run_ingestion_step` (WRITE steps stay `dry_run`, stage must be
   `ready`).
2. **Delegated deep read (Codex).** The brief embeds the context package +
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

The operator triggers this from SourcesView with one click ("Brief the
ingestion" → studio → execute), watches the whole chain in the Work tray step
timeline — each deterministic prep step and the Codex deep-read/consolidate
steps appear as timeline rows — and the job refuses to reach `delivered` until
the honesty gates pass locally (draft stays draft while any chunk lacks a
recorded deep-read result under `required_context_pass: true`).

## Data-contract / API changes

**New endpoints (registered in `server.py` POST/GET dispatch):**

*Briefs (agent-neutral):*
- `POST /api/briefs` — compose. Body: the brief spec below. Returns the brief
  record with the materialized text. Deterministic, zero-token, synchronous.
- `GET  /api/briefs` — list brief records (drafts + executed, for the tray).
- `GET  /api/briefs/{id}` — single brief (record + text).
- `POST /api/briefs/{id}` — save edited text (allowed only while status is
  `draft`; recomputes `brief_sha` and `size_chars`).
- `POST /api/briefs/{id}/discard` — mark discarded.

*Jobs (the execute exit):*
- `POST /api/codex/jobs` — launch. Body: `{brief_id, brief_sha,
  parent_job_id?, dry_run}`. Verifies sha + target freshness. Returns
  `{job_id, status}`. Non-blocking (enqueues; runner drains).
- `GET  /api/codex/jobs` — list job records (for the tray).
- `GET  /api/codex/jobs/{job_id}` — single job record (status + step timeline +
  branch/PR + brief_id).
- `GET  /api/codex/jobs/{job_id}/log` — the redacted JSONL log (tail/stream; may
  be served via the existing `/api/snapshot/{name}` file convention or a dedicated
  streaming route).
- `POST /api/codex/jobs/{job_id}/cancel` — cooperative cancel (kills the subprocess,
  marks `cancelled`; never force-pushes or half-commits).
- `POST /api/codex/jobs/{job_id}/return` — compose the follow-up brief from
  `{feedback}` and return it (the studio opens; execution is a separate
  explicit launch).
- **Capability probe** surfaced through `/api/health` and runtime config:
  `codex: {installed, authed, auth_mode, version}`.

**Brief spec (compose request):**
```
{
  "mission_kind": "refresh|verify|evidence|ingest|state|null",
  "grounding": {
    "page_ids": ["..."],                    // locked page / packet
    "source": {"path|url", "context"}|null, // ingest
    "attach_context_package": true|false,   // ingest deep-read
    "state_report": {"scope": "missions|quality|audit",
                     "context": "<wedge>"|null, "limit": N}|null
  },
  "intent": "free-text operator intent",
  "theme": "sanitized <topic> for wiki/<prefix>",
  "materialize": "refs|full"
}
```

**Brief record (`derived_root/work-briefs/<brief_id>.json` + `brief.md`):**
```
{
  "brief_id", "created_at", "updated_at",
  "status": "draft|executed|discarded",
  "spec": {…},
  "text_path": "work-briefs/<brief_id>/brief.md",
  "brief_sha": "sha256 of the exact text",
  "size_chars", "snapshot_generated_at",
  "target_hashes": {"<path>": "sha256", …},   // staleness guard
  "job_id": null | "…"
}
```

**Job record (`derived_root/codex-jobs/<job_id>.json`, mirrored into the snapshot):**
```
{
  "job_id", "brief_id", "brief_sha", "parent_job_id": null|"…",
  "created_at", "updated_at",
  "status": "queued|running|committing|delivered|returned|done|failed|cancelled",
  "reason": "…",                 // e.g. "plan limit reached", "codex not authed",
                                 //      "targets changed since brief composed"
  "mission_kind", "intent",
  "steps": [{"id","label","status"}],   // brief/run/commit/publish/open-pr
  "codex": {"session_id","auth_mode","final_message_path"},
  "branch": "wiki/…"|null,
  "draft_pr_url": "…"|null,
  "log_path": "codex-jobs/<job_id>/log.jsonl",
  "human_gate_state": "…"        // mirrors git_ops proposal state once a PR exists
}
```

**Stores.** Two new derived-tree dirs (siblings of `source-manifests`,
`llm-cache`, `web-snapshot`): `derived_root/work-briefs/` (per-brief
`<id>.json` + `brief.md`) and `derived_root/codex-jobs/` (per-job `<id>.json`,
`log.jsonl`, `final.md`). Both git-ignored (`data/derived/**` already blocked).

**Snapshot surface.** `work_briefs.json` and `codex_jobs.json` are added to
`SNAPSHOT_FILES` (`schemas.py`) and to the cockpit `FILES` map (`snapshot.ts`)
so the tray loads through the existing `loadFromBase()` path.
`/api/snapshot/{name}` already serves arbitrary snapshot files, so status/log
surfacing reuses that route.

**Cockpit client wrappers (`snapshot.ts`).** `composeBrief(spec)`,
`listBriefs()`, `saveBrief(id, text)`, `discardBrief(id)`, `spawnCodexJob(ref)`,
`listCodexJobs()`, `pollCodexJob(id)`, `streamCodexLog(id)`,
`cancelCodexJob(id)`, `returnCodexJob(id, feedback)` — each identical in shape
to `runGitWorkflow`/`runIngestionStep` (POST/GET to `apiUrl('…')`, parse JSON,
throw on `!ok`). `App.tsx` wires them with the existing `busyAction`/notice-toast
+ honest demo-mode disabling.

**Git surface.** `git_workflows` operations are reused as-is, with exactly
**one guarded addition** (Phase 5): `resume_proposal(branch)` — `wiki/`-prefix
check, clean-worktree precondition, checkout of an existing proposal branch,
for the returns loop. No other new git op; no raw `git`/`gh` from the Codex
path.

## Implementation phases

Each phase is independently shippable and leaves the cockpit honest. The
composer ships **before** the runner: briefs are useful with zero execution
capability.

### Phase 0 — Capability probe + honest degradation (ship first)
- **Deliverables:** `codex` capability probe in the server; `codex:{installed,
  authed,auth_mode,version}` in `/api/health` and runtime config; the UI reads it;
  a "Codex not available / not authed" state everywhere a future execute CTA will
  live; i18n keys (EN+PT). No composer, no runner yet.
- **Acceptance:** with `codex` absent/unauthed, the cockpit shows the honest
  unavailable state and no execute CTA is clickable; with `codex` authed, the probe
  reports `authed:true, auth_mode:"chatgpt"`. `pytest` covers the probe's three
  states (absent, installed-unauthed, authed) via a stubbed CLI.

### Phase 1 — Brief composer + Brief studio (no runner)
- **Deliverables:** `wiki_core/web/briefs.py` (pure, deterministic, tested);
  `POST/GET /api/briefs`, `GET/POST …/{id}`, `…/{id}/discard`; the
  `derived_root/work-briefs/` store; the Brief studio panel (five sections,
  pinned contract, intent textarea, raw-edit + reset, size meter, staleness
  note); the **copy** and **save** exits; "Generate brief" entry points on
  mission rows, PageReader `readerActions`, `packetTray`, SourcesView, and the
  missions-panel header ("Brief the top problems", wiki-state grounding);
  `work_briefs.json` in the snapshot; EN+PT i18n.
- **Acceptance:** from a stale-page mission, "Generate brief" yields a complete
  brief whose evidence numbers match what the cockpit displays; edits persist
  and recompute `brief_sha`; copy delivers fully materialized text; with
  `codex` absent everything works except the (disabled, honest) execute exit;
  `pytest` asserts composition for each grounding kind, provenance lines,
  materialize modes, and sha stability (same spec + same snapshot → same sha).

### Phase 2 — Job runner + execute exit
- **Deliverables:** the in-process single-worker job runner + on-disk job store
  (`derived_root/codex-jobs/`); `POST/GET /api/codex/jobs`, `GET …/{id}`,
  `…/{id}/log`, `POST …/{id}/cancel`; sha verification + target-hash staleness
  guard (block + confirm-override); `codex exec - --cd <repo> --sandbox
  workspace-write -a on-request --json` invocation fed the studio text verbatim,
  with JSONL tailing + `SECRET_VALUE_RE` redaction; `git_workflows` handoff
  (start→stage→commit→publish→open_draft_pr, `dry_run` honored);
  `codex_jobs.json` in the snapshot; the "Execute with Codex" exit wired in the
  studio. Driven by a synthetic fixture (a fake `codex` shim emitting canned
  JSONL that "edits" a fixture file).
- **Acceptance:** a job launched from a studio brief against the fixture shim
  reaches `delivered` with a real `wiki/<theme>` branch + draft PR (against a
  test remote) or a faithful `dry_run` preview; the executed prompt is
  byte-identical to the studio text; a tampered/mismatched sha is rejected; a
  brief whose targets changed is blocked until recomposed or confirmed; the log
  is redacted; a second launch while one is running is queued, not run
  concurrently; cancel kills the subprocess and marks `cancelled` with no
  half-commit. `pytest tests/` green; the sandbox never leaves the workdir; no
  path can push to `main` or open a non-draft PR.

### Phase 3 — Work tray + monitoring + work-in-the-world
- **Deliverables:** the third `Work` `trayButton` + `workTray` panel (badge =
  active jobs + drafts); saved-brief rows; job rows with StatusPill lifecycle;
  the executed brief one click away (read-only); the step timeline (reusing
  `pipelineRail`/`gateStepTone`); the live JSONL log `<pre>` (reusing
  `CommandOutput`, labeled read-only); branch/draft-PR links; the scene's
  proposal-salience treatment on pages targeted by active/delivered jobs;
  approval-inbox composition (delivered job ⇒ `approve` mission, same
  `draft_pr_url`); honest demo/unavailable disabling.
- **Acceptance:** launching a job (dev/fixture) shows queued→running→delivered
  with a streaming log, the exact brief attached, and a working "open draft PR"
  link; targeted nodes light up with the existing proposal treatment and clear
  on merge/cancel; the tray closes the packet/missions trays and vice-versa; in
  demo or Codex-unavailable mode the tray shows saved briefs and the honest
  state, and no live job.

### Phase 4 — Ingestion chain (ingest → deep-read → consolidate → propose)
- **Deliverables:** the `ingest` brief flow wiring SourcesView's "Brief the
  ingestion"; the runner chains the deterministic prep (via
  `run_ingestion_step`, WRITE steps `dry_run`) then the Codex deep-read brief
  embedding the context package + `context_deep_read.v3` + ingestion skills,
  then consolidate/integrate, then the `wiki/ingest-…` proposal; the tray step
  timeline reflects the full chain; the job refuses `delivered` until the LLM
  honesty gate passes.
- **Acceptance:** ingesting a fixture source produces a proposal branch with a
  normalized event whose `consolidated_into` is closed and target pages reference
  the source back; `wiki_consolidate.py --check` passes on the branch;
  `sensitivity` flags are set without raw values echoed; the deep read fills
  quadrants or declares explicit absence. Zero tokens are spent by the Python core.

### Phase 5 — Returns, recurring briefs, honesty polish, downstream adoption
- **Deliverables:** "Return with feedback" on `delivered` jobs → follow-up brief
  (diff + PR state + feedback + same-branch contract) → studio → execute via the
  new guarded `resume_proposal(branch)` op; job threads (`parent_job_id`) in the
  tray; "no parallel branch for a page with an open proposal" steered into
  returns; **recurring briefs** (save a spec as a named template — "monthly
  statement ingest" — recomposed fresh on each use, never stale text); the
  plan-usage note in the tray ("plan limit reached" degradation); `docs/`
  operator note on `codex login` (and `--device-auth` for headless boxes); final
  gate wiring so a Codex branch runs the full deterministic gate set before
  draft→ready; downstream adaptation notes (the base kit ships the capability,
  private repos enable it).
- **Acceptance:** returning a delivered job lands a follow-up commit on the SAME
  branch and updates the same draft PR, with the feedback verbatim in the
  follow-up brief; a second brief on a page with an open proposal is steered
  into a return; a recurring brief recomposes with fresh evidence; a plan-limit
  failure surfaces honestly as `failed` with a reason, not a stall; a Codex
  branch cannot be marked ready while any honesty gate is red; the base cockpit
  with `codex` absent behaves identically to today except briefs still compose
  and copy.

## Risks and mitigations

- **Codex not installed or not authed.** → Capability probe + honest "Codex not
  available/not authed" state; the execute exit disabled, compose/copy/save
  fully functional; no fake run (Phases 0-1). The operator is told to run
  `codex login` (or `--device-auth` on a headless box).

- **The operator edits the brief into something that violates conventions.** →
  Acceptable by design: the guarantees are structural, not prompt-level
  (finding 5). The pinned contract section always ships; `git_workflows` makes
  main-push/non-draft-PR/merge physically unavailable; the honesty gates +
  audit + CI judge the branch output, not the prompt input. The studio never
  silently rewrites the operator's text — control stays human.

- **A copied brief is executed elsewhere, unsupervised.** → Stated honestly in
  the studio: outside the local executor there is no sandbox, queue, timeout or
  redaction — only the repo's structural gates still hold (prefix-gated ops,
  audit, CI, draft-PR review). The brief's contract section carries the same
  instructions regardless of executor.

- **The wiki changes between composing and executing a brief.** → The brief
  records `snapshot_generated_at` + per-target content hashes; launch re-hashes
  and blocks with "targets changed — recompose or confirm"; the tray labels
  confirmed-stale runs. No silent execution of outdated evidence.

- **Secret / token leakage.** → Codex is invoked as a subprocess and never handed a
  token; auth lives in `~/.codex` outside the repo. All captured stdout/JSONL is
  scrubbed by `SECRET_VALUE_RE` before reaching the cockpit or the log file. Any
  token that ever lands in a versioned file fails `wiki_core/detectors/secrets.py`
  in `wiki_audit --check` and CI. Sandbox is `workspace-write` (network off), never
  `--yolo`. The composer embeds page/source content that is already in the repo —
  it introduces no new secret surface.

- **Runaway or long jobs.** → `codex exec` with `-a on-request` and a
  `workspace-write` sandbox fenced to the workdir; a per-job timeout on the
  subprocess; cooperative cancel endpoint that kills the process cleanly (no
  half-commit); a queue of one so jobs cannot pile up or race the git tree.

- **Scope creep / wrong-scope edits.** → The brief is grounded in explicit targets
  only; the contract forbids pushing/merging and pins the `wiki/` prefix;
  `stage_paths` only stages files already in the changed-set, and the branch is a
  draft PR a human reviews. The sandbox prevents edits outside the workdir.

- **Concurrency / shared auth corruption.** → Single serialized job stream enforced
  by the runner; the plan states the ChatGPT-plan `auth.json` reuse is
  single-stream, private-infra-only, and that the seed file must not be overwritten
  (it holds refreshed tokens). Explicitly unsuitable for public multi-user deploys.

- **Plan-quota exhaustion.** → A job draws on the operator's ChatGPT plan; on limit
  the runner marks the job `failed` with a "plan limit reached" reason and the tray
  shows it honestly rather than stalling. Composing briefs costs zero quota —
  the operator can keep preparing work while limits recover.

- **Determinism drift.** → No LLM client enters `wiki_core`; the composer is
  deterministic file/report concatenation; Codex only produces a proposal
  branch; the zero-token honesty gates and `wiki_operation_compile` (cockpit ==
  recompile at HEAD) remain the guarantee; generated operational pages are
  recompiled, never hand-edited by Codex.

- **Human gate bypass.** → Structurally impossible via `git_workflows`
  (prefix-gated commit/publish, always-`--draft` PR, no merge op;
  `resume_proposal` is prefix-gated too). The plan forbids raw `git`/`gh` from
  the Codex path.

## Definition of done

- From any point of the wiki's state — a mission, the locked page, a packet, a
  raw source, or the aggregate health picture — one click composes a **complete
  work brief** (conventions + deterministic evidence + targets + my intent +
  the pinned contract), and I can **read, edit, copy, save or execute** it.
- **What I saw is what ran:** the executed prompt is byte-identical to the
  studio text (`brief_sha` verified), stored verbatim, and one click away from
  every job row; stale briefs are blocked, not silently run.
- The brief is **agent-portable**: the copy exit yields a self-contained prompt
  for any agent, with the supervision difference stated honestly; the local
  execute exit is the only supervised path (sandbox, queue, redaction, timeout).
- Work behaves **humanly**: I delegate from the missions where the work is
  named, check in on a live read-only log, receive a draft PR, and **return it
  with feedback on the same branch** instead of restarting; job threads read as
  one piece of work; the scene shows what is being worked on via the existing
  proposal encodings.
- Auth is ChatGPT OAuth only; no API key is stored or requested; the token stays in
  `~/.codex` and never appears in any brief/branch/commit/PR/snapshot/log.
- Every executed brief lands as a `wiki/<theme>` branch + commits + a **draft** PR
  through the existing `git_workflows` (plus the single guarded
  `resume_proposal` for returns); Codex cannot approve, mark ready, or merge;
  no writes to `main` or generated operational pages.
- The Work tray shows drafts and queued/running/delivered/returned/failed with a
  redacted live log, the exact brief, and the branch/PR link; the produced draft
  PR composes into the existing approval inbox + a new `approve` mission with
  zero new plumbing.
- The ingestion chain (deterministic prep → Codex deep-read → consolidate/integrate
  → propose) runs and watches from one click, and refuses `delivered` until
  the honesty gates pass; ingesting = integrating is enforced.
- With `codex` absent or unauthed, briefs still compose/edit/copy/save; in
  demo/static mode the cockpit degrades honestly (no CTA fakes, no fake jobs).
  The deterministic core remains LLM-free; all zero-token gates and
  `pytest tests/` stay green on every Codex-produced branch.
- Landed in the open-source kit first, covered by a synthetic `codex`-shim fixture
  and tests, passing CI, before any private downstream repo enables it.
