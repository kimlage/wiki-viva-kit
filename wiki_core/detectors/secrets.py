"""High-confidence secret detectors (API keys, tokens, private keys).

Precision is favoured over recall: each pattern targets a known credential
shape, and the generic assignment rule additionally requires the candidate
value to look random (high Shannon entropy) before reporting.
"""

from __future__ import annotations

import json
import math
import re

from . import Finding, line_of, redact

_DETECTOR = "secrets"
_CATEGORY = "secret"

# (kind, severity, compiled pattern). Order is informative only.
_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "aws_access_key",
        "critico",
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ),
    (
        "google_api_key",
        "critico",
        re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    ),
    (
        "slack_token",
        "critico",
        re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    ),
    (
        "jwt",
        "alto",
        re.compile(
            r"eyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}"
        ),
    ),
    (
        "pem_private_key",
        "critico",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"),
    ),
    (
        "github_token",
        "critico",
        re.compile(r"(?:gh[opsur]_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{22,})"),
    ),
    (
        "bearer_token",
        "alto",
        re.compile(r"(?i)bearer\s+[0-9A-Za-z._\-]{20,}"),
    ),
    # Anthropic comes before OpenAI: 'sk-ant-...' would also match the OpenAI pattern.
    (
        "anthropic_api_key",
        "critico",
        re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{20,}"),
    ),
    (
        "openai_api_key",
        "critico",
        # alphanumeric body (no '-') so we do not match hyphenated slugs; excludes ant-.
        re.compile(r"\bsk-(?!ant-)(?:proj-)?[0-9A-Za-z]{20,}"),
    ),
    (
        "stripe_secret_key",
        "critico",
        re.compile(r"\bsk_(?:live|test)_[0-9A-Za-z]{16,}"),
    ),
    # Credential embedded in a connection URL: a user and password before the "@" (finding 8).
    (
        "connection_string_credential",
        "critico",
        re.compile(r"\b[a-z][a-z0-9+.\-]{1,}://[^\s:/@]{1,}:[^\s:/@]{3,}@"),
    ),
]

