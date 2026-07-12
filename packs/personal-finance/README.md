# Personal Finance experience pack

This pack is the first full operational vertical built on the experience-pack
kernel. It models private accounts, transactions, obligations, categories,
reconciliations and monthly closings while shipping only synthetic public
fixtures.

Its v2 temporal adapters compile transaction occurrence, obligation due date,
reconciliation period and monthly period/close into namespaced canonical
events. Dense and failure scenarios are declarative inputs to the trusted core
fixture compiler; no pack-owned code is executed.

All operations are declarative, default to dry-run and require a reviewed
`wiki/*` branch plus a human Git gate before canonical mutation. The pack never
contains credentials, authenticated links or real financial records. Its asset
manifest is intentionally empty until a separately approved, licensed asset is
available.
