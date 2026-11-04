# Experimental host-bound source reassessment

The [source reassessment command](../../../scripts/wiki_folder_reassessment_v2.py)
uses `wiki_core.folder_reassessment_host_v2.prepare_folder_reassessment`, a
read-only adapter around the existing v2 source reassessment. The host
constructs and retains a `FolderHostBinding` for an absolute repository root and
an explicit set of folders. Request data must not construct that binding.
A folder binding is not a grant to other folders or a filesystem ACL.

The request names the bound folder, fixed approved revision, exact source,
explicit reports and either selected consumer paths or an owner-scoped path.
Auxiliary-start packets are currently refused by this adapter.
The host checks binding and selection, current ownership and read permissions,
all explicit report evidence and historical policy connections before opening
selected consumers. Historical replay additionally requires equivalent Git
objects for the authorized instruction chain, mandatory references and selected
index. A cross-owner source requires an explicit report with an approved exact
bilateral connection; without such a report the adapter refuses the request.
The underlying inventory still checks every selected consumer before reading it.

For an independent local Git selection the same adapter accepts the optional
`independent_repo` object and reported `repo_read` results described in the
[source reassessment guide](folder-v2-experimental-usage.md). The trusted host
must construct its binding with an explicit tuple of `(folder, absolute root,
expected origin identity, repository-relative path)` entries; the default is
empty. The payload cannot add entries to the binding. Each requested folder,
resolved root, identity and exact path must match that list before the
repository is opened, and wiki source/report permissions are checked before
selected Git content is read. Matching a node, URL or configured origin does
not itself grant access or prove remote authentication. The compared commit is
explicitly selected and is not asserted to be HEAD.

The result is a scoped preview, not consumer discovery or a receipt registry.
Declarations and reported reads are not independent execution evidence. A
changed or missing source never approves, writes, merges or proves freshness.
The host must independently verify repository and actor identity, approval of
the trusted ref, and actual filesystem access. Field and section selection
limits delivery only: `RepositoryReader` loads the entire Git blob, so the host
must be authorized to read that whole blob.

The CLI constructs its binding from the trusted host environment and accepts a
recorded contextual ingestion request through `--source-request` when required.
Its result retains the existing reassessment schema and pending statuses. Direct
`reassess_folder_source_v2` calls do not have a `FolderHostBinding` and are for
a trusted coordinator. This does not provide a network endpoint, v1 receipt
migration, query migration or automatic activation. Independent review and tests
are required before downstream adoption.
