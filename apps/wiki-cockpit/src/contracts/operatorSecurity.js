// One executable operator-handshake contract shared by the browser mutation
// boundary, Codex capability diagnostics and the Node downstream preflight.
// Diagnostics are deliberately value-free: a malformed local process cannot
// make a credential-shaped authored value appear in UI or release evidence.

export const REQUIRED_OPERATOR_SERVER_VERSION = "wiki_web_server.v6";
export const REQUIRED_OPERATOR_SECURITY_VERSION = "wiki_operator_security.v2";
export const REQUIRED_OPERATOR_NONCE_HEADER = "X-Wiki-Operator-Nonce";
export const REQUIRED_OPERATOR_ATTEMPT_HEADER = "X-Wiki-Attempt-Key";
export const REQUIRED_OPERATOR_MAX_BODY_BYTES = 1_048_576;
export const REQUIRED_OPERATOR_CAPABILITIES = Object.freeze([
  "operator_security_v2",
  "cors_default_deny_v1",
  "action_state_transitions_v1"
]);

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim() === value && value.length > 0;
}

export function validateOperatorHandshake(health) {
  const errors = [];
  const payload = record(health);
  if (!payload || payload.ok !== true) {
    errors.push("operator health did not report ok=true");
  }
  if (payload?.server_version !== REQUIRED_OPERATOR_SERVER_VERSION) {
    errors.push(`operator server version must be ${REQUIRED_OPERATOR_SERVER_VERSION}`);
  }

  const capabilities = Array.isArray(payload?.schema_capabilities)
    ? payload.schema_capabilities.filter((value) => typeof value === "string")
    : [];
  if (
    !Array.isArray(payload?.schema_capabilities) ||
    capabilities.length !== payload.schema_capabilities.length ||
    capabilities.some((value) => !nonEmptyString(value)) ||
    new Set(capabilities).size !== capabilities.length
  ) {
    errors.push("operator schema capabilities must be unique non-empty strings");
  }
  for (const capability of REQUIRED_OPERATOR_CAPABILITIES) {
    if (!capabilities.includes(capability)) {
      errors.push(`operator capability ${capability} is missing`);
    }
  }

  const security = record(payload?.operator_security);
  if (!security) {
    errors.push("operator security object is missing");
  } else {
    if (security.version !== REQUIRED_OPERATOR_SECURITY_VERSION) {
      errors.push(`operator security version must be ${REQUIRED_OPERATOR_SECURITY_VERSION}`);
    }
    if (!nonEmptyString(security.nonce)) {
      errors.push("operator security nonce is missing");
    }
    if (security.nonce_header !== REQUIRED_OPERATOR_NONCE_HEADER) {
      errors.push(`operator nonce header must be ${REQUIRED_OPERATOR_NONCE_HEADER}`);
    }
    if (security.attempt_header !== REQUIRED_OPERATOR_ATTEMPT_HEADER) {
      errors.push(`operator attempt header must be ${REQUIRED_OPERATOR_ATTEMPT_HEADER}`);
    }
    if (
      !Number.isSafeInteger(security.max_body_bytes) ||
      security.max_body_bytes < 1 ||
      security.max_body_bytes > REQUIRED_OPERATOR_MAX_BODY_BYTES
    ) {
      errors.push(`operator max body bytes must be between 1 and ${REQUIRED_OPERATOR_MAX_BODY_BYTES}`);
    }
    if (security.mutations !== "post_only") {
      errors.push("operator mutations contract must be post_only");
    }
    if (security.browser_origin_default !== "deny") {
      errors.push("operator browser origin default must be deny");
    }
    if (security.cors_opt_in !== "exact_loopback_allowlist") {
      errors.push("operator CORS opt-in must be exact_loopback_allowlist");
    }
  }

  if (errors.length || !security) return { ok: false, errors, security: null };
  return {
    ok: true,
    errors: [],
    security: {
      version: security.version,
      nonce_header: security.nonce_header,
      nonce: security.nonce,
      attempt_header: security.attempt_header,
      max_body_bytes: security.max_body_bytes,
      mutations: security.mutations,
      browser_origin_default: security.browser_origin_default,
      cors_opt_in: security.cors_opt_in
    }
  };
}

export function operatorRestartReason(validation) {
  const detail = validation.errors[0] || "operator handshake is invalid";
  return `the local operator is outdated; restart it to activate ${REQUIRED_OPERATOR_SECURITY_VERSION} (${detail})`;
}

export function operatorSecurityEvidence(validation) {
  if (!validation.ok || !validation.security) return null;
  return {
    version: validation.security.version,
    nonce_present: true,
    nonce_header: validation.security.nonce_header,
    attempt_header: validation.security.attempt_header,
    max_body_bytes: validation.security.max_body_bytes,
    mutations: validation.security.mutations,
    browser_origin_default: validation.security.browser_origin_default,
    cors_opt_in: validation.security.cors_opt_in
  };
}
