# Source access and linked-action previews

The existing Sources workspace separates **declared configuration**, **adapter
evidence**, and **execution authority**. Open a source's Update tab to inspect
its account, context coordinator, executor, requested and observed scopes,
last probe, validity, source update date, and technical state. Configure edits
expected metadata through the existing content-bound preview/confirmation flow.
Saving a declaration does not authenticate, grant permissions or activate a bot.

No credential belongs in a recipe. `auth.ref` is a non-authorizing locator in
the official client or secret store. URLs, bearer values and credential-looking
blobs are refused. Profiles, provider login, capability flags and successful
process exit do not prove access to a resource or isolation of accounts.

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

## Declared access

An optional `access` mapping in the existing source recipe has this shape:

```yaml
access:
  schema_version: wiki_source_access.v1
  expected_identity: reader@example.test
  coordinator: research
  executor: example-executor
  requested_scopes: [read]
```

These are fictional values. Real identities remain in the private consumer.
The existing source-operation API accepts `access` only at source scope; its
preview token binds the complete configuration, and stale confirmation refuses
the write. Observed identity, granted scopes and verification cannot be set by
this browser patch. There is no new credential registry, task store or runner.

## Evidence from a supported adapter

Only the repository-owned, allowlisted deterministic refresh adapter may
optionally return `access_probe` beside its existing inventory. It is not read
from an authored recipe or accepted as an HTTP grant. The adapter owns the
official authentication mechanism and its truthful resource-read assertion.
Its complete observation contains exactly:

```json
{
  "schema_version": "wiki_source_access.v1",
  "binding_sha256": "<digest of the exact source_access_subject>",
  "outcome": "verified",
  "confirmed_identity": "reader@example.test",
  "granted_scopes": ["read"],
  "checked_at": "2026-01-01T12:00:00Z",
  "valid_until": "2026-01-01T12:05:00Z",
  "evidence_ref": "receipt:fictional-resource-read",
  "error_code": ""
}
```

The binding is SHA256 of UTF-8 canonical JSON (`sort_keys=True`,
`ensure_ascii=False`, `allow_nan=False`, separators `(',', ':')`) over
`source_access_subject(source)`: source ID, context, platform, locator, auth
pointer and declared access. A different account, executor, scope or context
cannot reuse that evidence. Dates require timezones and a valid finite window;
expired evidence is unknown. A successful inventory without this observation
remains unverified. A local report is trusted adapter evidence, not a signed
platform permission or proof of an autonomous workflow.

Retained source-operation receipts show their historical probe cut after a
reload; a new view requires revalidation before showing verified access again.
This prevents an older receipt from hiding a later session failure or denial.

Other outcomes are `awaiting_auth`, `awaiting_approval`, `authority_blocked`,
`technical_blocked`, `execution_unknown`, and `revoked`. A denial is not an
expired login. Uncertain effects require reconciliation of the same task before
retry. Probes and their diagnostics cannot contain secrets or authorization URLs.

Revalidation is offered only through the existing deterministic-adapter preview.
An agent connector, missing adapter or manual-export route has no invented
Connect/Grant/Disconnect control. Use the supported official client when needed;
disabling a tool is not revoking an account. Declared-access sources cannot apply
inventory through this route until fresh identity/scope evidence is verified.
Legacy recipes without access declarations retain their existing behavior and
are never upgraded to verified by capability or exit code.

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

## Validation and remaining acceptance

Public tests use fictional identities and clearly identify their doubles. The
composed cycle uses real local files/manifests, templates, context/transition
helpers, Git/bare transport and HTTP readback. Account probes, executor output,
independent review, GitHub/CI and merge service are synthetic; fixture gate
scripts prove invocation, not auditor acceptance. Replay, wrong accounts,
expiry, approval/denial, revocation, unknown effects and interrupted merge are
covered without claiming live account or autonomous-runtime acceptance.

Actual activation still requires an authorized real source read, event, same
canonical task, admitted executor, result, independent exact-head review,
applicable gates, merge and served-byte readback. Repeat without duplicate
effects and validate supported expired-login/interruption recovery before
scheduling autonomy. Pending work may recur briefly in reports; old results
must retain their original dates and must not appear as new progress. No
unchanged-source rule hides a still-open decision, question or access problem.
