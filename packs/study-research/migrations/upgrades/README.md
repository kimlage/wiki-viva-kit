# Upgrade migrations

Future versions add one declarative `<from>-to-<to>.yaml` migration here. Every
migration must keep `data_policy: preserve_user_content`; executable migration
code is not accepted by the kernel.
