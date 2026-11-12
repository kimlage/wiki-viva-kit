# Source registry and downstream fixture ownership

The shared registry emits an explicit collection of the exact canonical source
IDs it renders. Collection members do not move source nodes or their ingestion
events. IDs are unique, non-empty and serialized as strings.

Consumers may already declare a nested-source selection in their own
[wiki.config.yaml](../../../wiki.config.yaml):

```yaml
source_registry:
  nested_sources:
    - memories/sources/channel/selected.md
```

Direct pages in the legacy global sources directory remain canonical. The
configured sources directory name is also discovered under nested contexts in
`paths.memory_root`; no global directory is required. A declared selection allows
only the listed pages outside that direct legacy directory, including local
context sources; missing or non-source entries and malformed policies fail.
An empty selection includes no nested sources. With no policy the recursive
default remains unchanged. This is a local index policy, not an authorization
or new external ingestion permission. Recipe cadence, timestamps and data
boundaries retain their existing contracts.

Keep one canonical shared source page and reference it from its consumers.
Global projections aggregate the existing pages, without a second source list
or symlink aliases. Discovery prunes symlinks and nested Git repositories and
never grants cross-context access.

The public demo is authored against its own
[fixture page-type registry](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/docs/references/fixtures/demo-wiki/wiki.page-types.yaml).
Its cross-surface tests use that registry, preserving all five-event checks.
A downstream root's own type declarations do not redefine the synthetic demo.

## Upgrading

Adopt the approved pin by B0/C1/C2/C3 and regenerate the source registry using
[wiki_source_registry.py](../../../scripts/wiki_source_registry.py). Existing
consumer configuration is authoritative; no source-page metadata or custom
page types need to be rewritten. If a declared `nested_sources` selection should
include local sources, add their exact repository-relative paths to that same
selection. Regenerate affected input-stage and operation projections too; their
input selectors now use the configured memory root and collection directory
name, including future local pages. Keep exact consumer inventory assertions and
align translated display expectations with the central EN/ES/PT contract.
