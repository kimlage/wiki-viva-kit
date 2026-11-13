# Wiki Viva v9.2.1

This patch corrects the snapshot revision for a clean repository root after a
merge. The manifest reports the actual checked-out commit, so downstream operator
checks can bind the served content to the approved merge. Nested source scopes
retain their existing scoped identity, and dirty sources remain explicit.

Cancellation is also synchronized with subprocess startup: a job cancelled
before launch does not start the agent, and cancellation during startup can
terminate the registered process. The job remains running until cleanup ends.

## Upgrading

Use the reviewed `v9.2.1` tag after publication. Review the B0 dry-run, copy
kit-owned files in C1, run declared C2 generators and apply any consumer-owned
C3 migration explicitly. Run the consumer's applicable gates and verify the
installed operator and content together. See the [v9.2.0 upgrade notes](wiki-viva-v9.2.0.md#upgrading).