# Identifier on the left of the assignment + (optional quote) + delimiter +
# value. Accepts the FULL identifier (e.g. MY_PASSWORD, db_password,
# AWS_SECRET_ACCESS_KEY) and the quoted JSON/YAML key ("password": ...).
# The "is it a credential?" decision is made by testing a keyword in the name
# (below): '\b' next to '_' let MY_PASSWORD= escape (finding 5) and the closing
# quote broke the match of "password": ... (finding 6).
_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<name>[A-Za-z][A-Za-z0-9_.\-]*)   # left-hand identifier
    ['"]?\s*[:=]\s*                        # optional closing quote + delimiter
    ['"]?(?P<value>[^\s'"]+)               # optional opening quote + value
    """
)
_CREDENTIAL_KEYWORD_RE = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|senha|password|passwd|pwd|"
    r"client[_-]?secret|refresh[_-]?token|access[_-]?key|private[_-]?key)"
)

# Entropy thresholds for the generic assignment rule. Tuned so random hex/base64
# blobs trip the rule but ordinary words/sentences do not.
_MIN_VALUE_LEN = 16
_MIN_ENTROPY_BITS_PER_CHAR = 3.0

# The value of a generic credential is a TOKEN: alphanumeric + base64url (no
# '.', '/', parentheses, spaces). This rejects code (e.g. `overlap_tokens =
# int(config.llm.get(`) and paths (`/Users/...`), which have 'token'/'key' in the
# name but a value that is not a secret. Tokens with '.'/'/' (JWT, bearer) have
# their own dedicated pattern.
_TOKEN_LIKE_RE = re.compile(r"[A-Za-z0-9_\-+=]+")


def _shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character."""
    if not value:
        return 0.0
    length = len(value)
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def _looks_random(value: str) -> bool:
    """Heuristic: long enough and high enough entropy to be a real secret."""
    if len(value) < _MIN_VALUE_LEN:
        return False
    return _shannon_entropy(value) > _MIN_ENTROPY_BITS_PER_CHAR


# --------------------------------------------------------------------------- #
# Credential-file SHAPE detection.
#
# The content-based rules above match on the *value* (a high-entropy token, a
# PEM header, a provider prefix). They miss a whole class of leak: a Google
# credential FILE committed wholesale. ``credentials.json`` / ``token.json``
# were the real gap in this repo's history. We catch them by their structural
# shape -- the diagnostic SET of keys -- rather than by any single value, so a
# leak is flagged even when the embedded token is short or low-entropy.
#
# Two shapes:
#   * Google service-account key: a JSON object whose ``type`` is
#     ``"service_account"`` together with a ``private_key`` and ``client_email``.
#   * OAuth client/token: a JSON object carrying OAuth credential material --
#     ``refresh_token`` / ``access_token`` / ``client_secret`` (with the
#     companion ``client_id``). ``token.json`` and ``client_secret_*.json``.
# --------------------------------------------------------------------------- #

_SERVICE_ACCOUNT_TYPE = "service_account"
# Service-account shape: the literal type marker plus the two fields that make
# it a usable key. All three required so an unrelated {"type": ...} does not fire.
_SERVICE_ACCOUNT_KEYS = ("private_key", "client_email")

# OAuth credential material. ``client_secret`` alone is enough; the live tokens
# (refresh/access) require the ``client_id`` companion so a bare {"access_token":
# "<short>"} from unrelated APIs is less likely to false-positive. Tuned for the
# google-auth ``token.json`` / ``client_secret_*.json`` shapes.
_OAUTH_STRONG_KEYS = ("client_secret",)
_OAUTH_TOKEN_KEYS = ("refresh_token", "access_token")

# Fallback for malformed / partial JSON (truncated paste, trailing comma): the
# key names still betray the shape. Quote-delimited so we match the JSON key,
# not an English sentence that happens to contain the word.
_SERVICE_ACCOUNT_TYPE_RE = re.compile(
    r'"type"\s*:\s*"service_account"'
)
_KEY_PRESENT_RE = {
    key: re.compile(r'"' + re.escape(key) + r'"\s*:')
    for key in (
        "private_key",
        "client_email",
        "client_secret",
        "client_id",
        "refresh_token",
        "access_token",
    )
}


def _redacted_shape_excerpt(kind: str, keys: tuple[str, ...]) -> str:
    """A safe, value-free description of the credential file shape.

    Never echoes any field value -- only the kind and the diagnostic key names,
    so the finding stays shareable.
    """
    return f"{kind}{{{', '.join(keys)}}}"


def _scan_credential_file_shape(text: str) -> list[Finding]:
    """Detect whole Google credential files by their JSON shape.

    Parses ``text`` as JSON when possible; otherwise falls back to quoted-key
    presence so a truncated paste is still caught. At most one finding per shape
    -- excerpts are value-free.
    """
    findings: list[Finding] = []

    obj: object | None
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        obj = None

    present: set[str]
    is_service_account: bool
    if isinstance(obj, dict):
        keys = {k for k in obj if isinstance(k, str)}
        present = keys
        is_service_account = obj.get("type") == _SERVICE_ACCOUNT_TYPE
    else:
        # Fallback: scan the raw text for quoted JSON keys / the type marker.
        present = {
            key for key, pat in _KEY_PRESENT_RE.items() if pat.search(text)
        }
        is_service_account = bool(_SERVICE_ACCOUNT_TYPE_RE.search(text))

    if is_service_account and all(k in present for k in _SERVICE_ACCOUNT_KEYS):
        matched = ("type=service_account", *_SERVICE_ACCOUNT_KEYS)
        findings.append(
            Finding(
                kind="google_service_account_key",
                category=_CATEGORY,
                severity="critico",
                line=1,
                excerpt=_redacted_shape_excerpt(
                    "google_service_account_key", matched
                ),
                detector=_DETECTOR,
            )
        )

    has_strong = any(k in present for k in _OAUTH_STRONG_KEYS)
    has_live_token = any(k in present for k in _OAUTH_TOKEN_KEYS)
    has_client_id = "client_id" in present
    if has_strong or (has_live_token and has_client_id):
        matched = tuple(
            k
            for k in (
                "client_id",
                "client_secret",
                "refresh_token",
                "access_token",
            )
            if k in present
        )
        findings.append(
            Finding(
                kind="google_oauth_credentials",
                category=_CATEGORY,
                severity="critico",
                line=1,
                excerpt=_redacted_shape_excerpt(
                    "google_oauth_credentials", matched
                ),
                detector=_DETECTOR,
            )
        )

    return findings


# --------------------------------------------------------------------------- #
# Short-lived access codes and hash-configuration secrets (issue #524).
#
# Invite codes, verification/one-time codes and pairing codes grant access even
# though they are short and low-entropy, so the generic entropy rule misses
# them. Identity-provider hash configurations (for example an auth project's
# `hashConfig`) carry a signer key and salt separator that let an attacker
# verify exported password hashes. Every excerpt here is fully masked: a short
# code would otherwise survive `redact`'s visible edges.
# --------------------------------------------------------------------------- #

_CODE_VALUE = r"(?P<value>[A-Za-z0-9][A-Za-z0-9_\-]{3,127})"
_ACCESS_CODE_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9])
    ['"]?(?P<name>
        (?:invit(?:e|ation)|verif(?:y|ication)|confirm(?:ation)?|pairing|one[_-]?time|otp|mfa|2fa)
        [_-]?(?:code|token|pin|key)
      | otp
    )['"]?
    \s*[:=]\s*['"]?""" + _CODE_VALUE
)
# Prose forms in the languages the kit ships (en/pt/es): an English
# "verification code" phrase, a Portuguese "código de verificação" phrase or a
# Spanish "código de invitación" phrase followed by the code itself.
_ACCESS_CODE_PROSE_RE = re.compile(
    r"""(?ix)
    \b(?:
        (?:invite|invitation|verification|confirmation|pairing|one[- ]time|sign[- ]in|login)\s+code
      | c[oó]digo\s+de\s+(?:verifica[cç][aã]o|verificaci[oó]n|convite|invitaci[oó]n|confirma[cç][aã]o|confirmaci[oó]n|pareamento|acesso|acceso)
    )
    \s*(?:is|é|es|[:=#-])?\s*['"`]?""" + _CODE_VALUE
)
# Individualized invite/verification links: a path segment or query value that
# carries the code itself.
_ACCESS_CODE_URL_RE = re.compile(
    r"""(?ix)
    https?://[^\s<>"')\]]*?
    (?:
        /(?:invite|invites|invitation|invitations|join|verify|verification|confirm)/(?P<path>[A-Za-z0-9_\-]{8,})
      | [?&](?:invite(?:_code)?|invitation|invite_token|verification_code|otp|code)=(?P<query>[A-Za-z0-9_\-]{6,})
    )
    """
)
# Hash-configuration secret fields (JSON, YAML or assignment form).
_HASH_CONFIG_FIELD_RE = re.compile(
    r"""(?ix)
    ['"]?(?P<name>signer[_-]?key|salt[_-]?separator|base64[_-]?signer[_-]?key|base64[_-]?salt[_-]?separator)['"]?
    \s*[:=]\s*['"]?(?P<value>[A-Za-z0-9+/_\-]{2,}={0,2})
    """
)


def _code_like(value: str) -> bool:
    """A real code mixes digits, or cases, and is not a placeholder word."""
    if value.lower() in {"none", "null", "redacted", "example", "placeholder", "xxxx", "xxxxxx"}:
        return False
    if set(value) <= {"x", "X", "*", "-", "_", "0"}:
        return False
    has_digit = any(c.isdigit() for c in value)
    mixed_case = any(c.islower() for c in value) and any(c.isupper() for c in value)
    return has_digit or mixed_case


def _hash_config_value(value: str) -> bool:
    """Base64 material: padded, or long and random; never a bare word."""
    if value.lower() in {"none", "null", "redacted", "example", "placeholder"}:
        return False
    if value.endswith("=") and len(value) >= 4:
        return True
    return len(value) >= 16 and _shannon_entropy(value) > _MIN_ENTROPY_BITS_PER_CHAR


def _masked(kind: str, value: str) -> str:
    return f"{kind}:{'*' * min(len(value), 12)}"


def _scan_access_codes(text: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[int] = set()

    def add(kind: str, severity: str, start: int, value: str) -> None:
        if start in seen:
            return
        seen.add(start)
        findings.append(Finding(kind=kind, category=_CATEGORY, severity=severity,
                                line=line_of(text, start), excerpt=_masked(kind, value),
                                detector=_DETECTOR))

    for match in _ACCESS_CODE_ASSIGNMENT_RE.finditer(text):
        if _code_like(match.group("value")):
            add("access_code", "alto", match.start("value"), match.group("value"))
    # Prose is followed by ordinary capitalized words ("access code DocuSign"):
    # only a value with a digit counts there.
    for match in _ACCESS_CODE_PROSE_RE.finditer(text):
        value = match.group("value")
        if _code_like(value) and any(c.isdigit() for c in value):
            add("access_code", "alto", match.start("value"), value)
    for match in _ACCESS_CODE_URL_RE.finditer(text):
        group = "path" if match.group("path") else "query"
        value = match.group(group)
        if _code_like(value):
            add("individualized_access_link", "alto", match.start(group), value)
    for match in _HASH_CONFIG_FIELD_RE.finditer(text):
        if _hash_config_value(match.group("value")):
            add("hash_config_secret", "critico", match.start("value"), match.group("value"))
    return findings


def scan_secrets(text: str) -> list[Finding]:
    """Detect credential-shaped secrets in ``text``."""
    findings: list[Finding] = []

    for kind, severity, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    kind=kind,
                    category=_CATEGORY,
                    severity=severity,
                    line=line_of(text, match.start()),
                    excerpt=redact(match.group(0)),
                    detector=_DETECTOR,
                )
            )

    for match in _ASSIGNMENT_RE.finditer(text):
        name = match.group("name")
        if not _CREDENTIAL_KEYWORD_RE.search(name):
            continue
        value = match.group("value")
        if not _TOKEN_LIKE_RE.fullmatch(value):
            continue
        if not _looks_random(value):
            continue
        findings.append(
            Finding(
                kind="generic_secret_assignment",
                category=_CATEGORY,
                severity="alto",
                line=line_of(text, match.start("value")),
                excerpt=redact(value),
                detector=_DETECTOR,
            )
        )

    findings.extend(_scan_credential_file_shape(text))
    findings.extend(_scan_access_codes(text))

    return findings


__all__ = ["scan_secrets"]
