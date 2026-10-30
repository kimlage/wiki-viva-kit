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

The reader presents the recorded verification and intended temporal use.
Reading alone performs no global refresh and grants no execution permission.
