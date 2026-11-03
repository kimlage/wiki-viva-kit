# Wiki Viva v9.1.0

This minor release distributes the reader/catalog secret-output correction,
bounded context queries, canonical task preparation and opt-in installed-code
composition added since v9.0.0, together with explicit installed-gate
availability. The preserved v9.0.0 source archives do not contain the later
reader output protection.

## Corrections and scope

- The low-level reader checks selected body, section, field, identity and
  catalog output before serialization, including raw strings and key/value
  associations. Refusals do not echo detected values; safe private selections
  remain usable. Synthetic fixtures demonstrated the missing output check in
  v9.0.0; this work did not establish actual credential exposure.
- Dynamic query impact follows declared current consumption with bounded,
  deduplicated propagation and authorization of every reached typed cause.
  Successful identical selections can be reused within one preflight while
  preserving logical byte budgets and current authority and branch checks.
  Navigation links do not establish consumption or grant access.
- Inherited mandatory instructions are tracked as normative dependencies and
  revalidated during impact and integration checks. These dependencies remain
  distinct from factual evidence; inherited restrictions cannot be widened by
  a descendant.
- Task preparation uses canonical context packets while retaining profile
  routes for navigation. Explicitly declared modular factual units are
  supported. Nested editorial hubs use qualified typed metadata across
  input-stage, audit and operation consumers; a folder location alone does not
  create an owner, domain or authorization.
- In installed-code mode, a gate that cannot execute is reported as unavailable.
  Installed receipts lack current input identity and remain historical; they do
  not establish a current pass or refresh its validation time. Individual and batch UI
  controls respect availability. This does not enable execution of consumer
  test code.
- Installed-code mode separates pinned code, consumer content and the frontend
  bundle. It remains opt-in. Agent jobs, consumer adapters, observers,
  contribution scratch gates and external builds remain unavailable in that
  mode. See the [local operator contract](../guides/local-operator.md).

Context policy and protected packets do not replace host/filesystem controls
or service authorization. A packet digest proves bytes, not semantic reading,
factual freshness, complete coverage, an operating service or autonomy.
Optional finite schedule advice does not install or activate a scheduler.

## Upgrading

Use the reviewed `v9.1.0` tag after publication and verify its full target
commit against the published release source. Preserve `v9.0.0` at
`d29754569507259be3744690d5ee86df3520ddd5` for reproducibility; do not use
its unchanged source archives for a new adoption.

Follow the [v9 migration procedure](wiki-viva-v9.0.0.md#upgrading):
an isolated consumer checkout; review the B0 plan; apply C1 byte-for-byte and
declared C2 generators; supply explicit consumer-owned C3 migrations when
needed; run applicable kit and consumer gates; and independently review the
final consumer proposal. A version label alone does not prove that these
steps were performed.

Consumers adopting the gate-availability fix must qualify the updated code
and rebuild the frontend together. Verify the code, content, bundle,
configuration and policy actually loaded through the consumer's supported
installation route. An older bundle does not demonstrate the corrected UI.
This release does not grant connections, change ownership, refresh factual
dates or activate jobs and paused schedules.

Before changing a served installation, preserve content, configuration,
frontend, receipts and the current lock; reconcile known runs and uncertain
effects. Qualify a compatible return version for the actual final content,
including knowledge created after upgrading. Restoring files or a launcher
dry-run does not demonstrate HTTP operation, restoration of a served bundle
or recovery of external effects. Keep runtime dependencies immutable during
execution.
