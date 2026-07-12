export type OperatorSecurityContract = {
  version: "wiki_operator_security.v2";
  nonce_header: "X-Wiki-Operator-Nonce";
  nonce: string;
  attempt_header: "X-Wiki-Attempt-Key";
  max_body_bytes: number;
  mutations: "post_only";
  browser_origin_default: "deny";
  cors_opt_in: "exact_loopback_allowlist";
};

export type OperatorHandshakeValidation =
  | { ok: true; errors: []; security: OperatorSecurityContract }
  | { ok: false; errors: string[]; security: null };

export type OperatorSecurityEvidence = Omit<OperatorSecurityContract, "nonce"> & {
  nonce_present: true;
};

export const REQUIRED_OPERATOR_SERVER_VERSION: "wiki_web_server.v6";
export const REQUIRED_OPERATOR_SECURITY_VERSION: "wiki_operator_security.v2";
export const REQUIRED_OPERATOR_NONCE_HEADER: "X-Wiki-Operator-Nonce";
export const REQUIRED_OPERATOR_ATTEMPT_HEADER: "X-Wiki-Attempt-Key";
export const REQUIRED_OPERATOR_MAX_BODY_BYTES: 1048576;
export const REQUIRED_OPERATOR_CAPABILITIES: readonly [
  "operator_security_v2",
  "cors_default_deny_v1",
  "action_state_transitions_v1"
];

export function validateOperatorHandshake(health: unknown): OperatorHandshakeValidation;
export function operatorRestartReason(validation: OperatorHandshakeValidation): string;
export function operatorSecurityEvidence(
  validation: OperatorHandshakeValidation
): OperatorSecurityEvidence | null;
