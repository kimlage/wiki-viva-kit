---
page_id: guide-sealed-demo-admin-journeys
page_type: reference_guide
title: Sealed demo admin journeys and downstream adoption
context: system
visibility: public_candidate
updated_at: 2026-09-30
stale_after_days: 90
sources_policy: implementation_and_synthetic_tests
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Sealed demo admin journeys and downstream adoption

The public synthetic demo now includes the same ritual and administrative
surface as downstream runtimes. Presentation is separate from authority:
opening a dock, typing a phrase or changing its URL grants no session.
The demo never sends an administrative request or offers an unlock button.

The four [browser journeys](../../../apps/wiki-cockpit/e2e/god-mode.spec.ts)
exercise the 3D ritual and its Escape/focus return, honest unavailable admin
dock, reduced-motion twin and forced 2D fallback. All assert zero admin requests
and zero runtime errors. Collection contains 106 public cases and two separate
downstream cases, with every prior public cell preserved. The current
[collection test](../../../apps/wiki-cockpit/scripts/demo-journeys.test.mjs)
checks the complete collected contract and all four journeys; it does not
reactivate the retired lane/capsule/attestation release state machine.

The common [admin implementation](../../../wiki_core/web/admin/__init__.py)
uses process-bound sessions and reviewed server-side plans. Unlock needs the
local process's expiring, single-use code and a fresh challenge, on top of the
existing operator nonce and attempt-key checks. Tokens live in memory only;
roles, configuration and reviewed plan hashes remain server authority.
Break-glass stays off. This adoption does not enable a service, register a
connector, grant persistent access or change an existing consumer's config.

## Upgrading

Follow the [B0/C1/C2/C3 runbook](wiki-viva-v8-downstream-upgrade.md) and pin
the merged source commit. C1 must copy shared code byte-for-byte, including the
journeys and their collection contract. Preserve consumer-owned memory,
configuration, assets and other worktrees; run the consumer's own gates and
read back the affected cockpit after adoption.

Consumers with local source icons must move only their extra declarations to
`assets/consumer-assets.v1.json` under the
[cockpit app](../../../apps/wiki-cockpit/README.md), with this schema:

```json
{"schema_version":"wiki_cockpit_consumer_assets.v1","assets":[]}
```

This file and a consumer-owned license notice are explicit C3 content, absent
from the kit's tracked inventory. Do not put personal brand names or data in
the public kit. Keep each asset's exact path, byte count, SHA-256, license hash,
provenance and per-item budget. A brand-use notice uses
`LicenseRef-Brand-Asset` and must contain both that identifier and
`Brand asset use notice`; software licenses are not substituted for trademarks.

The [asset gate](../../../apps/wiki-cockpit/scripts/asset-gate-lib.mjs) combines
the kit's base inventory and these declarations while preserving the kit's
policy and global ceilings. Consumer declarations may add only local source
icons; they cannot override policy, dependency identity or shared paths.
Duplicate identities/paths, aliases, traversal, hash/license drift,
unmanifested files and over-budget assets remain failures. The shared manifest
still declares its exact eight third-party assets. Synthetic tests exercise
the added inventory and every refusal above.
