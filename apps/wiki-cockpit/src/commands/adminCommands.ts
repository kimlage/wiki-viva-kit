// Initial admin command table (god-mode plan §10.5). Declaring a command here
// only teaches the parser its shape: capabilities are granted by the server
// per session and revalidated on execute (plan §8.2); no command accepts raw
// shell by construction. Commands with a busCommandId materialize a reviewed
// plan through the server-side command bus (PR4); the rest keep an honest
// "not wired yet" notice until their adapters ship.

import { buildCommandRegistry } from "./registry";
import type { AdminCommandDefinition } from "./types";

export const GOD_MODE_COMMAND_ID = "god_mode";

export const ADMIN_COMMANDS: readonly AdminCommandDefinition[] = [
  {
    id: GOD_MODE_COMMAND_ID,
    aliases: ["god_mode"],
    capability: ["session.manage"],
    risk: "read",
    // v1 subcommands (§10.5): bare opens the gate, `status` reports, `off`
    // locks. Anything else is not an exact invocation.
    parameters: [{ name: "subcommand", required: false, values: ["status", "off"] }],
    helpKey: "command.help.god_mode"
  },
  {
    id: "admin.overview",
    aliases: ["admin overview", "admin status"],
    capability: ["system.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_overview"
  },
  {
    id: "admin.inspect_system",
    aliases: ["admin inspect system"],
    capability: ["system.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_inspect_system",
    busCommandId: "system.inspect"
  },
  {
    id: "admin.inspect_config",
    aliases: ["admin inspect config"],
    capability: ["config.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_inspect_config",
    busCommandId: "config.inspect"
  },
  {
    id: "admin.config_validate",
    aliases: ["admin config validate"],
    capability: ["config.validate"],
    risk: "derive",
    parameters: [],
    helpKey: "command.help.admin_config_validate",
    busCommandId: "config.validate"
  },
  {
    id: "admin.config_diff",
    aliases: ["admin config diff"],
    capability: ["config.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_config_diff"
  },
  {
    id: "admin.gates_run",
    aliases: ["admin gates run"],
    capability: ["gates.run"],
    risk: "derive",
    parameters: [],
    helpKey: "command.help.admin_gates_run"
  },
  {
    id: "admin.sources_inspect",
    aliases: ["admin sources inspect"],
    capability: ["sources.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_sources_inspect"
  },
  {
    id: "admin.source_plan",
    aliases: ["admin source plan"],
    capability: ["sources.plan"],
    risk: "derive",
    parameters: [{ name: "id", required: true }],
    helpKey: "command.help.admin_source_plan"
  },
  {
    id: "admin.git_status",
    aliases: ["admin git status"],
    capability: ["git.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_git_status"
  },
  {
    id: "admin.git_proposals",
    aliases: ["admin git proposals"],
    capability: ["git.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_git_proposals"
  },
  {
    id: "admin.work_jobs",
    aliases: ["admin work jobs"],
    capability: ["agents.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_work_jobs"
  },
  {
    id: "admin.vision_discover",
    aliases: ["admin vision discover"],
    capability: ["views.discover"],
    risk: "derive",
    parameters: [],
    helpKey: "command.help.admin_vision_discover"
  },
  {
    id: "admin.vision_preview",
    aliases: ["admin vision preview"],
    capability: ["views.preview"],
    risk: "read",
    parameters: [{ name: "id", required: true }],
    helpKey: "command.help.admin_vision_preview"
  },
  {
    id: "admin.vision_propose",
    aliases: ["admin vision propose"],
    capability: ["views.propose"],
    risk: "proposal_write",
    parameters: [{ name: "id", required: true }],
    helpKey: "command.help.admin_vision_propose"
  },
  {
    id: "admin.audit_recent",
    aliases: ["admin audit recent"],
    capability: ["audit.inspect"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_audit_recent"
  },
  {
    // Listing recovery options is read-risk, but the whole domain stays
    // behind the recovery capability so the option list never renders for a
    // session that could not act on it.
    id: "admin.recovery_options",
    aliases: ["admin recovery options"],
    capability: ["recovery.execute"],
    risk: "read",
    parameters: [],
    helpKey: "command.help.admin_recovery_options"
  }
];

export const ADMIN_COMMAND_REGISTRY = buildCommandRegistry(ADMIN_COMMANDS);
