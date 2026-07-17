---
title: "Wiki Viva v8.1"
page_id: release-wiki-viva-v8-1
page_type: release_note
context: system
visibility: public_candidate
updated_at: 2026-07-17
stale_after_days: 365
sources_policy: release_note
gate: github_pr
sensitive_data_policy: no_personal_data
---

# Wiki Viva v8.1

Dual-epic release for the open-source kit: the Source Foundation Plane and the
advanced operator entry (god mode). Both features are flag/capability gated —
a snapshot or operator that does not advertise them behaves exactly as before.
The cockpit package version moves from 0.2.0 to 0.3.0.

## Source Foundation Plane

The sources view is refactored from a flat listing into a below-plane
foundation: sources, channels and governance controls now live in a vertical
band structure underneath the knowledge world.

- New payload contract `wiki_web_source_foundation.v1`, compiled last in the
  snapshot so its revision derives from the payload set built before it.
- New manifest content capability `source_foundation_v1`: a snapshot advertises
  it only when a valid `source_foundation.json` payload was built and
  validated. A snapshot without it falls back to the legacy sources layout; a
  snapshot with it and without a valid payload is a contract error, never an
  empty fake topology.
- Registry-driven spatial and camera profiles (`knowledge-upper`,
  `source-foundation`) with the four vertical bands `core`, `knowledge`,
  `provenance`, `foundation`. Y between bands is structural role; Y inside a
  band is bounded visual adjustment only.
- Lower-hemisphere camera with an `outer_arc` transition path: the user orbits
  inside the view's hemisphere and only a registered view change crosses the
  horizon.
- Dedicated foundation renderer (stations, lanes, governance plates, density
  counters) composed as an independent scene layer, active only when the
  view's plane profile is `foundation`.
- SourceDock lifecycle parity: closing the dock (or leaving its source)
  retires the ephemeral scene highlight and trace signals explicitly.
- 2D fallback bands with navigable sections and ARIA labels, so degraded mode
  keeps the same structural story.
- Honest typed diagnostics throughout: missing or malformed foundation data
  surfaces as a named contract state, never as an invented topology.
- Many-to-many provenance is preserved: a page may cite several sources and a
  source may feed several pages, in the payload and in the rendered lanes.

## Advanced operator entry (god mode)

- The `abrachaindabra` easter egg summons Takezo, a fully procedural
  character. It is a pure easter egg: no brand references, no data access, and
  the word itself never grants authority.
- Read-only Admin Dock (`?dock=admin`): registered like every dock but never
  part of the default navigation; discoverability comes from the `ui_admin`
  block and authorization always comes from the server.
- Operator handshake bumped to `wiki_web_server.v7` with admin schema
  capabilities `admin_capabilities_v1`, `admin_session_v1` and
  `admin_commands_v1`, so the cockpit detects a stale operator honestly
  instead of showing a raw 404.
- Local session unlock: startup code plus challenge nonce, in-memory session
  tokens with TTL and idle expiry — nothing admin-related is persisted to the
  browser.
- Hash-chained admin audit log: every admin action appends to a tamper-evident
  chain.
- Plan -> review -> execute command bus: plans are materialized server-side
  and executed only against a matching `plan_sha`; the browser never sends
  argv.

## Compatibility

- Old snapshots keep loading: the foundation payload is optional and
  capability-gated, so a pre-v8.1 snapshot renders the legacy sources layout.
- Old operators are detected honestly via the `wiki_web_server.v7` handshake
  and reported as an outdated-operator state instead of failing on missing
  endpoints.
- The easter-egg word never grants authority; every admin surface remains
  gated by the server-side session and capability contracts.
