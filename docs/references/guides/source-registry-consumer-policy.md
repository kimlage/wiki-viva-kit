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

Direct source pages remain canonical. A declared selection allows only those
nested source pages; missing or non-source entries and malformed policies fail.
An empty selection includes no nested sources. With no policy the recursive
default remains unchanged. This is a local index policy, not an authorization
or new external ingestion permission. Recipe cadence, timestamps and data
boundaries retain their existing contracts.

The public demo is authored against its own
[fixture page-type registry](../fixtures/demo-wiki/wiki.page-types.yaml).
Its cross-surface tests use that registry, preserving all five-event checks.
A downstream root's own type declarations do not redefine the synthetic demo.

## Upgrading

Adopt the approved pin by B0/C1/C2/C3 and regenerate the source registry using
[wiki_source_registry.py](../../../scripts/wiki_source_registry.py). Existing
consumer configuration is authoritative; no source-page metadata or custom
page types need to be rewritten. Keep exact consumer inventory assertions and
align translated display expectations with the central EN/ES/PT contract.
