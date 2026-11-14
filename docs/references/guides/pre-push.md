# Optional pre-push checks

Opt in per repository after reviewing this script and the existing hook setup:

```sh
python3 scripts/wiki_pre_push.py --root . --install
```

The installer configures `core.hooksPath` locally and refuses to replace an
existing hook or configured hook path. If hooks already exist, integrate this
script manually in that hook; do not silently discard them. The installed hook
uses the script and dependencies in the invoking worktree. A worktree without
the script cannot push until it is updated. It uses that worktree's `.venv`
Python when present, otherwise `python3` from `PATH`; the selected interpreter
must have the kit's dependencies. The default budget is
10 seconds; timeout, failed checks, and incomplete object reads block the push.
Timeout and catchable interruption terminate the worker group. A descendant that
deliberately leaves that group, or a forced termination of the supervisor,
requires containment by the host.

For each non-deleted ref, the hook checks whitespace in the pushed tree range
and runs the kit's secret detector on introduced blobs, path names, commit
messages and tag objects, including blobs later removed before the tip. For a
new ref the hook performs one bounded `git ls-remote` query against the actual
push URL and uses its current `main` as a baseline only if present locally and
ancestral. When an `insteadOf` rule could rewrite the supplied URL again, or
the baseline is unavailable, the hook scans the full reachable history. Local
remote-tracking refs are never proof of the
server's state. The server can change after the observation, so this is not a
substitute for server-side secret protection. A missing object or
more than 50 MB of candidate objects blocks instead of silently skipping the
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
the shared budget. Configuration comes from each pushed commit, not from an
uncommitted or untracked file. These commands run from the working tree, so configured commands
require every pushed tip to be the checked-out HEAD and tracked files to match
HEAD. The hook blocks if index flags such as `assume-unchanged` or
`skip-worktree` could hide changes, or if submodules are uninitialized or
different from the committed state. It compares raw tracked bytes to Git blobs,
so Git filters or line-ending conversions that change bytes cause a block. These checks do not establish the state of
untracked files. A repo without this
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
