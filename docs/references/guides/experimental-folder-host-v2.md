# Experimental folder host binding

`wiki_core.folder_coordination_v2` is an opt-in Python interface for a host
that already has authority to access repository metadata and mechanical control
bodies. It accepts a binding constructed and retained by trusted host code,
containing an absolute repository root and an explicit tuple of context folders.
Request data must not construct or widen that binding. Without a binding, or
when the requested folder is not exactly listed, it refuses the request before
loading repository policy. A listed folder is not a grant to its descendants.

`prepare_folder_packet` binds a folder to the current `origin/main` policy
revision, requires fixed Git object IDs, checks content ancestry and authorizes
the selected output, index and all evidence selectors under current and, when
needed, historical mechanical controls. Only then does it call the v2 packet
builder. `prepare_folder_preflight` accepts a matching v2 result and packet,
rechecks those selections, and invokes the limited v2 preflight. Both return
`enforcement_claim: none`; preflight does not approve or merge anything.

The API has no network endpoint, CLI, default activation, v1 fallback, query
receipt migration or implicit host authentication. Filesystem and actor
isolation, approval of the Git ref and access to global control metadata remain
the host's responsibility. It does not prove that instructions were loaded by
a session or that a reported task was executed. It does not replace the v1
coordination, ingestion, query or requirements paths; their migration and an
operational task remain separate work. Do not expose this internal interface
to an untrusted caller as a permission system.
