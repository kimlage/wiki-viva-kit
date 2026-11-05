# Independent Git evidence in protected source stages

A trusted in-process host may add immutable `RepositoryGrant` entries to its
existing `CoordinationBinding`. Each entry pins one physical local repository
root, configured identity, immutable commit, literal Git path, executor,
integrator and byte limit. It has a host-selected opaque ID. Both actors must
also have the `independent_git.read` capability in their current qualified
folder policy. An untrusted stage payload may select one ID or a list of up to
eight IDs; it cannot define or widen a grant. All selected grants are checked
before any selected Git repository is opened. The selection must be supplied again
for prepare, record and consolidate. A missing or changed grant cannot open an
existing request. CLI flags and the configured Git origin do not grant access.

The route uses local Git only, disables lazy fetching, reads an exact literal
path from the pinned commit and never adds unselected paths to the request. It
rechecks policy/ref, both actors and physical root identity before each Git
metadata, tree or blob command. The selected bytes and provenance participate
in the context fingerprint and both context and request budgets. Artifacts
bind an opaque digest of the host grant, not the local repository root. Request
and event also record the sanitized configured repository identity, revision,
path and hashes as provenance. The identity and receipt are not authorization
or evidence of remote identity.

Reading is not authorization to disclose a derivative. Once prepare returns
the source and request IDs, the trusted host may create a new immutable binding
with exactly the same read-grant attributes and an explicit `event_target` for
the canonical event of that request. The integrator is already fixed in the
grant. Both actors must also have `independent_git.derived_proposal` in their
qualified publication policy. Consolidate checks this exact target before
opening the retained request or result, then checks again around effects. A
different read grant cannot open the original request, even when reusing the
same selection ID. Without this separate output authorization, consolidation
is denied. Selecting an event in the payload or having a write scope is not
publication permission. The host's output grant explicitly permits disclosure
of the resulting proposal to readers under the wiki's existing access rules;
it does not itself prove remote permission or complete review/incorporation.

The trusted host may install grants in process or set
`WIKI_COORDINATION_REPOSITORY_GRANTS` at startup to a JSON list with the exact
`selection_id`, `root`, `identity`, `revision`, `path`, `executor`, `integrator`,
and optional `max_bytes` and `event_target`. The existing environment settings
still fix the allowed contexts, trusted ref and folder mode. The local CLI
reads the host binding at startup; flags and stage JSON cannot add grants.
`wiki_coordination.py --show-host-binding` reports the selected IDs, actors and
whether publication is configured, without printing roots or identities. The
operator must protect the startup environment. The CLI is an interface for a
trusted local operator, not a boundary against that operator. The binding controls
this application route only; it is not an operating-system ACL, process
sandbox, remote authentication or evidence of external business permission.
Startup validates grant syntax without opening every repository. Physical root
and storage are checked and pinned only when a grant is selected; an absent
unselected repository does not block another selection. Every selected grant
and storage boundary is checked before opening any selected Git body.
The host remains responsible for separately qualifying local filesystem access
and the Git installation. A configured origin only checks local routing; it is
not proof of the remote repository's identity. Other links and files are not
inspected by this selection.

The source stage still requires a separately authorized repository-local
`source_ref`. Selected independent Git files are interpretation evidence;
the adapter does not capture a Git blob as the primary source.

This adapter requires an ordinary `.git` directory inside the selected root.
It rejects gitfiles/worktrees, `commondir`, object alternates, symlinked or
hard-linked Git object storage, and object stores with more than 100,000
metadata entries. It checks the root and storage identities again before each
Git command. Filesystem checks cannot prevent concurrent hostile replacement;
the trusted host must protect the repository and storage while operating.
Protected cache guards also recheck selected repository storage around reads.
Each check walks bounded object-store metadata, so many chunks or a large store
can make preparation and inspection expensive. Metadata at the object-store
root does not prove that nested entries remain unchanged.
Local Git configuration is read with a 100 KB cap and a conservative lexical
check; includes, worktree redirects, backslash escapes and external alternate
ref commands are refused, including incidental matching text. Such repositories
need a separately qualified adapter.

The read-only `compare` source stage requires the same original request and
selection, plus a separately host-pinned current selection for the same
repository identity and path. The explicitly selected source page must declare
that repository; each candidate must be authorized independently and is read
from the approved wiki commit rather than an unapproved working-tree edit. It compares
only that file and returns an on-demand review suggestion for declared current
requirements. It does not write pages, prove file consumption or assert that a
proposal was reviewed. Missing grants, stale policy or unavailable results
stop the comparison.
