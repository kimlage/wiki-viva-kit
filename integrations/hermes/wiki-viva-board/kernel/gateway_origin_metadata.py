"""Sanitized process origin metadata; never account or transport authority.

The candidate builder prepends the exact pinned native pure URL resolver in a
local environment scope. Importing the authenticated gateway module is avoided.
"""
import ipaddress
import os
import re
from urllib.parse import urlsplit

_ORIGIN_ENV_KEYS = ("CONNECTOR_GATEWAY_URL", "TOOL_GATEWAY_DOMAIN", "TOOL_GATEWAY_SCHEME")
_SCHEMA = "hermes.connector_gateway_origin.v1"


def unknown_origin(reason="gateway_origin_unknown"):
    return {"schema_version": _SCHEMA, "status": "unknown", "profile": None,
            "origin": None, "provenance": "unknown", "resolution_scope": "process",
            "reason_code": reason, "account_identity_verified": False, "account_enforced": False}


def _sanitized_origin(value):
    if type(value) is not str or not value or len(value) > 4096:
        raise ValueError("invalid origin")
    # urlsplit otherwise silently removes some controls. Reject before parsing;
    # raw URLs and parser exceptions must never become RPC errors or logs.
    if re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("invalid origin")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("invalid origin")
    authority = parsed.netloc.rsplit("@", 1)[-1]
    host = parsed.hostname
    if ":" in host:
        if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", authority):
            raise ValueError("invalid origin")
        host = str(ipaddress.IPv6Address(host))
    else:
        if not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]+)?", authority):
            raise ValueError("invalid origin")
        name = host.removesuffix(".")
        if len(name) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in name.split(".")):
            raise ValueError("invalid origin")
        if re.fullmatch(r"[0-9.]+", name):
            ipaddress.IPv4Address(name)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("invalid origin")
    return {"scheme": parsed.scheme, "host": host, "port": port}


def origin_metadata(profile, environment=None):
    """Read only three URL settings, never dotenv, config, credentials or HTTP.

    This is the resolver's process environment at observation time. It neither
    resolves a profile's secret scope nor proves the endpoint an authenticated
    operation would use after future secret hydration or an environment change.
    """
    if type(profile) is not str or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile):
        return unknown_origin("gateway_origin_profile_unknown")
    try:
        env = os.environ if environment is None else environment
        snapshot = {key: env.get(key, "") for key in _ORIGIN_ENV_KEYS}
        if any(type(value) is not str or len(value) > 4096 for value in snapshot.values()):
            return unknown_origin("gateway_origin_invalid")
        explicit = snapshot["CONNECTOR_GATEWAY_URL"].strip().rstrip("/")
        derived = snapshot["TOOL_GATEWAY_DOMAIN"].strip().strip("/") or snapshot["TOOL_GATEWAY_SCHEME"].strip()
        provenance = "override" if explicit else "derived" if derived else "default"
        origin = _sanitized_origin(_native_connector_origin(snapshot))
    except Exception:
        return unknown_origin("gateway_origin_invalid")
    return {"schema_version": _SCHEMA, "status": "known", "profile": profile,
            "origin": origin, "provenance": provenance, "resolution_scope": "process",
            "reason_code": None, "account_identity_verified": False, "account_enforced": False}
