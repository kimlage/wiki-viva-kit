// Command interpretation layer (god-mode plan §10). The CommandBar input is
// interpreted on Enter BEFORE search navigation: exact easter-egg phrases,
// exact `god_mode` invocations and the explicit "> " / "/admin" prefixes are
// commands; everything else stays untouched search input. The phrase is never
// a credential — parsing an invocation grants no privilege (plan §3.2).

export type EasterEggId = "takezo_ritual";

export type ParsedInput =
  | { kind: "search"; query: string }
  | { kind: "easter_egg"; id: EasterEggId }
  | { kind: "admin_command"; commandId: string; args: Record<string, string> }
  | { kind: "invalid_command"; messageKey: string };

// Every non-search interpretation the CommandBar forwards to its host.
export type CommandInvocation = Exclude<ParsedInput, { kind: "search" }>;

// Risk taxonomy (plan §9): extends the existing ActionCard vocabulary
// (`read`, `derive`) with the three administrative write levels.
export type CommandRiskLevel =
  | "read"
  | "derive"
  | "proposal_write"
  | "external_write"
  | "destructive";

export type CommandParameter = {
  name: string;
  required: boolean;
  // Closed set of accepted literal values (compared case-insensitively).
  // Any other value rejects the invocation — no fuzzy matching.
  values?: readonly string[];
  // Sensitive parameter values are redacted from the in-memory history and
  // must never appear in any log or notice (plan §10.4).
  sensitive?: boolean;
};

export type AdminCommandDefinition = {
  id: string;
  // Alias phrases, lowercase, tokens separated by single spaces. The first
  // alias is the canonical spelling shown in help.
  aliases: string[];
  // Capability groups (plan §8.1) the server must grant before this command
  // can plan or execute. The parser only carries them; enforcement is always
  // server-side and revalidated on execute.
  capability: string[];
  risk: CommandRiskLevel;
  parameters: CommandParameter[];
  helpKey: string;
  hidden?: boolean;
  // Server-side command-bus id (wiki_core/web/admin/commands.py) this parser
  // command materializes into via POST /api/admin/commands/plan. Absent while
  // the command has no bus adapter yet — invoking it then stays an honest
  // notice instead of a request that would 404.
  busCommandId?: string;
};
