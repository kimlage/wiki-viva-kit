"""Strict, secret-free local runtime route configuration; disabled by default."""
from pathlib import Path
import re
from urllib.parse import urlsplit

class RuntimeErrorCode(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(test, code):
    if not test:
        raise RuntimeErrorCode(code)


def validated_config(value):
    if value is None:
        return {"enabled": False}
    require(isinstance(value, dict), "openclaw_invalid_config")
    fields = {"enabled", "node_binary", "entrypoint", "profile", "state_dir", "gateway", "routes"}
    optional = {"mission_options", "recovery", "recurring"}
    require(not set(value) - fields - optional and isinstance(value.get("enabled", False), bool), "openclaw_invalid_config")
    if not value.get("enabled"):
        require(set(value) <= {"enabled"}, "openclaw_disabled_config_has_settings")
        return {"enabled": False}
    require(set(value) - optional == fields, "openclaw_incomplete_config")
    if "recovery" in value:
        require(value["recovery"] == {"mode": "read_only", "max_continuations": 1}
                and type(value["recovery"].get("max_continuations")) is int,
                "openclaw_invalid_recovery_policy")
    for key in fields - {"enabled", "routes"}:
        require(isinstance(value[key], str) and 0 < len(value[key]) < 1024
                and not any(ord(c) < 32 for c in value[key]), "openclaw_invalid_config")
    for key in ("node_binary", "entrypoint", "state_dir"):
        require(Path(value[key]).expanduser().is_absolute(), "openclaw_absolute_path_required")
    url = urlsplit(value["gateway"])
    require(url.scheme == "ws" and url.hostname in {"127.0.0.1", "::1"}
            and not url.username and not url.password and not url.query and not url.fragment
            and url.path in {"", "/"} and url.port is not None, "openclaw_local_gateway_required")
    require(bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value["profile"])), "openclaw_invalid_profile")
    require(isinstance(value["routes"], dict) and bool(value["routes"]), "openclaw_routes_required")
    for profile, route in value["routes"].items():
        require(isinstance(profile, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile)
                and isinstance(route, dict) and set(route) - {"native_thread_id", "native_thread_binding"} == {"session_key", "session_id", "label"}, "openclaw_invalid_route")
        require("native_thread_binding" not in route or
                route["native_thread_binding"] == "first_turn" and "native_thread_id" not in route,
                "openclaw_invalid_route")
        require(all(isinstance(v, str) and 0 < len(v) <= 240 and not any(ord(c) < 32 for c in v)
                    for v in route.values()), "openclaw_invalid_route")
    options = value.get("mission_options", {})
    require(isinstance(options, dict), "openclaw_invalid_mission_policy")
    for key, option in options.items():
        require(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key)
                and isinstance(option, dict) and set(option) == {"label", "model", "effort"}
                and all(isinstance(v, str) for v in option.values())
                and 0 < len(option["label"]) < 120 and not any(ord(c) < 32 for c in option["label"])
                and re.fullmatch(r"openai/[a-zA-Z0-9._-]+", option["model"])
                and option["effort"] in {"high", "max"}, "openclaw_invalid_mission_policy")
    recurring = value.get("recurring", {})
    require(isinstance(recurring, dict) and len(recurring) <= 8, "openclaw_invalid_recurring_policy")
    for key, rule in recurring.items():
        require(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key)
                and isinstance(rule, dict) and set(rule) == {"profile", "action_id", "mission_id", "message", "interval_minutes", "watch_paths"}
                and rule["profile"] in value["routes"] and rule["mission_id"] in options
                and isinstance(rule["action_id"], str) and re.fullmatch(r"[a-z0-9_-]+", rule["action_id"])
                and type(rule["interval_minutes"]) is int and 10 <= rule["interval_minutes"] <= 10080
                and isinstance(rule["message"], str) and 0 < len(rule["message"]) <= 10000
                and isinstance(rule["watch_paths"], list) and 0 < len(rule["watch_paths"]) <= 32
                and all(isinstance(p, str) and p and not Path(p).is_absolute() and ".." not in Path(p).parts
                        for p in rule["watch_paths"]), "openclaw_invalid_recurring_policy")
    return value
