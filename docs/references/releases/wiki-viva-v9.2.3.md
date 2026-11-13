# Wiki Viva v9.2.3

The access-secret check distinguishes URL userinfo from ordinary email
addresses in a URL path or query. It examines successive decoding layers so
encoded userinfo and recognized credential-bearing query parameters remain
blocked. Detection is heuristic and does not identify every possible secret.
This allows protected consolidation to review an authorized candidate with an
ordinary email-search link while retaining the existing secret checks.

## Upgrading

Use the reviewed `v9.2.3` tag after publication. Review the B0 dry-run, copy
kit-owned files in C1, run declared C2 generators and apply consumer-owned C3
changes explicitly. No configuration migration is required. Run the consumer's
gates and verify the intended authorized source lifecycle after adoption.
