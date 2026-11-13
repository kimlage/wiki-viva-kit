# Wiki Viva v9.2.0

This release adds folder-based context entry and protected source ingestion.
It also tightens repository boundaries and reports unavailable quality
measurements explicitly. These changes do not establish that any particular
consumer has adopted the release or executed a task.

## Changes and limits

- A trusted folder binding selects the applicable context, instructions and
  index for a task. Ownership and explicit read/write policy remain separate
  from folder names: a path, profile or link does not grant access. See the
  [protected coordination guide](../guides/context-coordination-protected.md).
- Protected ingestion binds the selected source, context and approved authority
  to a finite workflow. The [bounded ingestion guide](../guides/bounded-ingestion.md)
  describes selection, coverage, review and the supported capture formats.
  A request or packet does not establish semantic reading or source freshness.
- New approved-context operations use folder authority. Legacy v1 packet and
  ingestion entry points are retired for new work; historical verification and
  the separately authorized working-tree compatibility route remain distinct.
  A superseded historical v1 query can be retired under approved-base rules,
  while affected current consumers and queries remain subject to review.
- Nested Git repositories are boundaries for local traversal and sync.
  Separately selected Git evidence requires an explicit host binding; an
  unrelated nested repository is not silently traversed or copied.
- Quality telemetry reports blocked or unavailable measurements rather than
  presenting them as empty successful results. The public Python CI gate
  distributes the collected suite across processes and propagates failures.

Context policy and packets do not replace filesystem or service authorization.
This release does not grant connections, run a model, refresh source dates,
start jobs or activate schedules. Folder context schedule advice remains
blocked pending its trusted host binding and requalification; see the
[context operation runbook](../guides/context-operation.md).

## Upgrading

Use the reviewed `v9.2.0` tag after publication and verify its target against
the published release. Preserve earlier releases for reproducibility. Use an
isolated consumer checkout, review the B0 dry-run, apply tracked kit-owned
files verbatim in C1, run declared generators in C2, and supply explicit
consumer-owned migrations in C3. Review the consumer proposal and run its
applicable gates. See the [downstream upgrade runbook](../guides/wiki-viva-v8-downstream-upgrade.md)
and [v9 migration and rollback notes](wiki-viva-v9.0.0.md#upgrading).

Consumers must explicitly migrate context selection and policy to the folder
route; an upgrade does not infer grants, ownership or historical receipt
mappings. Retain applicable historical records and qualify consumers of old
queries before retiring them. Rebuild and verify the code, content, frontend,
configuration and policy through the installation's supported route.

Before changing a served installation, preserve its content, configuration,
bundle and lock. Qualify a compatible return against the actual final content,
including changes made after upgrading, and verify the restored installation.
The consumer PR is a reversible change boundary, but reverting files alone does
not prove a working served installation or recovery of external effects.
