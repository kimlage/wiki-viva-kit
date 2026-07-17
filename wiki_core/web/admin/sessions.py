"""Local admin sessions (god-mode plan §7.1, §13, PR3).

The local adapter is deliberately humble: physical access to the process
terminal IS the credential. At startup the manager prints one short,
single-use, expiring unlock code to the server's stdout — never to a file,
response or log. Unlocking requires that code plus a fresh server-issued
challenge nonce, and every comparison is constant-time. The resulting
session is a random opaque token that lives only in this process's memory,
keyed to a per-process instance id, so a restart structurally revokes
everything (threat 14). Tokens are stored as digests: even this module
cannot reproduce a session token after handing it to the caller once.

Composition rule (plan §13.1 step 10, threat 13): the session header is
validated ON TOP OF the operator-security v2 nonce + attempt-key flow —
the server rejects the POST before this module ever sees it if those are
missing. Nothing here reads or writes disk, URLs or the snapshot; the
token can therefore never leak through them (threat 3).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from wiki_core.config import WikiConfig

# The session header composes with (never replaces) the operator nonce and
# attempt-key headers on every admin mutation.
ADMIN_SESSION_HEADER = "X-Wiki-Admin-Session"

# A printed code is worthless after this window; restart the process (or lock
# the session, which re-arms a fresh code) to get a new one.
UNLOCK_CODE_TTL_S = 900
# An unlock attempt must follow its challenge quickly (anti-replay, §13.1).
CHALLENGE_TTL_S = 120
MAX_PENDING_CHALLENGES = 16
# Per-process rate limits (plan §13.4): local adapter, local counters.
UNLOCK_ATTEMPT_LIMIT = 5
UNLOCK_ATTEMPT_WINDOW_S = 300
RENEW_ATTEMPT_LIMIT = 30
RENEW_ATTEMPT_WINDOW_S = 60
# A session this close to its TTL reports the "expiring" visual state (§6.3).
SESSION_EXPIRING_THRESHOLD_S = 120

# Human-friendly alphabet: no 0/O, 1/I/L ambiguity on a terminal font.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_CODE_LENGTH = 8

# Closed error vocabulary. Code failures share ONE code on purpose: a wrong,
# consumed and expired code are indistinguishable to the caller, so the
# endpoint is not an oracle for which guess was "close".
ERROR_ADMIN_DISABLED = "admin_disabled"
ERROR_RATE_LIMITED = "admin_rate_limited"
ERROR_CHALLENGE_REJECTED = "admin_challenge_rejected"
ERROR_CODE_REJECTED = "admin_unlock_code_rejected"
ERROR_SESSION_INVALID = "admin_session_invalid"
ERROR_SESSION_EXPIRED = "admin_session_expired"

# Role -> base visual state (plan §6.3, §8.3). The full-role labels only ever
# come from the server; the frontend renders what it is told.
_ROLE_STATES = {
    "observer": "active_readonly",
    "operator": "active_partial",
    "maintainer": "active_partial",
    "publisher": "active_partial",
    "admin": "active_full",
    "rescue_admin": "active_full",
}


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _digest_code(code: str) -> bytes:
    # Typing "ABCD-2345", "abcd 2345" or "ABCD2345" all mean the same code:
    # only the alphabet characters count, case-insensitively.
    normalized = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return _digest(normalized)


def _new_unlock_code() -> str:
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def _print_stdout(line: str) -> None:
    # The ONLY sink for the unlock code: the local process stdout (§13.1).
    print(line, flush=True)


@dataclass
class _Session:
    session_id: str
    token_digest: bytes
    role: str
    created: float
    last_seen: float
    expires: float
    instance_id: str


@dataclass
class _RateWindow:
    limit: int
    window_s: float
    events: deque = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        while self.events and now - self.events[0] > self.window_s:
            self.events.popleft()
        if len(self.events) >= self.limit:
            return False
        self.events.append(now)
        return True


class AdminSessionManager:
    """One in-memory session store per operator process.

    Every public method is thread-safe and returns a plain dict with an
    ``ok`` flag and, on failure, a typed ``error_code`` — never the supplied
    code, never a stored token, never an internal digest.
    """

    def __init__(
        self,
        config: WikiConfig,
        *,
        announce: Callable[[str], None] | None = None,
    ) -> None:
        self.enabled = (
            config.admin_enabled
            and str(config.admin.get("local_unlock") or "") == "startup_code"
        )
        # Sessions are keyed to this process instance: a restart creates a new
        # instance id and an empty store, so no token survives it (threat 14).
        self.instance_id = secrets.token_urlsafe(12)
        self.session_ttl_s = (
            int(config.admin.get("session_ttl_minutes") or 15) * 60
        )
        self.idle_lock_s = int(config.admin.get("idle_lock_minutes") or 5) * 60
        self.default_role = str(config.admin.get("default_role") or "admin")
        # Test seam: a monotonic clock the suite can replace to step time.
        self.clock: Callable[[], float] = time.monotonic
        self._lock = threading.Lock()
        self._announce = announce or _print_stdout
        self._code_digest: bytes | None = None
        self._code_issued: float | None = None
        self._code_consumed = False
        self._challenges: OrderedDict[str, float] = OrderedDict()
        self._session: _Session | None = None
        self._unlock_rate = _RateWindow(UNLOCK_ATTEMPT_LIMIT, UNLOCK_ATTEMPT_WINDOW_S)
        self._renew_rate = _RateWindow(RENEW_ATTEMPT_LIMIT, RENEW_ATTEMPT_WINDOW_S)
        if self.enabled:
            self.arm()

    # ------------------------------------------------------------------
    # unlock code lifecycle
    # ------------------------------------------------------------------

    def arm(self, announce: Callable[[str], None] | None = None) -> None:
        """Issue a fresh single-use unlock code and announce it.

        Called at construction, and again whenever a session ends (lock or
        expiry) so the local owner can unlock again without a restart. The
        plaintext code exists only inside this call frame; the manager keeps
        a digest.
        """

        if not self.enabled:
            return
        if announce is not None:
            self._announce = announce
        code = _new_unlock_code()
        with self._lock:
            self._code_digest = _digest_code(code)
            self._code_issued = self.clock()
            self._code_consumed = False
        self._announce(
            f"[wiki-admin] one-time unlock code: {code} "
            f"(valid {UNLOCK_CODE_TTL_S // 60} min, single use, this terminal only)"
        )

    # ------------------------------------------------------------------
    # challenge -> unlock -> session
    # ------------------------------------------------------------------

    def issue_challenge(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error_code": ERROR_ADMIN_DISABLED}
        now = self.clock()
        with self._lock:
            for key in [
                k for k, issued in self._challenges.items()
                if now - issued > CHALLENGE_TTL_S
            ]:
                del self._challenges[key]
            while len(self._challenges) >= MAX_PENDING_CHALLENGES:
                self._challenges.popitem(last=False)
            challenge = secrets.token_urlsafe(24)
            self._challenges[challenge] = now
        return {
            "ok": True,
            "challenge": challenge,
            "expires_in_s": CHALLENGE_TTL_S,
        }

    def unlock(self, *, code: str, challenge: str) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error_code": ERROR_ADMIN_DISABLED}
        now = self.clock()
        with self._lock:
            # Every attempt (right or wrong) consumes rate budget, so a guess
            # stream cannot ride along with legitimate retries (§13.4).
            if not self._unlock_rate.allow(now):
                return {"ok": False, "error_code": ERROR_RATE_LIMITED}
            issued = self._challenges.pop(str(challenge or ""), None)
            if issued is None or now - issued > CHALLENGE_TTL_S:
                return {"ok": False, "error_code": ERROR_CHALLENGE_REJECTED}
            supplied = _digest_code(code)
            expected = self._code_digest or _digest("")
            code_matches = hmac.compare_digest(supplied, expected)
            code_alive = (
                self._code_digest is not None
                and not self._code_consumed
                and self._code_issued is not None
                and now - self._code_issued <= UNLOCK_CODE_TTL_S
            )
            if not (code_matches and code_alive):
                return {"ok": False, "error_code": ERROR_CODE_REJECTED}
            # Success: the code is consumed forever (single use) and any prior
            # session is replaced — one local owner, one session.
            self._code_consumed = True
            token = secrets.token_urlsafe(32)
            self._session = _Session(
                session_id=f"session_{secrets.token_hex(8)}",
                token_digest=_digest(token),
                role=self.default_role,
                created=now,
                last_seen=now,
                expires=now + self.session_ttl_s,
                instance_id=self.instance_id,
            )
            described = self._describe_locked(now)
        return {"ok": True, "token": token, "session": described}

    # ------------------------------------------------------------------
    # validation / renew / lock
    # ------------------------------------------------------------------

    def _describe_locked(self, now: float) -> dict[str, Any]:
        session = self._session
        assert session is not None
        expires_in = max(int(session.expires - now), 0)
        idle_remaining = max(
            int(session.last_seen + self.idle_lock_s - now), 0
        )
        state = _ROLE_STATES.get(session.role, "active_partial")
        if expires_in <= SESSION_EXPIRING_THRESHOLD_S:
            state = "expiring"
        return {
            "session_id": session.session_id,
            "role": session.role,
            "state": state,
            "expires_in_s": expires_in,
            "idle_remaining_s": idle_remaining,
            "ttl_s": self.session_ttl_s,
            "idle_lock_s": self.idle_lock_s,
        }

    def _validate_locked(
        self, token: str, now: float, *, touch: bool
    ) -> dict[str, Any]:
        session = self._session
        supplied = _digest(str(token or ""))
        if session is None:
            # Compare against a throwaway digest so a missing session costs
            # the same time as a wrong token.
            hmac.compare_digest(supplied, _digest(""))
            return {"ok": False, "error_code": ERROR_SESSION_INVALID}
        if not hmac.compare_digest(supplied, session.token_digest):
            return {"ok": False, "error_code": ERROR_SESSION_INVALID}
        if session.instance_id != self.instance_id:
            return {"ok": False, "error_code": ERROR_SESSION_INVALID}
        if now >= session.expires or now - session.last_seen >= self.idle_lock_s:
            # Server-side expiry (TTL or idle). The dead session is removed
            # immediately; the caller re-arms a fresh unlock code after
            # releasing the lock.
            self._session = None
            return {
                "ok": False,
                "error_code": ERROR_SESSION_EXPIRED,
                "rearm": True,
            }
        if touch:
            session.last_seen = now
        return {"ok": True, **self._describe_locked(now)}

    def _after_validation(self, result: dict[str, Any]) -> dict[str, Any]:
        if result.pop("rearm", False):
            self.arm()
        return result

    def validate(self, token: str, *, touch: bool = True) -> dict[str, Any]:
        """Validate a session header value; ``touch`` feeds the idle timer."""

        now = self.clock()
        with self._lock:
            result = self._validate_locked(token, now, touch=touch)
        return self._after_validation(result)

    def session_for_capabilities(self, token: str) -> dict[str, Any] | None:
        """Session description for GET discovery, or None when locked.

        Deliberately touch-free: polling the capabilities endpoint must not
        keep an abandoned session alive past its idle lock.
        """

        if not token:
            return None
        result = self.validate(token, touch=False)
        return result if result.get("ok") else None

    def renew(self, token: str) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error_code": ERROR_ADMIN_DISABLED}
        now = self.clock()
        with self._lock:
            if not self._renew_rate.allow(now):
                return {"ok": False, "error_code": ERROR_RATE_LIMITED}
            result = self._validate_locked(token, now, touch=True)
            if not result.get("ok"):
                out = result
            else:
                session = self._session
                assert session is not None
                # Rotation: the old token dies here, a new opaque token is
                # the only way to continue (plan §13.2).
                new_token = secrets.token_urlsafe(32)
                session.token_digest = _digest(new_token)
                session.expires = now + self.session_ttl_s
                session.last_seen = now
                out = {
                    "ok": True,
                    "token": new_token,
                    "session": self._describe_locked(now),
                }
        return self._after_validation(out)

    def lock(self, token: str) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error_code": ERROR_ADMIN_DISABLED}
        now = self.clock()
        rearm_after_lock = False
        with self._lock:
            result = self._validate_locked(token, now, touch=False)
            if not result.get("ok"):
                out = result
            else:
                self._session = None
                rearm_after_lock = True
                out = {
                    "ok": True,
                    "session_id": result["session_id"],
                    "state": "locked",
                }
        out = self._after_validation(out)
        if rearm_after_lock:
            # A deliberate lock re-arms a fresh code so the owner can come
            # back without restarting the process (§5.4).
            self.arm()
        return out
