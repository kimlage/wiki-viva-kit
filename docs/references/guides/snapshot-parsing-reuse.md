# Snapshot compilation parsing reuse

Compiling a large wiki reads some pages in several projections. The page
index, block model and source model can parse the same YAML frontmatter more
than once before a single snapshot is returned.

The compiler now reuses the result of parsing identical YAML blocks within
that compilation. It still reads the file and its current body on every
call. Content changes produce a new key, and callers receive independent
copies of the parsed mapping. The context is discarded on return or error;
there is no disk cache or cross-request cache. Its retained block text is
limited to 8 MiB, 2,048 entries and 64 KiB per block; Python mapping overhead
is additional. Oversized blocks or a full cache use normal parsing.

The safe YAML loader and flat parser contracts are unchanged. The local
operator retains its source revision checks, write exclusion, snapshot TTL,
action CAS and receipt validation. This change does not connect an executor,
grant access, dispatch work or change action state.

An isolated public fixture with 900 pages and 50 actions performed 2,700 YAML
loads before this change and 900 afterward. One profiled compilation took
3.94 seconds before and 2.88 seconds afterward. These measurements are local
observations, not a latency guarantee for a consumer or an installed service.

[Parser tests](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_frontmatter_compilation_cache.py) cover
fresh file/body reads, independent mappings, cleanup after failure, nested
scopes, thread isolation, cache limits and safe-loader semantics.
[Snapshot parity](https://github.com/kimlage/wiki-viva-kit/blob/c46568234f8d16d81f1e38140246a31d4faff9c8/tests/test_snapshot_frontmatter_cache.py) compares
the complete payload with reuse enabled and disabled, at the same revision
and generation time.

## Upgrading

Apply the kit's normal B0/C1/C2/C3 sync and the consumer's review gates. There
is no configuration, schema, data or action migration. This patch alone does
not change a running operator. A consumer should not discard its worktree or
restart an active service as part of diagnosing a slow read.
