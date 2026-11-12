# Wiki Viva v9.2.4

## Context discovery and access

Documentary snapshots containing an instruction file and an index previously
became unassigned context owners. Approved configuration can now opt out specific
subtrees using `context_discovery.exclude`. Their files belong to the nearest
remaining context. Discovery stays unchanged when the option is absent.
Excluding the root or conflicting with an explicit `context_access` entry is
rejected. Path checks, denies, approved revisions and historical authorization
remain in force. This option does not change native agent instruction discovery.

The [context reader guide](../guides/context-reader.md#documentary-trees-and-context-discovery)
documents the option and two existing access contracts: children cannot widen
their parents' read ceilings, and foreign document bodies require exact bilateral
connections even when the reader has a broad ceiling. This release does not add
independent child grants, directory grants or glob imports.

## Other integrated changes since v9.2.3

- Context instruction handling includes `CLAUDE.md`; context hubs can declare
  perspective bundles and render integral maps through the shared generator.
- The four AQAL perspectives are required in both folder-based and explicit
  protected ingestion. Context-specific perspectives supplement that baseline.
- Canonical action/source discovery supports nested context locations. Source
  registry membership remains subject to its explicit selection policy.
- Bounded audit, sync and context operations carry their revision and selection
  requirements; operator source handling and navigation received corrections.
  Host admission and real-environment execution still need their own evidence.
- CI retains the full suites and first-attempt browser policy while splitting
  functional browser tests across isolated runners. Dependency caches and bounded
  installation retries do not retry failed tests or waive gates.

## Upgrading

Use the reviewed `v9.2.4` tag after publication. Review B0, copy managed files
through C1, run declared C2 generators and perform consumer-owned C3 migrations
explicitly. The full source SHA identifies the adopted code. Existing tags and
historical packets are not rewritten by this release.

1. Existing configurations retain automatic context discovery. To exclude a
   documentary tree, review its ownership change, add the explicit prefixes to
   approved configuration and resolve conflicting context declarations. Rebuild
   affected packets under the approved policy and an authorized content revision.
   Exclusions do not retroactively authorize historical content.
2. Review changed instruction chains, including `CLAUDE.md`, and revalidate
   affected context packages. Folder entry alone does not prove native loading.
3. Reprepare protected ingestion requests created before the AQAL requirement,
   including authorized access to all four required perspective pages. Missing
   pages or permission cause refusal before capture; do not bypass that refusal.
4. If relocating canonical sources beneath context folders, preserve the intended
   `source_registry.nested_sources` membership explicitly and regenerate/check
   the registry. Compare canonical page identities before and after migration.
5. Run consumer gates and verify the intended authorized workflow after adoption.
   Updating a lock or generating a map does not establish live operation.
