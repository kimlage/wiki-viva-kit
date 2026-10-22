# Source configuration and linked-action previews

The Sources workspace retains its catalogue, source and record settings,
authentication method and non-secret reference, inventory refresh and ingestion.
Configuration changes use the existing content-bound preview/confirmation flow.
The cancelled Hermes connection controls, executor bindings, account tests and
source-host pairing are removed. Historical access fields are not interpreted
as authorization, and existing source documents are not rewritten by this change.

No credential belongs in a recipe. `auth.ref` is a non-authorizing locator in
the official client or secret store. URLs, bearer values and credential-looking
blobs are refused. Capability flags and a successful process exit do not prove
access to a private resource. The original authorization card remains descriptive;
the wiki does not connect accounts or grant permissions.

## Textual wiki content and external originals

A consumer that keeps originals outside its wiki can enable an existing-auditor
check without changing application resources or granting storage access:

```yaml
audit:
  wiki_text_storage:
    enabled: true
    roots: [memories, docs]
```

Roots are explicit, unique repository-relative content directories. The check
runs in `wiki_audit.py --check`, including the existing `drive_artifact_links`
selection. It rejects binary/source-container content in those directories by
bytes rather than extension, even when tracked, untracked or ignored by Git.
Application code and its resources outside those content roots are unaffected;
do not put an application resource directory in this policy based on extension.
UTF-8 Markdown, code examples and operational configuration remain valid.

The existing `data/drive_artifacts_manifest.json` also identifies external
captures by normalized `source_path`: a file still present in a selected content
root is refused even if it is UTF-8 JSON. The audit does not infer the purpose of
uncatalogued text. Legacy entries may omit `source_path`; a declared malformed
path is an error. Normalized absolute external paths remain metadata only and
are not opened; an absolute path inside the checkout guards the same local file.
The audit does not
authenticate, verify remote custody, upload, delete, rewrite
historical evidence or authorize a financial export. Review that classification
and verify the correct external destination, access, exact bytes and references
before removing an original. Retain its Git provenance without rewriting history.
The feature is absent by default; malformed policies and unreadable catalogs
refuse when configured. Existing privacy and secret gates remain mandatory.

## Read-only event-to-action composition

The existing ingestion plan and Add surface expose a linked-action preview.
A normalized event must explicitly record `source_account` and `source_refs`.
Its linked source-config page may declare `action_binding`:

```yaml
action_binding:
  repo_id: fictional-wiki
  source_key: source-logical
  account_id: reader@example.test
  context: research
  event_id: event-fictional
  event_sha256: <exact event document SHA256>
  action_id: action-review-fictional
  action_sha256: <exact existing action SHA256, or empty for a new proposal>
  owner_ref: person-example
  coordinator: research
  required_sources: [corporate, tasks]
```

The event links its config with `config_ref`. The server supplies its canonical
snapshot; no browser-supplied snapshot or callback command is accepted. The
composer reuses the normalized-event identity resolver, real manifest, canonical
action index and explicit coordinator routes. It returns `reuse`, `propose`,
`reconcile`, `conflict` or `unmapped`, with a stable preview key and task reference.
Same event/account/binding yields the same target; revision changes reconcile.
Similar titles or contexts do not establish business identity. A new card is
only proposed, with coordinator binding pending. STOP, human waits and terminal
states are retained; `execution_ready` and `writes` always remain false.
Required-source reads remain explicitly unknown; this preview does not consult
corporate services, Tasks, accounts or a model.

## Validation boundary

The composed contribution test uses real synthetic files, Git/bare transport,
canonical action state and local HTTP served-body readback. Executor output,
independent review, GitHub/CI and merge service are doubles. It proves neither
live account access nor an autonomous runtime. Ingestion previews remain
read-only and never authorize a source read or create an executor.

The [withdrawal record](../releases/hermes-integration-withdrawal-2026-10-22.md)
identifies the preserved code cut and the separate installed-plugin boundary.
