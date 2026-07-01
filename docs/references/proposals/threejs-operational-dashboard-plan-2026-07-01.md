---
title: "Plan - Three.js operational wiki cockpit"
page_id: plan-threejs-operational-dashboard-2026-07-01
page_type: methodology_plan
aliases:
  - Three.js operational cockpit
  - Human operations dashboard
  - Wiki Viva web cockpit
  - 3D wiki operations interface
tags:
  - wiki/methodology
  - wiki/operations
  - wiki/interface
  - wiki/threejs
  - status/plan
date: "2026-07-01"
status: plan
context: system
visibility: private_reference
related_pages:
  - memories/operations.md
  - memories/system/wiki/daily-operation.md
  - memories/system/wiki/architecture.md
  - memories/system/wiki/pr-governance.md
  - memories/system/wiki/command-reference.md
  - memories/system/wiki/gates-and-audit.md
target_version: "wiki-viva v7.0 candidate"
audience: "wiki-viva maintainers, downstream wiki owners and implementation agents"
scope: "implementation plan for a base open-source web cockpit, later adapted by private/local wiki repos"
---

# Plan - Three.js Operational Wiki Cockpit

Updated on: 2026-07-01.

This plan defines a **mind-blowing but operationally honest** web interface for Wiki Viva: a Three.js-powered command cockpit that helps a human operate, update, approve and understand a living Markdown/Git wiki without having to think in raw commands, branches, hashes or CI logs.

The first implementation target is the open-source `wiki-viva-kit`. The private/local wiki becomes a downstream adapter and validation target only after the base contracts, UI patterns and safety model are implemented in the public kit without personal context.

The initial product must be designed to run locally from a real repository checkout. Cloud deployment is a later adapter concern: each implementation/downstream wiki owns its own deployment target, while the open-source kit supplies clean build artifacts, runtime contracts and examples that make Vercel or GCP deployment straightforward when a repo is ready for it.

## Mission

Build a **human operations dashboard** for a living wiki.

The interface should answer, as the first screen of the day:

1. What needs my attention now?
2. What is stale, blocked, risky or waiting for approval?
3. Which sources/actions/decisions are driving the next update?
4. What changed, why did it change, and what proof supports it?
5. Which Git branch, proposal or Pull Request needs human attention?
6. What button can a non-technical owner safely press to advance the wiki?

The web cockpit must not replace the existing Markdown/Git model. It is an operating layer over the same contracts:

- Markdown remains canonical memory.
- Git remains the substrate.
- `main` remains the approved wiki.
- `wiki/<theme>` branches remain proposals.
- The GitHub Pull Request remains the human gate.
- Deterministic Python remains responsible for reproducible extraction, audit, graph, score, source registry, cockpit compilation and validation.
- The UI can guide, preview and execute allowed workflows, but it must never create invisible truth outside the repository.

## Current baseline used by this plan

### Open-source kit baseline

The base repository already contains the right primitives:

- a Markdown/Git-first living operational wiki;
- deterministic Python core in `wiki_core/`;
- `scripts/wiki_*.py` CLIs for ingestion, audit, quality, source registry, operation compilation, PR summaries, OKF export and graph checks;
- a daily operations page compiled from wiki/Git/derived state;
- GitHub PR as the human approval gate;
- configurable paths, language, branch prefix and approval policy through `wiki.config.yaml`;
- Open Knowledge Format export/check/import-preview/visualization helpers.

Relevant internal pages:

- [README.md](../../../README.md)
- [Architecture](../../../memories/system/wiki/architecture.md)
- [Daily operation](../../../memories/system/wiki/daily-operation.md)
- [Governance and PR flow](../../../memories/system/wiki/pr-governance.md)
- [Command reference](../../../memories/system/wiki/command-reference.md)
- [Operations cockpit](../../../memories/operations.md)

### Downstream/private wiki constraints, sanitized

The downstream private wiki proves the base must be configurable, not hardcoded:

- localized memory paths can differ from `memories/`;
- generated language can be Portuguese while the open-source kit remains English;
- contexts can be many and domain-specific;
- operational score/karma can be disabled by config;
- private PII can be allowed inside private pages while access secrets are still blocked everywhere;
- the cockpit has real human actions and operational context vitality, so the UI must handle dense daily work, not only toy examples.

No private content should be copied into the public kit. The open-source implementation should ship sample data only.

## Product thesis

Most wiki tools are editors. Wiki Viva needs an **operations room**.

The mental model is not “browse a documentation site.” The mental model is:

> “I am entering mission control for my living knowledge system. The system shows what needs attention, why it matters, what evidence exists, and which safe proposal-producing action I can take next.”

The Three.js layer exists to make invisible wiki dynamics visible:

- context vitality becomes orbit energy;
- stale pages become cooling/dimming nodes;
- pending decisions become gravity wells;
- actions become moving task comets;
- source ingestion becomes a visible pipeline;
- PR approval becomes a gate with proof shields;
- source_refs and moc_parent become inspectable provenance links;
- daily operation becomes a real cockpit, not a static Markdown table.

## Non-goals

- Do not build a hidden database as the new source of truth.
- Do not bypass PR review.
- Do not add an embedded LLM client to the deterministic Python core.
- Do not require a live GitHub token for read-only local exploration.
- Do not make Three.js the only way to use the wiki; every 3D view needs a 2D/list fallback.
- Do not leak downstream/private repo details into the open-source kit.
- Do not make a beautiful dashboard that can silently write to `main`.
- Do not make Vercel, GCP or any hosted platform required for the first implementation.

## Experience principles

### 1. Human-first, not CLI-first

The UI should expose human actions such as:

- “Start my day”
- “Review what changed”
- “Add a source”
- “Refresh the cockpit”
- “Explain why this is stale”
- “Create a proposal branch”
- “Run the gates”
- “Open a draft PR”
- “Archive resolved proposals”
- “Export/share an OKF bundle”

The backend maps those actions to safe `wiki_*` commands and Git operations.

### 2. Honesty before wow

Every impressive animation must preserve epistemic status:

- approved vs proposed;
- fresh vs stale;
- source-backed vs unsourced;
- clean vs failing gate;
- private vs public-candidate;
- pending vs closed ingestion;
- conceptual review pending vs mechanically valid.

