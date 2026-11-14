# Optional pre-push checks

Opt in per repository after reviewing this script and the existing hook setup:

```sh
python3 scripts/wiki_pre_push.py --root . --install
```

The installer configures `core.hooksPath` locally and refuses to replace an
existing hook or configured hook path. If hooks already exist, integrate this
script manually in that hook; do not silently discard them. Keep the script and
its Python dependencies available at the installed path. The default budget is
10 seconds; timeout, failed checks, and incomplete object reads block the push.

For each non-deleted ref, the hook checks whitespace in the pushed tree range
and runs the kit's secret detector on blobs reachable in the introduced commit
history, including blobs later removed before the tip. For a new branch it uses
the locally known `<remote>/main` as the base only if that is an ancestor;
otherwise it examines the full available history. This offline estimate may be
stale and is not proof of the server's current history. A missing object or
more than 50 MB of candidate blobs blocks instead of silently skipping the
scan. Results do not replace CI, review, server-side protection, or the full
privacy audit. It does not print matching content.

An optional consumer-owned `wiki.config.yaml` may declare additional quick
checks as argument arrays, without a shell:

```yaml
pre_push:
  quick_commands:
    - [python3, scripts/check_my_queue.py, --check]
```

Only configure commands that are safe to run automatically and finish within
the shared budget. These run from the working tree, so configured commands
require every pushed tip to be the checked-out HEAD and tracked files to match
HEAD. They do not establish the state of untracked files. A repo without this
configuration runs the generic checks alone. Deleting a ref has no content to
check. The consumer is responsible for declaring any queue freshness gate.

Only on the owner's explicit emergency instruction, bypass this hook for one
push with `git -c core.hooksPath=/dev/null push ...` (use a suitable empty hook
directory instead of `/dev/null` on Windows). Record the reason and perform the
omitted validation afterwards. This does not bypass server-side policy.

## Kit main protection

The kit's `main` protection requires a PR and current base (`strict`), applies
to administrators, and does not require a GitHub approval. The required status
contexts are `audit-and-test`, `cockpit-v8`, `browser-journeys (desktop-1)`,
`browser-journeys (desktop-2)`, `browser-journeys (visual-mobile)`,
`browser-journeys (cross-browser)`, `snapshot-flat-windows`, and
`cockpit-browser`. Independently reviewed exact-head evidence remains required
by the kit's policy. Verify live configuration with
`gh api repos/kimlage/wiki-viva-kit/branches/main/protection`; this document is
not proof that server settings are currently applied.
