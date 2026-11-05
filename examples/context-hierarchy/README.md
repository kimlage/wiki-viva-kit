# Historical synthetic v1 context hierarchy

The [root model](context.example.yaml) and descendant `context.example.yaml`
files preserve the former v1 manifest contract as synthetic history. They are
inert examples, not the current folder hierarchy or permission configuration.
New task packets cannot be created through the v1 CLI or host binding; use the
[folder reader guide](../../docs/references/guides/context-reader.md) and
[protected coordination](../../docs/references/guides/context-coordination-protected.md).
Historical v1 receipts retain their original IDs and require the original
manifest to be established for historical verification; no folder equivalence
is inferred. Do not activate these examples as a second production hierarchy.

The following paragraphs describe v1 behavior for historical interpretation,
not rules for new folder packets.

Each manifest declares `schema_version`, unique `id`, one `parent` (null only for the root), the physical directory `root`, `purpose`, `owner`, and lists of `instructions`, `skills` and `templates`. `policy` holds `read`, `write`, `capabilities`, `publication` and typed `deny` entries. The root declares every policy boundary; a missing child entry inherits, an empty allow list grants nothing, and typed denies accumulate and take precedence. Paths are literal repository-relative prefixes with no globs. `self` expands at the declaring context, `self/name` below it, and `.` means the repository root. A child can narrow but cannot widen its parent. Optional `workflow` and `defaults` are metadata, not permission.

The approved `instructions`, `skills` and `templates` of each context in the lineage are **mandatory normative inputs**: their declaration is a separate grant to compose the policy. They come from the approved policy revision and must belong to their declaring context. `policy.read` controls evidence and data, so a child with `read: []` still receives those mandatory ancestor rules but receives no evidence. An applicable `deny.read` also blocks a mandatory input and therefore blocks the packet. A child cannot declare a sibling's file as its rule. A proposed change to an ancestor rule is not used until the approval reference advances.

`imports` and `exports` are explicit matching rules with `from_context`, `to_context`, exact `selector` path, optional `section` or `field`, `use`, `classification` and ISO `expires`. Both contexts' effective read policies must permit the path. The most deeply nested context root owns a path; declaring a different producer cannot bypass a connection. Both sides must have identical, unexpired rules. A link or pending proposal grants nothing; there are no implicit sibling grants.

The former v1 policy loader bound authority to a trusted Git reference maintained
by an independent approval process; Git alone does not prove review. Historical
verification must select the relevant prior manifest and revision without
turning them into current permission.

The historical v1 packets included the selected context, declared reads, bytes,
digests and incomplete coverage. A byte budget and result-to-packet validation
did not prove that an agent had read the material or that access was enforced by
the operating system. The current folder and dynamic-query paths have their own
[selection contract](../../docs/references/guides/context-dynamic-selection.md).

Capability reports are supplied and authenticated by the caller, not proven by this policy. A report requires `verification: verified`, lists of exact `capabilities` and exact resource `scope` values, and a nonempty `limitation`. An effect request names both capability and exact target; a generic scope is not proof for a different resource. Neither YAML nor the report asserts operating-system sandbox enforcement.