The UI should never imply that generated, draft or branch-local content is approved memory.

### 3. Progressive disclosure

A non-technical owner sees the task and consequence first. Technical details appear only when needed:

- first layer: “3 actions need attention.”
- second layer: “2 stale contexts, 1 pending decision.”
- third layer: “Generated by `wiki_operation_compile.py`; failing check: `stale_after_days`.”
- fourth layer: raw command, stdout, diff, file paths and commit SHA.

### 4. Every write is reviewable

Mutating actions should produce one of these states:

- a dry-run preview;
- a derived artifact;
- a branch-local change;
- a commit on a proposal branch;
- a draft PR;
- a PR update.

There should be no “apply directly to approved wiki” button in the base UI.

### 5. Git items are first-class operational objects

The cockpit should operate Git and PR state as human workflows, not as hidden implementation details. Branches, commits, diffs, local dirty state, upstream divergence, draft PRs, gate results and review readiness should each have visible UI state.

The user-facing actions are:

- “Sync approved wiki”
- “Create proposal branch”
- “Switch proposal”
- “Review local changes”
- “Stage known generated files”
- “Commit proposal”
- “Publish proposal branch”
- “Open/update draft PR”
- “Run PR summary”
- “Prepare for human review”

The base UI must not expose force push, hard reset, direct merge to `main`, arbitrary checkout, arbitrary rebase or remote deletion as normal actions. If later versions add advanced maintenance flows, they need a separate safety design.

### 6. 3D as sensemaking, 2D as precision

The 3D interface should create spatial understanding and emotional salience. Precise editing, reading and review still needs crisp 2D panels, tables, Markdown preview and diffs.

### 7. Local-first, public-safe

The read-only cockpit must run from a static snapshot. The action runner should be an explicit local server mode bound to localhost, with command allowlists and visible logs.

The local version is not a lesser demo. It is the primary first implementation because it can operate a real checkout, respect private data boundaries and make every write visible before any network or hosted deployment exists.

## Information architecture

