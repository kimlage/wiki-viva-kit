# Hermes integration withdrawal — 2026-10-22

Status: the integration project is cancelled. This source-withdrawal record
is not proof of consumer promotion or installed-plugin removal.

## Scope

Remove only the optional Hermes wrapper/dashboard, native session/host bridge,
inactive kernel candidate, account/executor connection controls and their
exclusive tests. Mixed files retain source configuration, authentication
method/reference, ingestion, linked-action preview, canonical action transitions,
contribution/replay, dialogue, editing and standalone navigation. Secrets remain
prohibited; recipe credential rejection and diagnostic redaction remain active.

## Preservation

The preceding public source is available at immutable commit
[a08e99c454ee8130af375f701b8887213903818a](https://github.com/kimlage/wiki-viva-kit/tree/a08e99c454ee8130af375f701b8887213903818a),
also preserved locally as `archive/hermes-project-20261022-public`.
The selective change starts from merge `0be34cda44ab3c58467db4451d20b82b5634e179`.
No history is rewritten. Source documents, canonical actions, IDs, states and
literal events are preserved; existing access declarations are not bulk-rewritten.

## Upgrading

Use the normal B0/C1/C2/C3 sync and consumer review gates. C1 removes a retired
integration path only when the previous `kit.lock` owned it. Consumer-owned
files and private overrides must be reviewed separately. Rollback is the
reviewed PR reversal, not a reset of consumer data or unrelated work.

Installed desktop/dashboard plugins are a separate operational target. Removing
the kit source does not unload, disable or delete an installed plugin. Any later
retirement must identify its exact files, preserve recovery references and use
the host's supported procedure. This code change does not touch services,
external connectors, credentials, ACLs or source data.

## Validation

Local source-withdrawal checks passed: 2161 Python tests with 19 skips, 808
frontend tests, TypeScript, production build, architecture/assets/bundle and
script gates. Audit and public-export checks reported zero errors. The complete
Python run preceded the final packaging-only change that carries this note
through C1; its sync regression is checked separately. Synthetic source data,
authored demo pages and packs retain their exact bytes. The only memory edit is
the active CLI catalogue, where the cancelled installer is retired.

The 681 regenerated sample files differ only in removed `access`/`access_policy`
projections and the resulting snapshot IDs, integrity hashes and provenance.
Normal C2 generation and its deterministic check own these outputs.


Run the normal public gates and independent review on the exact candidate,
including standalone source configuration, credential rejection, action/ingestion
and contribution/replay coverage, plus refusal of retired HTTP routes and
previously-managed sync pruning. Synthetic checks are not live source access.
