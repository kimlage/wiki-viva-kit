# Upgrade migrations

Each future release adds a declarative `<from>-to-<to>.yaml` migration with
`data_policy: preserve_user_content`. Pack upgrades may adapt generated bundle
contracts; they never delete account, transaction, obligation, reconciliation
or closing pages authored by the user.