### App shell

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Command bar: Ask / Search / Run safe action / Jump to page           │
├───────────────┬───────────────────────────────────────┬─────────────┤
│ Mission rail  │ Three.js operational scene             │ Action pane │
│               │ + 2D overlay cards                     │             │
│ Today         │                                       │ Details     │
│ Graph         │                                       │ Proof       │
│ Sources       │                                       │ Diff        │
│ Review        │                                       │ Actions     │
│ Health        │                                       │ Logs        │
│ Settings      │                                       │             │
├───────────────┴───────────────────────────────────────┴─────────────┤
│ Timeline strip: branch, proposals, source events, gate runs          │
└─────────────────────────────────────────────────────────────────────┘
```

### Core routes

| Route | Name | Purpose |
| --- | --- | --- |
| `/` or `/ops` | Today cockpit | First screen: actions, alerts, stale contexts, PRs and source pressure. |
| `/graph` | Knowledge galaxy | Spatial map of root entity, contexts, pages, relations and provenance. |
| `/sources` | Source inbox | Add/triage/read source state, route to context and create ingestion proposals. |
| `/review` | Human gate | Review branch/PR changes, gate results, privacy hints and semantic diff. |
| `/pages/:page_id` | Page cockpit | Human summary, status, freshness, relations, source_refs, backlinks and actions. |
| `/health` | System health | Audit, quality, graph, freshness, ingestion closure, cache and derived artifacts. |
| `/settings` | Repo profile | Read-only config view first; guided config editor later via PR. |

## Home page: “Today cockpit”

The initial page is the operational cockpit transformed into an interactive command surface.

### Above-the-fold layout

1. **Top command strip**
   - Greeting with repo owner label and current repo name.
   - Current mode: read-only snapshot, local operator, GitHub-connected, or degraded/offline.
   - Branch state badge: approved `main`, proposal branch, dirty worktree, or detached snapshot.
   - One primary CTA: the next safest action.

2. **Do now stack**
   - Ranked cards from pending decisions, owner actions, stale contexts, failing gates, source backlog and open PR review needs.
   - Each card has: human title, why it matters, risk level, evidence link, suggested next action and “show command details.”
   - Cards are grouped by intention: Decide, Review, Refresh, Ingest, Fix, Approve.

3. **System pulse orb**
   - A central Three.js object representing the root entity.
   - Orbit rings represent contexts.
   - Ring brightness means freshness.
   - Red/amber flares mean stale contexts, broken gates or pending decisions.
   - Small moving particles represent recent operations/events.
   - The orb breathes slowly when the system is healthy; it becomes tense/jittered only for real alerts.

4. **Gate status panel**
   - Local gates: audit, operation compile check, quality, methodology coverage, input stage, PR summary.
   - Each gate is shown as a shield: unknown, running, pass, warning, fail.
   - Clicking a shield opens translated explanations plus raw logs.

5. **Open proposal lane**
   - Shows current `wiki/*` branches and PRs as capsules moving toward the human gate.
   - Draft PRs are translucent; ready PRs are solid; merged PRs cross into the approved memory layer.

### Secondary panels

- **Context vitality heatmap**: all contexts ordered by urgency, with freshness countdown.
- **Ingestion closure**: ingested sources vs closed events, unresolved source pressure, compression ratio.
- **Action queue**: pending action IDs with source page, state and owner-friendly next step.
- **Decision queue**: decisions that block progress.
- **Resume links**: root MOC, system log, operational pass, coverage, source registry.
- **What changed since last visit**: commits, PRs, generated pages and newly stale contexts.

### Morning animation

On first load:

1. Camera starts above the root orb.
2. Context rings expand in order of urgency.
3. Stale or blocked items emit visible pulses.
4. The camera settles on the top `Do now` card.
5. The action pane opens with a plain-language explanation: “Start here because…”.

Respect `prefers-reduced-motion`: reduce this to a simple fade and focus outline.

## Three.js visualization modes

### 1. Knowledge galaxy

A 3D graph view that makes the wiki’s structure legible.

#### Objects

| Object | Visual metaphor | Data source |
| --- | --- | --- |
| Root entity | central star / command core | `root_entity.page` |
| Context hub | orbiting planet / ring anchor | context hub pages |
| Memory page | node / satellite | frontmatter pages |
| Source page | crystal / evidence shard | `page_type: source` and source registry |
| Action | comet with trail | action pages and pending queue |
| Decision | diamond / gravity well | decision pages |
| Claim | small evidence-linked node | claim pages |
| PR/proposal | capsule outside approved orbit | Git state / GitHub PR |
| Derived artifact | ghost layer | derived snapshot metadata |

#### Edges

- `moc_parent`: navigation hierarchy edge.
- `source_refs`: evidence/provenance edge.
- Markdown links: semantic/navigation references.
- Git proposal impact: pages changed together in a PR.
- Ingestion chain: source -> chunks -> event -> proposal -> consolidated page.

#### Motion rules

- Approved memory lives in stable orbit.
- Proposal branches live in a parallel “draft dimension” slightly offset from the approved graph.
- Stale pages slowly lose brightness and drift outward.
- Pending decisions create local gravity wells that attract related actions/pages.
- Source_refs emit short light pulses from claim/page back to evidence on hover.
- Newly changed nodes glow with a short-lived halo.
- Nodes with failing gates show an interrupting shimmer, never a decorative red glow without an actual reason.

#### Interactions

- Hover: show page title, type, context, status, freshness and top relation.
- Click: open the action pane with Markdown preview, proof links, related actions and possible workflows.
- Double click: focus camera and isolate neighborhood.
- Shift+click/lasso: select a set of pages and generate an impact/review bundle.
- Search: command bar highlights matching nodes and draws a route from root to result.
- “Why am I seeing this?”: explains the source of the node and the exact data fields that placed it there.

### 2. Ingestion pipeline theatre

A 3D pipeline that visualizes source -> memory compilation.

```text
Source
  -> Manifest
  -> Text / chunks
  -> FTS index
  -> Secret pre-scan
  -> LLM context package
  -> Agent deep read result
  -> Normalized event
  -> Ingestion proposal
  -> PR human gate
  -> Approved memory
```

Each stage is a station. A source moves through stations as a visible packet:

- blocked secret: packet stops before persistence and shows a hard stop;
- PII in private page: packet shows an informational badge, not a block;
- missing LLM pass: packet pauses at context package;
- proposal created: packet becomes a draft capsule;
- PR approved: capsule merges into the memory galaxy.

Human-friendly labels should sit above technical command names.

### 3. Human gate review room

A visual PR review experience.

- Center: changed pages arranged by context.
- Left: PR metadata, branch, status, gate results.
- Right: semantic diff and Markdown preview.
- Bottom: checklist: conceptual diff read, privacy checked, cockpit recompiled, honest status.
- 3D cue: a gate with shields for mechanical validations and a separate human key for conceptual approval.

The interface must visually separate:

- machine-valid mechanical status;
- human-reviewed conceptual correctness;
- privacy/publication review;
- pending items intentionally left open.

### 4. Source inbox and triage nebula

A workspace for adding or routing sources without CLI knowledge.

- Drag/drop source or paste URL.
- Choose context using semantic cards, not raw slugs only.
- Choose or confirm source type.
- See privacy pre-triage before writing.
- Preview proposed target pages and perspectives from the input stage.
- Run dry-run first.
- Create a proposal branch and draft PR only after preview.

The 3D layer shows incoming sources as floating artifacts waiting for classification. Once routed, each artifact snaps to the context orbit it will affect.

### 5. Timeline radar

A temporal visualization of wiki activity:

- source ingestion events;
- page updates;
- stale deadlines;
- gate runs;
- PRs opened/merged;
- operational pass closeouts;
- score/karma events when enabled.

The timeline should support scrubbing: as the user moves through time, the graph shows what the wiki looked like at that point.

### 6. Page cockpit

Every page gets an operational card:

- title, type, context, status, visibility;
- freshness window and countdown;
- source_refs and provenance graph;
- backlinks and moc_parent path;
- open actions/decisions involving the page;
- last PR/change that touched it;
- suggested safe actions: refresh, link missing parent, create related action, add source, include in review bundle.

### 7. Command palette

The command palette is the non-technical bridge to the backend.

Examples:

- “Show stale contexts.”
- “Refresh the cockpit.”
- “Add this PDF as a source.”
- “Explain this PR in human language.”
- “Create a proposal to update this page.”
- “Run the gates.”
- “What is blocking merge?”
- “Show evidence for this claim.”

The first implementation can be deterministic search + action matching. A later agent-assisted mode can draft explanations, but the Python core should stay LLM-free.

## Backend architecture

The backend should provide a clean separation between **read model**, **action model** and **Git/proposal model**.

### Local execution contract

The first usable implementation should assume one human is running the cockpit against one local checkout:

```text
repo checkout
  -> Python snapshot/command server on 127.0.0.1
  -> Vite dev server or static frontend build
  -> browser UI
```

Local execution requirements:

- no cloud account required;
- no GitHub token required for read-only mode;
- current repo path, branch and remote freshness always visible;
- every mutating action starts with preview/dry-run when possible;
- versioned writes happen only on `wiki/<theme>` proposal branches;
- remote writes are separate actions with explicit confirmation;
- local logs and raw command output are retained for the session, not hidden by animation;
- all commands can be reproduced from the terminal.

Suggested local commands:

```sh
python3 scripts/wiki_web_snapshot.py --out data/derived/wiki/web-snapshot --clean
python3 scripts/wiki_web_server.py --host 127.0.0.1 --port 8765
cd apps/wiki-cockpit && npm install && npm run dev
```

The static snapshot command should remain useful by itself. The local server adds actions; it should not be required for read-only exploration.

### Operating modes

#### Mode A - Static snapshot, read-only

Goal: public demo, GitHub Pages/local file, local static preview, zero server.

- CLI generates JSON snapshots from the repo.
- Frontend reads JSON only.
- No Git mutation.
- Great first open-source milestone.

Proposed command:

```sh
python3 scripts/wiki_web_snapshot.py --out data/derived/wiki/web-snapshot --clean
```

Generated files:

```text
data/derived/wiki/web-snapshot/
  manifest.json
  operations.json
  graph.json
  pages.json
  sources.json
  actions.json
  decisions.json
  freshness.json
  gates.json
  git.json
  timeline.json
  diff.json
  ingestion.json
  quality.json
  commands.json
```

#### Mode B - Local operator server

Goal: safe local operation of a repo checkout.

- Runs only on localhost by default.
- Serves snapshot data.
- Runs allowlisted commands.
- Streams logs.
- Reads local Git state and upstream divergence.
- Creates/updates proposal branches.
- Stages and commits only known/previewed paths.
- Opens/updates draft PRs only when configured.

Proposed command:

```sh
python3 scripts/wiki_web_server.py --host 127.0.0.1 --port 8765
```

Implementation can use optional dependencies behind an extra such as `requirements-web.txt` or `pip install -e .[web]`. The deterministic core must remain usable without the web stack.

#### Mode C - GitHub-connected review assistant

Goal: inspect PRs, statuses and branch metadata through GitHub API.

- Optional token.
- Read PR metadata/statuses.
- Create draft PR only from a local proposal branch.
- Never auto-merge in base version.

#### Mode D - Hosted read/review deployment

Goal: make the cockpit easy to host later without changing the product contract.

- Vercel/GitHub Pages: static snapshot viewer or read-only review UI.
- GCP Cloud Run: optional read/review service or controlled operator service.
- Hosted mutating actions require an explicit repo runner/GitHub App design.
- Hosted deployments still write through proposal branches and PRs, never directly to `main`.
- Each downstream implementation owns its deployment configuration, secrets, domain and rollout process.

The open-source kit should provide examples and adapters, not a single blessed hosted state.

### Deployment ownership model

Each implementation should own its own deployment proof:

- local implementation PRs must include a reproducible local run path;
- hosted implementation PRs must describe their deployment target, build command, runtime mode and data boundary;
- downstream/private deployments must keep private snapshots, secrets and operator credentials outside the public kit;
- deploy previews can read synthetic/open data, but must not publish private wiki state by accident;
- the same frontend should support static/read-only hosting and localhost operator mode through explicit runtime configuration.

Deployment adapters should be thin:

| Target | Intended mode | Contract |
| --- | --- | --- |
| Local dev | static + local operator | Vite frontend, localhost Python server, real checkout. |
| Static file/GitHub Pages | static snapshot | Generated JSON only, no writes, public sample data. |
| Vercel | static/read-only review | Build frontend, load configured snapshot URL or bundled sample snapshot. |
| GCP Cloud Run | read/review service or controlled operator | Containerized app/server with explicit repo runner and GitHub App/token design. |

The first implementation should make these targets easy later by avoiding hardcoded filesystem paths, using environment/runtime config for snapshot URLs, keeping operator APIs separate from static UI routes and keeping all mutating operations behind the proposal/PR model.

### Proposed code layout

```text
apps/wiki-cockpit/
  package.json
  vite.config.ts
  src/
    app/
    components/
    scenes/
    data/
    graph/
    review/
    sources/
    health/
    accessibility/

wiki_core/web/
  __init__.py
  snapshot.py
  schemas.py
  presenters.py
  commands.py
  git_ops.py
  server.py

scripts/
  wiki_web_snapshot.py
  wiki_web_server.py

tests/
  test_web_snapshot.py
  test_web_commands.py
  test_web_git_ops.py
```

### Frontend stack

Base recommendation:

- Vite + TypeScript.
- React for dashboard and panels.
- Three.js through React Three Fiber for declarative scene composition.
- Drei for camera controls, helpers, text, adaptive DPR and performance helpers.
- Zustand or a tiny reducer store for UI state.
- TanStack Query or a small fetch layer for API/snapshot state.
- Playwright for high-value e2e flows.
- Vitest for pure UI/data tests.

Renderer policy:

- Start with WebGL as the stable baseline.
- Keep a renderer abstraction so WebGPU can be evaluated later without changing the product model.
- Use a 2D fallback if WebGL is unavailable.

### Snapshot schema

Every snapshot must include:

```json
{
  "schema_version": "wiki_web_snapshot.v1",
  "repo": {
    "repo_id": "wiki-viva-kit",
    "language": "en",
    "memory_root": "memories",
    "default_branch": "main",
    "branch_prefix": "wiki/"
  },
  "generated_at": "2026-07-01T00:00:00Z",
  "source_commit": "<sha-or-null>",
  "mode": "static|local_operator|github_connected"
}
```

Graph nodes:

```json
{
  "id": "system-wiki-architecture",
  "path": "memories/system/wiki/architecture.md",
  "title": "Living wiki architecture",
  "page_type": "source_catalog",
  "context": "system",
  "visibility": "private_self",
  "status": "active",
  "updated_at": "2026-06-25",
  "stale_after_days": 90,
  "freshness_state": "fresh|stale|unknown",
  "approved_state": "approved|proposal|derived",
  "risk_flags": [],
  "metrics": {
    "inbound_links": 0,
    "outbound_links": 0,
    "source_ref_count": 0
  }
}
```

Graph edges:

```json
{
  "source": "system-wiki-architecture",
  "target": "system-wiki-index",
  "type": "moc_parent|source_ref|markdown_link|pr_impact|ingestion_chain",
  "status": "valid|missing|proposal",
  "weight": 1
}
```

Action cards:

```json
{
  "id": "refresh-cockpit",
  "kind": "refresh|review|ingest|fix|approve|archive|export",
  "title": "Refresh the operations cockpit",
  "human_reason": "The committed operations page is stale or may not match HEAD.",
  "risk_level": "read|derive|proposal_write|external_write|destructive",
  "default_dry_run": true,
  "commands": [
    {
      "label": "Check cockpit freshness",
      "argv": ["python3", "scripts/wiki_operation_compile.py", "--check"],
      "writes": false
    }
  ]
}
```

Git state:

```json
{
  "default_branch": "main",
  "current_branch": "wiki/example-proposal",
  "branch_prefix": "wiki/",
  "worktree": {
    "clean": false,
    "changed_files": [
      {
        "path": "memories/system/wiki/example.md",
        "status": "modified",
        "known_generated": false,
        "suggested_stage": true
      }
    ]
  },
  "upstream": {
    "remote": "origin",
    "ahead": 1,
    "behind": 0,
    "last_fetch_at": "2026-07-01T00:00:00Z"
  },
  "proposal": {
    "is_proposal_branch": true,
    "theme": "example-proposal",
    "draft_pr_url": null,
    "human_gate_state": "not_opened|draft|ready_for_review|approved|merged|blocked"
  }
}
```

This data should be generated without a GitHub token from local Git whenever possible. GitHub metadata enriches the model, but the UI must still operate from local branch and diff state when offline.

## Backend action model

### Allowlisted command runner

All UI-triggered backend commands must pass through an allowlist.

Allowed in base local operator mode:

- `wiki_operation_compile.py --check|--write`
- `wiki_operational_pass.py --check|--write`
- `wiki_source_registry.py --check|--write`
- `wiki_input_stage.py --check|--write`
- `wiki_audit.py --check`
- `wiki_quality_report.py --check`
- `wiki_check_methodology_coverage.py --check`
- `wiki_pr_summary.py`
- `wiki_page_graph.py --check`
- `wiki_new.py --dry-run|...`
- `wiki_new_ingest.py --dry-run|...`
- `wiki_ingest.py --dry-run|...`
- `wiki_gate.py --list|...`
- `wiki_okf_export.py --out ... --clean`
- `wiki_okf_check.py --bundle ... --check`

Allowed Git operations in base local operator mode:

- `git status --short --branch`
- `git rev-parse --show-toplevel|--verify HEAD`
- `git branch --show-current`
- `git log --oneline --decorate --max-count ...`
- `git diff --stat|--name-status|-- ...`
- `git diff --cached --stat|--name-status|-- ...`
- `git fetch --prune <configured-remote>`
- `git pull --ff-only <configured-remote> <default-branch>` when on a clean default branch
- `git switch <existing-wiki-branch>`
- `git switch -c wiki/<theme>`
- `git add <known-previewed-paths>`
- `git commit -m <generated-or-user-reviewed-message>`
- `git push -u <configured-remote> wiki/<theme>` after explicit remote-write confirmation

Optional GitHub operations:

- `gh pr view|status|checks` or equivalent GitHub API read calls;
- `gh pr create --draft` or equivalent GitHub API call from a published proposal branch;
- `gh pr edit` for generated PR body/checklist updates.

Explicitly excluded from the base UI:

- direct merge to `main`;
- `git reset --hard`;
- force push;
- arbitrary rebase;
- arbitrary checkout of non-proposal branches;
- branch deletion;
- remote deletion;
- arbitrary shell command input.

Dangerous shell access is not part of the UI. No arbitrary command textbox.

### Safety levels

| Level | Meaning | UI behavior |
| --- | --- | --- |
| `read` | Reads repo state only | Run immediately, show logs. |
| `derive` | Writes ignored derived artifacts | Require explanation and undo note. |
| `proposal_write` | Writes versioned files on proposal branch | Require branch confirmation and preview. |
| `external_write` | Opens/updates PR or remote metadata | Require explicit confirmation. |
| `destructive` | Deletes/archive/rebase/force-like actions | Not in base UI unless separately designed. |

### Human language log translator

Command output should be shown in two layers:

- plain-language summary: “Audit failed because 2 pages are stale and 1 Markdown link is broken.”
- raw log: collapsible, copyable, exact stdout/stderr.

This can start with deterministic pattern matching. A later agent mode may summarize logs, but the raw log remains the proof.

### Git operations abstraction

The backend should expose Git as human workflows:

| Human action | Backend operations |
| --- | --- |
| Sync approved wiki | fetch remote -> compare `main` with upstream -> fast-forward only when clean and confirmed. |
| Inspect worktree | read branch, dirty files, upstream ahead/behind, proposal status and changed paths. |
| Start proposal | verify clean/acceptable state -> create `wiki/<theme>` branch -> snapshot. |
| Switch proposal | list existing `wiki/*` branches -> switch only to a selected proposal branch. |
| Save generated changes | show path preview -> stage known paths -> commit with generated/user-reviewed message -> rerun checks. |
| Review changes | run `git diff`, `wiki_pr_summary.py`, audit checks -> produce review bundle. |
| Publish proposal | push proposal branch after explicit remote-write confirmation. |
| Open draft PR | call GitHub API/CLI or print exact command/URL if not connected. |
| Update proposal PR | commit new files, rerun summary/checks and update draft PR body. |
| Prepare human gate | mark checklist readiness in UI and surface exact GitHub PR for final review. |
| Supersede proposal | use `wiki_gate.py` where applicable, update state and PR note. |

The UI should never hide the branch. It should translate it:

- “Approved wiki” = `main`.
- “Draft proposal” = `wiki/<theme>` branch.
- “Human gate” = GitHub PR.

### Pull Request human gate state machine

The cockpit should model PR review as a state machine:

```text
local clean main
  -> proposal branch created
  -> local changes previewed
  -> commit created
  -> gates run
  -> branch published
  -> draft PR opened/updated
  -> machine checks visible
  -> human checklist reviewed
  -> ready for GitHub review
  -> merged outside or by an explicitly designed future flow
  -> local main synced
```

The base UI can create/update draft PRs and prepare a human review bundle. It must not present merge as an ordinary base action. If a user merges in GitHub, the local cockpit should detect the merged PR, guide a fast-forward pull of `main`, and refresh the snapshot.

The gate visualization must distinguish:

- local branch exists but no PR;
- draft PR exists but gates have not passed;
- gates passed but human checklist is incomplete;
- human checklist complete but GitHub review/merge is still external;
- PR merged and local checkout not yet synced;
- PR merged and approved wiki refreshed locally.

## Key human workflows

### Workflow 1 - Start the day

1. User opens `/ops`.
2. UI loads `operations.json`, `gates.json`, `git.json` and `freshness.json`.
3. System pulse animates context vitality.
4. Do Now stack ranks the top blockers.
5. User clicks the first card.
6. Action pane explains why the item matters and shows safe actions.
7. User can refresh cockpit, open related page, or create a proposal.

Acceptance criteria:

- user can understand the next action without reading Markdown source;
- every recommendation links to the underlying page/source/gate;
- stale data is visibly marked as stale, never silently trusted.

### Workflow 2 - Add a source without CLI knowledge

1. User clicks “Add source.”
2. User drops a file or pastes a URL.
3. UI asks for plain-language context and shows matched configured contexts.
4. Backend runs pre-triage/dry-run.
5. UI shows risk result: secret block, PII info, source type, target pages, perspectives.
6. User confirms “Create proposal.”
7. Backend creates/uses a `wiki/<theme>` branch.
8. Backend runs ingestion steps or emits the LLM context request according to existing contract.
9. UI shows the pipeline theatre and the next blocked stage.
10. User gets a draft PR/review bundle when ready.

Acceptance criteria:

- a non-technical user does not need to know script names;
- secrets block before persistence;
- missing agent deep-read is shown as an honest pause, not a failure hidden in logs.

### Workflow 3 - Review a PR as the human gate

1. User opens `/review`.
2. UI loads local branch state, draft/ready PR metadata when available, `wiki_pr_summary.py`, audit status and changed pages.
3. UI shows whether the proposal is only local, published without PR, draft PR, ready PR, merged-but-not-synced or fully synced.
4. 3D review room groups changed pages by context.
5. User reads conceptual diff summary, privacy hints, gate output and exact Markdown diffs.
6. User checks the human-only checklist.
7. UI allows publishing the proposal branch, opening/updating a draft PR, regenerating the PR body and marking the bundle ready for external human review.
8. UI does not auto-merge in the base version; after an external merge, it guides a fast-forward sync of local `main`.

Acceptance criteria:

- mechanical pass and human approval are visually different;
- privacy review is explicit;
- the user can open the exact changed Markdown page and raw diff;
- a PR is treated as the approval gate, not as a decorative link.

### Workflow 4 - Fix a stale context

1. Context ring glows stale.
2. User clicks it and sees pages causing staleness.
3. UI offers “Create refresh proposal.”
4. Backend creates a branch and a checklist of pages/sources to review.
5. User or agent updates pages.
6. Backend reruns audit/freshness and cockpit compile.
7. PR summary shows the fixed vitality.

Acceptance criteria:

- staleness is traced to page-level evidence;
- UI does not auto-update `updated_at` without actual content review;
- final PR proves the context is fresh by gate, not by animation.

### Workflow 5 - Explore proof for a claim/page

1. User searches a term.
2. UI highlights matching nodes and ranked pages.
3. User opens a page cockpit.
4. Provenance layer shows `source_refs`, backlinks and navigation path.
5. User can open evidence source or create an action to verify/update it.

Acceptance criteria:

- user can answer “why do we believe this?”;
- missing or weak source_refs are visible as risk, not hidden.

## Visual and motion system

### Design language

- Dark command-room base with high-contrast text panels.
- 3D canvas as atmosphere and structure, not a full-screen toy.
- Glass panels only where text remains readable.
- Status colors are consistent and accessible: healthy, warning, blocked, proposal, approved, private/public-candidate.
- Motion is slow, intentional and tied to real state.

### Animation catalog

| Animation | Meaning | Trigger |
| --- | --- | --- |
| Root breathing | System healthy/idle | `/ops` loaded with no critical blockers. |
| Context orbit dimming | Freshness aging | context stale countdown. |
| Amber/red pulse | Action required | pending decision, stale context, failed gate. |
| Edge light pulse | Provenance path | hover source_ref or search result. |
| Proposal capsule drift | Branch not merged | open proposal branch/PR. |
| Gate shield lock | Mechanical validation pass | audit/check command success. |
| Gate shield crack | Mechanical failure | audit/check command failure. |
| Human key turn | Conceptual review checked | user explicitly marks checklist. |
| Source packet movement | Ingestion progress | source moves stage to stage. |
| Camera focus glide | User selects node/card | click/search/navigation. |

### Interaction feel

- Hover latency under 100ms for local data.
- Camera transitions under 650ms.
- No infinite spinning loaders; every async task has stage labels.
- Use optimistic UI only for “command queued,” never for “command succeeded.”
- After every write command, show what changed and how to undo/review.

## Performance practices

The cockpit should treat GPU resources as scarce.

- Render on demand when the scene is static.
- Reuse geometries and materials.
- Use instancing for repeated nodes/particles.
- Use level-of-detail for far graph elements.
- Progressive-load heavy scene layers.
- Adapt pixel ratio/effects to device performance.
- Move graph layout computation to a Web Worker or precompute stable layouts in the snapshot.
- Cap visible labels and use semantic zoom.
- Provide 2D fallback and reduced-motion mode.

Performance budgets for the base app:

| Budget | Target |
| --- | ---: |
| Initial JS before route split | under 350 KB gzip target, revisit after prototype |
| `/ops` usable from static snapshot | under 2 seconds on a mid-range laptop |
| Idle CPU/GPU | near zero when no animation is active |
| Graph interaction | stable 60fps target for sample data; graceful degradation for large repos |
| Maximum visible labels | dynamic, never all nodes at once |

## Accessibility and fallbacks

Every 3D visualization must have a parallel accessible representation:

- Do Now stack as cards/list.
- Graph as searchable table/tree.
- Pipeline as ordered status list.
- Timeline as chronological table.
- PR review as normal diff + checklist.
- Keyboard navigation for all actions.
- Reduced motion mode.
- Sufficient contrast for status colors.
- Screen-reader labels for cards and status badges.

The UI should be impressive when WebGL is available and still fully operational when it is not.

## Security and privacy

### Public open-source base

- Ship only sample/synthetic data.
- No private downstream repo names or data in fixtures.
- No generated snapshot from a private repo committed to this repo.
- No GitHub token required for read-only demo.

### Local operator mode

- Bind to `127.0.0.1` by default.
- Show repo path and branch prominently.
- Use an allowlist, not arbitrary shell commands.
- Redact secrets in logs.
- Never print tokens/cookies/credentials.
- Require confirmation before versioned writes.
- Require separate confirmation before remote writes.
- Keep all writes on proposal branches.
- Store no extra persistent app database by default.

### GitHub integration

- Token scopes must be documented.
- PR creation/update is optional.
- Merge is out of scope for base version.
- The UI should show whether GitHub data is live or from local snapshot.

## Implementation phases

### Phase 0 - Product contract and schemas

Deliverables:

- this plan;
- `wiki_web_snapshot.v1` schema draft;
- `git.json` / PR state schema draft;
- local execution contract;
- sample static snapshot fixture;
- decision: app path and dependency strategy.

Acceptance:

- no private data;
- plan links to existing Wiki Viva contracts;
- Git/PR state is modeled as a first-class data contract;
- local execution works without cloud accounts;
- implementation can start without changing existing CLI behavior.

### Phase 1 - Static read model

Deliverables:

- `wiki_core/web/snapshot.py`;
- `scripts/wiki_web_snapshot.py`;
- snapshot JSON files for sample repo state;
- Git/read model from local checkout state;
- tests for graph nodes, edges, operations, actions, freshness, gates and Git state.

Acceptance:

- snapshot generation is deterministic;
- existing audit/tests still pass;
- no server required;
- branch/default-branch/upstream status is represented when Git is available;
- localized path config is respected.

### Phase 2 - Read-only web cockpit

Deliverables:

- `apps/wiki-cockpit` Vite/React/TypeScript app;
- `/ops`, `/health`, `/pages/:page_id` routes;
- static snapshot loader;
- documented local dev path;
- 2D cards and tables before heavy 3D;
- first Three.js system pulse orb.

Acceptance:

- user can open the dashboard and understand daily operational state;
- all status cards link to underlying pages/commands;
- local static execution works before any hosted deployment exists;
- reduced-motion and 2D fallback work.

### Phase 3 - Knowledge galaxy

Deliverables:

- 3D graph scene;
- context orbit layout;
- node/edge type styling;
- search highlight;
- page action drawer;
- provenance pulse animation.

Acceptance:

- root -> context -> page hierarchy is visually obvious;
- stale/risky/proposed state is visible;
- clicking a node always exposes textual proof.

### Phase 4 - Local operator server

Deliverables:

- optional local server;
- allowlisted command runner;
- streaming logs;
- action cards for refresh, audit, graph check and PR summary;
- branch status read model.
- proposal branch create/switch workflow;
- known-path staging and commit preview.

Acceptance:

- all commands are visible before run;
- dry-run is default for risky actions;
- no arbitrary shell execution;
- generated changes are reviewable;
- versioned writes stay on `wiki/<theme>` branches.

### Phase 5 - Human gate review console

Deliverables:

- `/review` route;
- PR/branch diff summary;
- gate shield visualization;
- conceptual review checklist;
- privacy hints;
- local branch/published branch/draft PR/ready PR/merged states;
- draft PR body generator/update helper.

Acceptance:

- UI separates machine checks from human approval;
- PR summary can be regenerated;
- user can inspect exact Markdown diff.
- base UI can prepare/open/update draft PRs but does not auto-merge.

### Phase 6 - Source inbox and ingestion wizard

Deliverables:

- add source flow;
- pre-triage/dry-run results;
- input-stage target/perspective preview;
- pipeline theatre;
- proposal creation flow.

Acceptance:

- non-technical user can start ingestion safely;
- secrets block before persistence;
- missing LLM-agent pass is shown as an explicit next step.

### Phase 7 - Downstream/local adapter hardening

Deliverables:

- validate against a localized private downstream checkout without committing private output;
- path/language config fixes;
- karma disabled/enabled behavior;
- dense action/context data handling;
- local privacy review checklist.

Acceptance:

- same open-source app runs against localized repo paths;
- no hardcoded `memories/`, `system`, English-only labels or karma assumptions;
- private data stays local.

### Phase 8 - Wow polish and operational excellence

Deliverables:

- timeline radar;
- semantic diff filmstrip;
- adaptive performance;
- graph layout worker;
- polished camera choreography;
- onboarding demo mode;
- visual regression tests for core routes.

Acceptance:

- visual layer feels premium but never obscures evidence;
- app remains usable with keyboard/2D fallback;
- performance stays within budget on sample and medium repos.

### Phase 9 - Deployment adapters

Deliverables:

- documented static build path for sample/open snapshots;
- Vercel read-only deployment example;
- GCP Cloud Run container example for read/review or controlled operator mode;
- runtime config contract for snapshot URL, repo label, mode and API base URL;
- clear boundary between public sample deploys and private downstream deploys.

Acceptance:

- every hosted example can be deployed without private data;
- Vercel path does not require mutating repo access;
- GCP path documents token/GitHub App scope and still writes through PRs;
- downstream implementations can own their deploy without forking core cockpit logic.

## Definition of done for base version

The base open-source version is done when:

- a user can generate a static web snapshot from a clean clone;
- a user can open the web cockpit and see the same operational priorities as `memories/operations.md`;
- a user can inspect page freshness, graph relations, source_refs and gate status through the UI;
- a user can run read/derive checks through local operator mode without arbitrary shell access;
- a user can create, inspect, commit and publish a proposal branch through explicit Git workflows;
- a user can open/update a draft PR as the human gate handoff;
- every mutating action is branch/PR-oriented and reviewable;
- the default path runs locally before any hosted deployment is required;
- the app works with configured paths and language labels;
- no private downstream content is present in the public repo;
- reduced motion and 2D fallback are first-class;
- CI covers snapshot schema and core presenter behavior.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Beautiful UI hides truth status | Keep approved/proposal/stale/source-backed states always visible. |
| Three.js becomes costly on large repos | Use instancing, LOD, semantic zoom, snapshot filters, workers and 2D fallback. |
| Backend becomes unsafe shell wrapper | Use strict allowlist, safety levels, dry-run first and explicit confirmations. |
| Public repo leaks private patterns | Ship synthetic sample data only; downstream validation remains local. |
| UI diverges from Markdown cockpit | Generate snapshot from the same deterministic compilers and test against committed pages. |
| Users think CI green means conceptually approved | Visualize machine gates and human review as separate states. |
| Localized repos break assumptions | Read all paths/language/context labels from `wiki.config.yaml`. |
| Web app dependencies bloat the core | Put web dependencies under `apps/wiki-cockpit` and optional Python extras. |
| Git UI encourages unsafe repository operations | Allowlist Git commands, exclude destructive operations and keep `main` write-protected by design. |
| Hosted deployment accidentally exposes private state | Make deploy adapters opt-in, synthetic by default and explicit about snapshot/data boundaries. |
| Vercel/serverless path cannot run local Git safely | Treat Vercel as static/read-only unless a separate trusted runner is designed. |

## First implementation PR checklist

- [x] Add this plan to `docs/references/proposals/`.
- [x] Add no private data or downstream snapshot.
- [x] Add `wiki_web_snapshot.v1` schema draft.
- [x] Add Git/PR state schema draft.
- [x] Add minimal sample snapshot fixture.
- [x] Add tests proving path config is not hardcoded.
- [x] Document the local run path before documenting hosted deploys.
- [x] Keep mutating Git actions behind branch/PR workflows.
- [x] Keep Vercel/GCP deployment as adapter examples, not prerequisites.
- [x] Keep existing Python CLI behavior unchanged.
- [x] Document how to run the future static cockpit.

Implementation note, 2026-07-01:

- Local operator mode now includes `/api/git/workflow` for proposal branch
  creation/switching, staging, commits, publishing and draft PR creation. The
  React UI keeps these workflows dry-run by default and never exposes arbitrary
  shell input.
- `/sources` now provides a source inbox plus `/api/sources/triage`, using the
  deterministic source manifest and detector stack before any ingestion write.
- The source inbox now includes an ingestion wizard backed by
  `/api/ingestion/plan` and `/api/ingestion/run`; it shows the ordered pipeline,
  runs proposal preview and ingest dry-run through existing CLIs, and keeps
  proposal/LLM request writes behind explicit controls.
- Hosted deployment remains adapter work: Vercel is static/read-only by default;
  a future GCP/Cloud Run operator runner must keep credentials private and still
  write through branch/PR workflows.
- The frontend now reads `wiki-cockpit.config.json` at runtime (`api_base`,
  `snapshot_base`, `repo_label`, `mode`) and the deployment guide documents
  Vercel static review plus a controlled GCP Cloud Run operator adapter boundary.
- The web snapshot manifest now carries `default_context` and `karma_enabled`;
  tests cover a dense localized `memorias/` fixture with karma disabled so the
  frontend is not forced through `memories/` or `system` assumptions.
- The frontend test suite now includes a DOM route contract smoke test for
  `/ops`, `/review`, `/sources`, `/health` and `/pages/:id`, mocking the 3D scene
  to verify the 2D textual fallback and core route affordances.
- `SystemScene` now detects missing WebGL or reduced-motion preference and
  renders a stable 2D fallback with branch state and node freshness instead of
  forcing a canvas.
- The snapshot contract now emits `timeline.json` and `diff.json`; `/ops` shows
  a timeline radar from page, operations and Git events, while `/review` shows a
  semantic diff filmstrip that separates branch diff, local worktree changes,
  privacy hints and exact Git commands for the human gate.
- The scene now computes the knowledge-galaxy layout through a Web Worker with a
  synchronous fallback, adapts visible-node budget/DPR/geometry detail to local
  device conditions, renders repeated graph nodes through instancing, and uses
  an on-demand render loop with a short camera intro.
- `/demo` and `?demo=1` force the bundled public sample snapshot for onboarding
  and deterministic visual checks; `?visual=1` forces the stable 2D scene
  fallback used by screenshot baselines.
- `npm run test:visual` now runs Playwright screenshot regression checks for
  `/demo`, `/review`, `/sources`, `/health` and `/pages/:id` against local sample
  data.
- `/ops` now includes Explore Content and Content Preview backed by the local
  snapshot: search highlights matching graph nodes, selecting a result or node
  exposes the page address/content kind/area/freshness/evidence links, route
  from the root via `moc_parent`, related content and safe review actions.
- `/ops` now supports multi-page impact bundles in the local snapshot UI:
  shift-selecting search results or adding the drawer page highlights the graph
  set, groups selected pages by review context, counts stale/source-ref pressure
  and emits a human-readable review handoff for the Pull Request gate without
  writing outside the repo.
- `/review` now exposes a Prepare Approval Request panel with an explicit Pull
  Request gate state track, generated review-request title/body from local
  diff/check/privacy hints, dry-run-first send/open/update controls and a new
  allowlisted `update_draft_pr` workflow backed by `gh pr edit`.
- `/review` now also exposes an Approved Wiki Sync panel for the post-merge
  path: it shows the exact fast-forward-only `fetch`/`pull` commands and keeps
  `sync_main` disabled unless the local checkout is on the approved branch.
- `/review` has been reframed as an Approval Desk instead of a technical Git
  console: the first screen now shows the decision state, approval path,
  decision packet, evidence/risk/check summary and review-request controls
  before exposing low-level local Git operations.
- `/ops` now gives the graph an explicit job: map modes let a human choose
  whether they are deciding what changed, verifying evidence, refreshing old
  content or browsing the wiki. The selected mode highlights relevant nodes,
  selects navigable content and builds the review packet without requiring the
  user to understand graph internals.
- The global navigation and source flow now use human task language: Home,
  Approve, Add, Health and Content; `/sources` is Add Knowledge with a Review
  New Source flow and an Add Flow that appears only after a source is checked.
- `scripts/wiki_web_deploy_bundle.py` now gives each implementation a local
  deployment proof path: it writes runtime config, deterministic snapshot JSON
  and `DEPLOYMENT.md` into a chosen output directory so Vercel/static or
  GCP/operator adapters can own their target-specific deploy without moving
  secrets or private snapshots into the public kit.
- The Git read model now opportunistically reads the current branch Pull
  Request through `gh pr view` when available, filling the PR URL and
  `draft`/`ready_for_review`/`merged` human-gate state while preserving the
  existing local-only fallback when GitHub metadata is unavailable.
- The deployment guide now has copyable templates for later host-owned
  deployments: `vercel.static.json` for static/read-only review and Cloud Run
  operator Dockerfile/service YAML examples that omit credentials and keep
  identity decisions outside the public kit.
- The cockpit status language has been tightened around human decisions instead
  of raw Git concepts: top-level badges, action cards, the content map, approval
  desk, health view and page views now say approved content, draft change,
  review workspace, evidence links, content warnings and refresh needs first;
  commands, branch names and low-level refs remain available only as progressive
  audit detail where they help reproduce the decision.

## External implementation references

These references guide implementation choices; they are not new project requirements.

- Three.js docs: renderer/object/control catalog, including `WebGLRenderer`, `WebGPURenderer`, `InstancedMesh`, `LOD` and controls.
- React Three Fiber docs: declarative Three.js scenes inside React, React-version pairing, no-overhead claim and Three.js compatibility model.
- React Three Fiber performance guide: on-demand rendering, resource reuse, instancing, LOD, progressive loading, performance monitoring and adaptive pixel ratio.
- MDN `requestAnimationFrame`: animation callbacks, refresh-rate behavior and timestamp-based animation guidance.
