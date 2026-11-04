# Experimental host-bound source reassessment

`wiki_core.folder_reassessment_host_v2.prepare_folder_reassessment` is an
opt-in, read-only adapter around the existing v2 source reassessment. The host
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

The result is a scoped preview, not consumer discovery or a receipt registry.
Declarations and reported reads are not independent execution evidence. A
changed or missing source never approves, writes, merges or proves freshness.
The host must independently verify repository and actor identity, approval of
the trusted ref, and actual filesystem access. Field and section selection
limits delivery only: `RepositoryReader` loads the entire Git blob, so the host
must be authorized to read that whole blob.

This adapter is not automatically applied to `wiki_folder_reassessment_v2.py`
or direct `reassess_folder_source_v2` calls. Those interfaces have no
`FolderHostBinding` and must only be offered to a coordinator trusted for
those accesses. The adapter has no CLI, network endpoint, v1 receipt migration,
query migration or automatic activation. Independent review and tests are
required before downstream adoption.
