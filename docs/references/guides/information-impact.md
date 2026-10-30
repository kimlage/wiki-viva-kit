# Information impact and factual use

Information relevance, verification age and execution permission answer different
questions. A dated observation retains its date; editing a queue does not verify
the facts of every item that it displays.

## Shared relations

The [relation inventory](../../../wiki_core/information_relations.py) preserves
individual occurrences and multiple meanings between the same pages. It is the
input to [impact evaluation](../../../wiki_core/information_impact.py) and
[explicit operational consumption](../../../wiki_core/information_use.py).

- Navigation and contextual references support discovery.
- Factual support carries an information dependency. Ambiguous prose remains
  conservative.
- An operational prerequisite declares information required for the intended
  use, separately from workflow prerequisites such as action state.
- A generated projection declares the fields it consumes and produces. The
  [operation compiler](../../../scripts/wiki_operation_compile.py) emits these
  declarations; projecting a state does not consume all the action's sources.
- A review record documents a judgment, not a new observation of every linked
  source. Historical support preserves its temporal scope and evidence.

The [operational pass](../../../wiki_core/operational_pass.py) and
[input stage](../../../wiki_core/input_stage.py) also declare their actual
metadata inputs. Title and legacy-state fallbacks retain body consumption where
they really parse it. Resume links remain navigation; diagnostic links record a
review. The compiler checks still detect additions, deletions and membership
changes, including pages not previously rendered as individual rows. Existing
publications can retain their date and visible text while reviewed occurrence
declarations are migrated. This does not verify source contents.

[Markdown occurrence roles](../../../wiki_core/markdown_link_roles.py) bind a
literal link to a declaration. That digest is neither proof of semantics nor
permission. Role changes require normal content review; the impact evaluator
retains base and candidate relations, including removed or retargeted links.

Propagation reaches a fixed point over affected fields, retaining multiple
causes. It does not expand from a consumer into every unrelated source cited by
that consumer. Editing a consumer does not automatically discharge an incoming
review obligation.

## Comparison and activation

The existing audit configuration accepts `information_impact: legacy`, `shadow`
or `use_scoped`, with `legacy` as the compatibility default. `shadow` adds a
comparison to the existing report without changing its acceptance decision.
Activation uses `freshness_scope: impact`, an explicit review base, and
`information_impact: use_scoped`.

In the activated mode, the freshness and impact audit entry points share one
authority. Existing age diagnostics and pending review obligations remain
visible. Missing evidence and relation integrity still fail. Per-proposal
freshness waivers are not accepted by this mode. Source dates and schedules are
not renewed to satisfy integration.

## Producer input declarations

Generated pages carry `projection_inputs` in their existing frontmatter. A
selector names fields and either explicit repository `paths` or `page_types`,
optionally restricted by context, namespace, depth, filename and the producer's
selection predicates. Candidates remain inputs before they become displayed
rows. A title using an H1 fallback consumes body; a completed item whose body is
not read does not. The selector examines only loaded wiki metadata and grants
no read, fetch or execution authority. Both base and current selections apply,
so deletion, type changes and movement out of a selected scope remain visible.

These declarations complement occurrence-specific projection links. They are
not source verification or a per-proposal exception. Configuration and queue
files actually read by a producer are explicit inputs. Strict typed comparison
preserves changes such as `false` to `0` and removal of a qualifying field.
Regenerate the four built-in projections during C3, preserving source dates;
review authored index, log and triage occurrences individually rather than
reclassifying an entire page type as navigation.

## Explicit current or historical consumption

A consumer may declare a scoped requirement using existing page fields:

```yaml
information_requirements:
  - target: claim-observed-balance
    fields: [body]
    temporal: current
    max_age_days: 1
```

Targets must resolve uniquely. Unknown keys, duplicate selectors and ambiguous
references fail closed. A body declaration of an operational prerequisite cannot
silently disappear from admission; an operational declaration without sufficient
scope is unusable for current execution.

Current factual use requires a specific claim, confirmed confidence, applicable
verification and evidence. The existing [temporal contract](temporal-kernel.md)
provides `verified_at`, `valid_from` and `valid_to`; the editorial `updated_at`
and a discovery cursor are not substitutes. A verification with day precision
stays a day, not an invented observation instant. Missing, future, expired,
inferred or conflicting evidence cannot qualify current use.

Revision coverage includes the selected content and the metadata qualifying its
verification. Git ancestry detects later edits; it does not establish truth or
prove an external read. Authorized context includes the relevant claim and its
evidence in the existing revision-bound readset. Current requirements are
rechecked at admission, and their derived validity bound limits the existing
OpenClaw mission expiry checked by the inference guard.

This guarantee covers declared requirements and the qualified execution path.
A packet hash does not certify arbitrary facts in a prompt, unknown external
changes, permissions, or the agent's complete understanding. A refresh or
historical reading may inspect old observations without presenting them as
current facts. No new tool, account, source access or scheduler is granted.

## Existing source queue

Review requests belong to the existing per-source/per-stream cursor state and
[source read model](../../../wiki_core/web/sources.py), not another task store.
They group consumers by source, stream, scope and fields. Reprojection preserves
attempt history and satisfied conditions, and releases consumers no longer in
use. A discovery cursor cannot clear factual review obligations.

Attempts need an explicit budget and a changed blocking condition before retry.
Discovery, script completion and inventory review do not constitute factual
verification or incorporation. Where no source/stream can be resolved, retain
an explicit unresolved information requirement rather than inventing a source.

The native `sources.review_pending` command projects the complete obligations
into that queue and submits bounded deterministic work to the existing
[job runner](../../../wiki_core/web/codex_jobs.py). It requires an explicit base,
`max_sources`, `max_attempts` and `max_adapter_calls`. Only sources qualified by
`audit.source_review_allowed_sources` may be selected; the default grants none.
That qualification selects a declared adapter, not an account or credential.
The budget counts adapter invocations, including the native preview recheck.
It does not claim to count a provider's internal pagination or network requests;
those limits belong to the reviewed adapter. No model is selected or invoked.

The plan describes collection-wide inventory reads. Applying discovered records
is restricted to the planned, existing streams; unrelated new records remain
unselected. Work stays on a proposal branch. Scripts without a declared RAW
scope and sources requiring a semantic reader or manual export remain explicit
impediments. Deferred obligations remain visible instead of being inactivated.

Native authority remains in RAM and is checked before each effect. Cancellation
prevents the next effect, while a read already in progress must finish before
its result is known. Restart does not restore authority or resend the job.
Recovery binds an exact attempt, preview and configuration to a successful
native receipt; missing or failed receipts cannot become successful collection.
An unreconciled attempt bars another background operation on the same source,
even after inputs or budgets change. A collected obligation needs factual
review before another collection of that same obligation. Changing catalogue
metadata or an attempt budget cannot satisfy it.

Cursor and review updates share an atomic source-state transaction, preserving
each other's fields. Unexpected edits are preserved and refused, including
concurrent edits to a config file the native operation also writes. A job's
output is not proof that arbitrary dirty files belong to it. No commit, push,
merge, verification timestamp or current-fact acceptance is implied by delivery.

The reader presents the recorded verification and intended temporal use.
Reading alone performs no global refresh and grants no execution permission.
