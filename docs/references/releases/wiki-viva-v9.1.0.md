# Wiki Viva v9.1.0

This release distributes the reader/catalog secret-output correction together
with the bounded queries and opt-in installed-code composition already integrated
in approved commit
[`7769aee73a166ac7fd7b4ab7f35be64576e451ca`](https://github.com/kimlage/wiki-viva-kit/commit/7769aee73a166ac7fd7b4ab7f35be64576e451ca).
The minor version reflects the additional query and composition interfaces since
v9.0.0. Publication of the tag/release is separate from merging these notes.

## Corrections and scope

- The low-level reader now checks selected body, section, field, identity and
  catalog output before serialization. Raw strings and key/value associations
  are checked as well as structured output; refusals do not echo detected
  values. Safe private selections remain usable. Synthetic fixtures demonstrate
  the correction; no actual credential exposure was established by this work.
- Dynamic query impact follows declared current consumption with bounded,
  deduplicated propagation and authorization of every reached typed cause.
  Legacy global review candidates remain visible. A navigation link alone does
  not establish current query consumption or grant access to another owner.
- Query reproduction can reuse successful identical selections within one
  preflight, preserving logical byte budgets and current authority/branch checks.
- Installed-code mode separates pinned code from content and frontend files.
  It remains opt-in; agent jobs, consumer adapters, observers, contribution
  scratch gates and external builds are unavailable in that mode. See the
  [local operator contract](../guides/local-operator.md).

The v9.0.0 tag remains at `d29754569507259be3744690d5ee86df3520ddd5`.
Its source archives are unchanged and must not be presented as corrected code.
A version label, detector result or packet digest does not prove semantic
reading, complete coverage, factual freshness, an operating service or autonomy.

## Upgrading

Use the reviewed v9.1.0 tag only after publication and verify its target commit.
Before publication, the approved corrected source is the full commit
`7769aee73a166ac7fd7b4ab7f35be64576e451ca`; do not substitute the v9.0.0 tag.
Consumers already pinned to that corrected commit do not need to change runtime
code merely to acquire a new version label.

Follow the [v9 migration procedure](wiki-viva-v9.0.0.md#upgrading) with that
corrected source: isolated consumer checkout, B0 review, C1 verbatim, declared C2,
explicit consumer-owned C3, applicable gates and independent PR review. Do not
refresh factual dates or grant connections as a side effect. The release-note
files are portable so downstream adoption carries the corrected guidance.

Before changing a served installation, preserve knowledge, configuration,
frontend, receipts and the current lock; reconcile known runs and effects.
Qualify a compatible return version for the actual content. A code/readback
test or launcher dry-run does not demonstrate HTTP operation, service rollback
or recovery of external effects. Keep runtime dependencies immutable during
execution and do not activate jobs or schedules as part of this upgrade.
