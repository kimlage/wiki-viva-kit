---
name: wiki-privacy-publication
description: Separate private operational memory from public derivatives, allowing useful private context in private repos while blocking secrets and unsafe publication.
---

# Wiki Privacy Publication

## Rules

- Private pages keep personal data (PII) freely: in a private personal repo it is welcome, not a risk.
- Access secrets (tokens, passwords, keys, cookies) are never kept, in any page -- private or public.
- Public candidates must be rewritten as derivatives and reviewed separately.
- Do not publish without redaction: private feedback, personal documents, ledgers or secure links (they carry PII). Never publish access secrets at all.
- Every public candidate needs a redaction checklist, source freshness check and independent PR review under the repository's [AGENTS.md](../../AGENTS.md). Privacy and secret failures remain fail-closed.

## Tool and API output

- An API or CLI response never appears whole in a terminal, thread, log or file.
  Select the allowed fields first (`jq`, `--format`, `--json <fields>`, `-q`) and
  record that filtered command, not the raw response.
- Do not fetch a full configuration object (for example an identity provider's
  project configuration) to read one field; request only that field.
- Invite codes, verification and one-time codes, pairing codes and individualized
  links are access secrets. Treat a password-hash configuration (signer key,
  salt separator) the same way.
- If a secret was exposed in output, record the incident without the value and
  rotate it. The audit scans versioned files and commits; it cannot redact
  output that was already printed.
