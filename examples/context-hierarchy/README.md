# Synthetic context hierarchy

The [root manifest](context.yaml) and its descendant `context.yaml` files form one hierarchy. They model finance, independently interpreted tax and costs, a personal company perspective, and a separate company domain. The example root is `examples/context-hierarchy`, not the repository root. A different hierarchy may put its root manifest at repository `context.yaml` and declare root `.`; it is an independent hierarchy, not a second source for this one.

Each manifest declares `schema_version`, unique `id`, one `parent` (null only for the root), the physical directory `root`, `purpose`, `owner`, and lists of `instructions`, `skills` and `templates`. `policy` holds `read`, `write`, `capabilities`, `publication` and typed `deny` entries. The root declares every policy boundary; a missing child entry inherits, an empty allow list grants nothing, and typed denies accumulate and take precedence. Paths are literal repository-relative prefixes with no globs. `self` expands at the declaring context, `self/name` below it, and `.` means the repository root. A child can narrow but cannot widen its parent. Optional `workflow` and `defaults` are metadata, not permission.

The approved `instructions`, `skills` and `templates` of each context in the lineage are **mandatory normative inputs**: their declaration is a separate grant to compose the policy. They come from the approved policy revision and must belong to their declaring context. `policy.read` controls evidence and data, so a child with `read: []` still receives those mandatory ancestor rules but receives no evidence. An applicable `deny.read` also blocks a mandatory input and therefore blocks the packet. A child cannot declare a sibling's file as its rule. A proposed change to an ancestor rule is not used until the approval reference advances.

`imports` and `exports` are explicit matching rules with `from_context`, `to_context`, exact `selector` path, optional `section` or `field`, `use`, `classification` and ISO `expires`. Both contexts' effective read policies must permit the path. The most deeply nested context root owns a path; declaring a different producer cannot bypass a connection. Both sides must have identical, unexpired rules. A link or pending proposal grants nothing; there are no implicit sibling grants.

The CLI uses the current tip of `refs/remotes/origin/main` as its trusted approval reference. An independent approval process must maintain and refresh that reference; a proposal cannot configure it. A library integrator may set a different trusted reference only through trusted external configuration, never from the proposed content. Git cannot itself prove a review occurred. The policy and mandatory bytes come from that approved revision, while explicitly selected evidence may come from a historical content revision. The reference is rechecked during packet composition.

After these examples have been approved on the trusted reference, create a request file with, for example:

```json
{"task_id":"demo-1","goal":"Review the synthetic context","output":"A short report","integrator":"example operator","evidence":[],"max_bytes":4096,"omissions":[]}
```

Then run from the repository root, replacing `/tmp/request.json` with the actual request file:

```sh
python3 scripts/wiki_context.py --approved-revision origin/main --manifest examples/context-hierarchy/context.yaml resolve finance/tax
python3 scripts/wiki_context.py --approved-revision origin/main --manifest examples/context-hierarchy/context.yaml pack finance/tax --content-revision origin/main --request /tmp/request.json
```

Packets include declared reads, selected bytes and digests, missing coverage and a canonical packet digest. `max_bytes` bounds the UTF-8 bytes of the complete canonical JSON packet, including metadata and digest; `bytes_used` is its exact size, and `selected_text_bytes` separately counts selected UTF-8 text. Overflow fails without truncation. This is a byte limit, not a model-token estimate. The existing secret detector checks selected text and returned metadata; detected access secrets block the packet without revealing their values. Personal data is not blocked merely for being personal. Dynamic queries are not yet supported; explicit read sets do not claim complete coverage. The task-result schema binds task and context IDs and packet digest; `validate_result` checks the binding and reported reads against the packet, but cannot independently prove an agent's claimed reading or changes.

Capability reports are supplied and authenticated by the caller, not proven by this policy. A report requires `verification: verified`, lists of exact `capabilities` and exact resource `scope` values, and a nonempty `limitation`. An effect request names both capability and exact target; a generic scope is not proof for a different resource. Neither YAML nor the report asserts operating-system sandbox enforcement.
