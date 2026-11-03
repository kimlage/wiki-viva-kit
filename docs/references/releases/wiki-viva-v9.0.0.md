# Wiki Viva v9.0.0

> **Adoption notice:** the immutable `v9.0.0` tag points to
> `d29754569507259be3744690d5ee86df3520ddd5` and predates the reader/catalog
> secret-output guard. Do not use that tag or its source archives for new
> adoption. Use approved corrected commit
> [`7769aee73a166ac7fd7b4ab7f35be64576e451ca`](https://github.com/kimlage/wiki-viva-kit/commit/7769aee73a166ac7fd7b4ab7f35be64576e451ca),
> or the reviewed v9.1.0 tag after publication. Synthetic regression fixtures
> demonstrated the missing output check; this work did not establish an
> actual credential exposure. The old tag is preserved for reproducibility.

This major release changes distributed files, configuration and API surfaces. It
keeps Markdown and Git as the canonical knowledge base while making context
policy, revision-bound reading and independent integration explicit. A version
number or this note is not evidence of approval, installation or a running
service; release promotion still follows the repository's independent review
and CI policy.

## What changes

- Context manifests declare purpose, ownership, ancestry, mandatory instructions,
  scoped policy and explicit imports/exports. Missing policy entries inherit;
  descendants cannot widen ancestors, and denials accumulate. A path scope is
  a ceiling, not a cross-context grant. A parent reading a child needs the same
  precise bilateral authorization as any other cross-context consumer.
- Revision-bound readers select approved Git content, frontmatter fields or
  stable section IDs. A task packet includes the selected context's purpose and
  boundaries, complete mandatory inputs, explicit evidence, revision/digests,
  coverage, task identity and a complete canonical-JSON byte budget. Current
  policy is checked separately from historical content; incomplete selections
  and budget overflow do not silently widen or truncate the packet.
- Approved ingestion admits an explicitly authorized staged local source before
  reading it, then bounds the complete context package and complete request
  independently. Required bodies and extracted chunks are not silently
  truncated. External sources need a separately qualified staging or adapter
  path. The working-tree compatibility mode is not approved policy.
- The local coordinator has an explicit protected packet path. It is disabled by
  default and requires an authenticated local session and a host-configured
  context binding. Existing profile/snapshot coordination remains available as
  `caller_trust` compatibility; it is not an owner-scoped ACL and is not an
  automatic fallback from protected mode.
- Existing `information_requirements` can retain selected fields/sections and
  the revision actually consumed. The impact tools compare authorized slices,
  limit and deduplicate immediate review candidates, and leave the destination
  to interpret independently. The preflight checks an exact branch, approved
  base, packet, reported result and write scope; it does not approve, execute
  proposed code, publish or merge.
- Modular section templates and finite context schedule advice are opt-in. The
  latter produces bounded, deterministic advice only; it does not install a
  scheduler, dispatch an agent, send a message or authorize an effect. Existing
  content and templates are not automatically rewritten.
- The distributed kit no longer requires the retired installation-specific
  execution integration. Generic source, action, proposal, operator-observation
  and cockpit capabilities remain available within their own contracts. A
  consumer that depended on removed APIs, configuration, files or loaders must
  explicitly migrate or replace that integration.

The local policy is not an operating-system sandbox. Host/filesystem controls,
service authorization and independently authenticated adapter evidence remain
necessary for effects. A packet digest proves bytes, not semantic reading or
current external facts. The synthetic pilot exercised two context threads in one
harness; it does not qualify two different harness products, a production
scheduler or an installed consumer.

## Upgrading

Use **approved corrected commit `7769aee73a166ac7fd7b4ab7f35be64576e451ca`**,
or the reviewed v9.1.0 tag after publication, as the source. The v9.0.0 tag and
its source archives remain historical and are not corrected by this notice. Perform
this work in an isolated consumer checkout that no service uses. Do not assume
that the version checked out there is the version currently served.

1. Inventory consumer-owned configuration, imports, scripts, frontends,
   integrations and callers of removed interfaces. Preserve the existing
   `kit.lock`, content, bindings, required receipts, code/configuration and the
   previous frontend artifact. Identify and qualify a return version and the
   compatibility or reverse migration for any content created after upgrade.
2. Run B0, the read-only plan, and review every addition, change and removal:

   ```sh
   python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
     --kit /path/to/wiki-viva-kit --consumer /path/to/consumer --dry-run
   ```

3. Prepare explicit consumer-owned C3 migrations for configuration, paths,
   context hierarchy, callers and any replacement integration that the B0
   review identifies. A folder move preserves neither authorization nor an
   external service binding. Configure only the contexts, imports and effects
   that have been specifically approved; do not turn a proposed connection
   into a grant. Preserve IDs, provenance and factual dates when moving pages.
4. Apply C1/C2 and the required explicit C3 commands **only in the isolated
   checkout**. C1 may remove previously kit-managed files before C3 runs; C2
   runs the kit's declared deterministic generators, if any. C3 belongs to the
   consumer and is never guessed by the kit:

   ```sh
   python3 /path/to/wiki-viva-kit/scripts/wiki_sync_from_kit.py \
     --kit /path/to/wiki-viva-kit --consumer /path/to/consumer \
     --c3-command "python3 scripts/consumer_migration.py"
   ```

   The C3 command above is a placeholder: provide the consumer's reviewed
   command or omit the option if no migration is needed. Review the diff and
   `kit.lock`, repeat B0, and run applicable kit and consumer gates. Obtain an
   independent review of the final proposal HEAD under the consumer's policy.
5. Before modifying a **served** root, prevent new admissions, reconcile runs,
   effects and proposals, and establish sufficient custody and quiescence. If a
   live process uses a loader or file that C1 will remove, retire or repoint that
   process and verify the old reference is no longer active **before** changing
   the served checkout. A prepared migration or empty resident counter is not
   proof of global quiescence. Preserve an approved recovery path and do not
   repeat uncertain external effects.
6. Adopt only the independently reviewed consumer result through its qualified
   installation procedure. Verify the actual code, content, frontend, policy,
   bindings and useful read/proposal flow after installation. Rebuild the
   frontend when its source changes; restart loaded server code when required;
   verify scheduler installation separately. Keep previously paused schedules
   paused until their own authorized, observed adoption.

For a local protected operator, see the [host binding and API guide](../guides/context-coordination-protected.md).
The [finite context operation runbook](../guides/context-operation.md) describes
selection, packet, worktree, result, preflight, independent review, integration,
readback and optional wake. The [bounded ingestion guide](../guides/bounded-ingestion.md)
explains source admission, separate context/request byte limits and recording. The [schedule advice contract](../context-schedules.md)
does not install or start an automation.

## Rollback

The reviewed consumer PR is the versioned-code rollback boundary, but reverting
it alone does not restore a running process, its frontend bundle, bindings,
schedules, retained receipts or external effects. Before installation, test the
specific old/new version pair and a path that preserves knowledge added after
migration. On failure, stop dependent admissions, reconcile uncertain effects,
restore the qualified code/configuration/bundle/binding through the controlled
procedure, and verify readback. Do not reset away new knowledge, replay effects
or reactivate paused schedules as a side effect of rollback.
