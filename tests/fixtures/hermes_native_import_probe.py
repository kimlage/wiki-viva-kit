"""Isolated full-module import probe; only dependency boundaries are fictitious.

The parent copies pinned public source into a disposable tree. This process
never adds the installed Hermes tree to sys.path, inherits no account env, and
refuses network/process launch. Native startup/env/plugin bodies are untouched.
"""
from contextlib import nullcontext
import importlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent
NATIVE_HOME = Path(os.environ["HERMES_HOME"])
CASE = os.environ["WIKI_IMPORT_CASE"]
CHANNEL = os.environ.get("HERMES_WIKI_NATIVE_CHANNEL")
events = []
config = {"secrets": {"synthetic-source": {"enabled": True}},
          "mcp_servers": {"synthetic-native": {"command": "NEVER-EXECUTED"}}}


def audit(name, args):
    if name == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0]))
        if path.name in {".env", ".op.env"}:
            assert path.is_relative_to(ROOT), "nonfixture env read"
            events.append("dotenv:" + path.name)
        if path.name == ".hermes-update-zip-swap":
            events.append("native-recovery-journal")
        if path.name == "wiki_native_startup_guard.py":
            events.append("startup-guard-read")
    if name == "os.rename" and any(".hermes-update-old" in str(value) for value in args[:2]):
        events.append("native-recovery-rename")
    if name == "socket.connect":
        assert isinstance(args[1], str) and args[1] == CHANNEL, "nonfixture transport"
    if name in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
        raise AssertionError("unexpected external process")


sys.addaudithook(audit)
sys.argv = ["hermes", "--cli", "chat", "-q", "public synthetic question"]


class Empty:
    def __call__(self, *a, **kw): return self
    def __getattr__(self, name): return self
    def __bool__(self): return False
    def __iter__(self): return iter(())
    def __len__(self): return 0
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def __getitem__(self, key): return self
    def __or__(self, other): return self
    def __ror__(self, other): return self


def fake_module(name, **values):
    module = ModuleType(name)
    module.__path__ = [str(ROOT / name.replace(".", "/"))]
    module.__dict__.update(values)
    def missing(attr):
        if attr.startswith("__"): raise AttributeError(attr)
        if attr.endswith("Mixin"): return type(attr, (), {})
        if attr in {"_serialized_replacement", "replacement_coordinator"}:
            return lambda fn: fn
        if attr.endswith(("_CAP", "_CHARS", "_SECS", "_SECONDS")): return 10
        if attr.isupper(): return set()
        return Empty()
    module.__getattr__ = missing
    sys.modules[name] = module
    return module


fake_module("hermes_constants", get_hermes_home=lambda: NATIVE_HOME,
    get_process_hermes_home=lambda: NATIVE_HOME, get_hermes_home_override=lambda: None,
    get_default_hermes_root=lambda: NATIVE_HOME,
    get_routing_process_hermes_home=lambda: NATIVE_HOME, hermes_home_key=lambda *a: str(NATIVE_HOME),
    export_scratch_tmp_env=lambda: None)
fake_module("utils", atomic_replace=lambda *a: None, mkstemp_beside=lambda *a, **kw: None,
    load_yaml_file_readonly=lambda *a: config, env_var_enabled=lambda *a: False,
    file_signature=lambda p: (str(p), 1))
fake_module("hermes_cli.config", get_hermes_home=lambda: NATIVE_HOME, load_config=lambda: config,
    load_config_readonly=lambda: config, read_raw_config=lambda: config)
fake_module("hermes_cli.config_effective", load_user_config_effective=lambda *a: config)
fake_module("hermes_cli._early_recovery", restore_interrupted_pull=lambda *a: False,
    recover_if_needed=lambda *a: None, _should_skip_external_secret_sources=lambda: False)
fake_module("hermes_cli._startup_fast", normalize_hermes_home_env=lambda: None,
    try_fast_version=lambda: False, project_root_str=lambda: str(ROOT),
    ensure_project_root_on_path=lambda: None)
fake_module("hermes_cli.venv_sync", prepare_launch=lambda *a: None)
fake_module("hermes_cli.managed_scope", get_managed_dir=lambda: None)
fake_module("hermes_cli._parser", command_argv=lambda argv: ["chat"],
    top_level_value_flag_sets=lambda: (set(), set()))
fake_module("pm.environments", activate_dependencies=lambda *a: None,
    install_state_permission_message=lambda *a: None,
    install_state_dir=lambda *a: ROOT / ".fixture-install-state")
fake_module("hermes_cli.plugins_loader", PluginLoaderMixin=type("Loader", (), {}),
    _plugin_home_scope=lambda *a: nullcontext(), _serialized_replacement=lambda fn: fn,
    in_plugin_load_worker=lambda: False)
fake_module("hermes_cli.plugins_dispatch", PluginDispatchMixin=type("Dispatch", (), {}))
fake_module("hermes_cli.plugins_ledger", PluginLedgerMixin=type("Ledger", (), {}))
fake_module("hermes_cli.plugins_discovery", plugin_discovery_suppressed=lambda: False,
    collect_directory_manifests=lambda *a, **kw: [], discover_entrypoint_manifests=lambda *a, **kw: [],
    resolve_manifest_winners=lambda *a, **kw: [])
fake_module("hermes_cli.plugins_manifest", resolve_plugin_load_order=lambda *a, **kw: [])
fake_module("hermes_cli.plugins_content", register_automation_blueprint=lambda *a, **kw: None,
    register_skill=lambda *a, **kw: None)
fake_module("tools.todo_tool", TODO_LEGACY_ALIASES=(), TODO_SCHEMA={"name": "synthetic-todo"})
fake_module("agent.secret_sources.registry", list_plugin_sources=lambda: [NS(name="synthetic-source", is_enabled=lambda c: c.get("enabled"))],
    enabled_source_names=lambda *a: {"synthetic-source"})


def apply_all(*a, **kw):
    events.append("external-source")
    target = kw.get("environ", os.environ)
    target["SYNTHETIC_EXTERNAL_MARKER"] = "fixture-only"
    return NS(sources=[NS(name="synthetic-source", label="synthetic", applied=["SYNTHETIC_EXTERNAL_MARKER"], skipped_existing=[],
        result=NS(ok=True, error=None, warnings=[], vars={}))], applied_any=True,
        provenance={"SYNTHETIC_EXTERNAL_MARKER": NS(source="synthetic-source", authoritative=True)}, conflicts=[])
sys.modules["agent.secret_sources.registry"].apply_all = apply_all


class DotEnv:
    def __init__(self, *, stream, **kw): self.stream = stream
    def parse(self):
        return [tuple(line.split("=", 1)) for line in self.stream.read().splitlines() if "=" in line]
fake_module("dotenv")
fake_module("dotenv.main", DotEnv=DotEnv)
fake_module("dotenv.variables", parse_variables=lambda value: [NS(resolve=lambda values: value)])

REAL = {"hermes_cli", "hermes_cli.main", "hermes_cli.env_loader", "hermes_cli.plugins",
    "hermes_cli.mcp_startup", "hermes_bootstrap", "hermes_state_ids", "model_tools",
    "agent.secret_scope", "tools.registry", "tools.wiki_native_startup_guard", "tools.wiki_native_host_wire",
    "tools.wiki_native_host", "tools.wiki_native_projection", "tools.wiki_authority"}
if CASE.startswith("recovery-"):
    # These are the actual canonical recovery modules, not the healthy-startup
    # fake dependency. The only replacement is the final external exec boundary.
    REAL.update({"hermes_cli._early_recovery", "hermes_cli._early_recovery_zip", "hermes_cli.update_lock"})
    sys.modules.pop("hermes_cli._early_recovery", None)
    class RecoveryRelaunch(BaseException): pass
    def external_exec_boundary(*args):
        events.append("native-relaunch-requested")
        raise RecoveryRelaunch()
    os.execv = external_exec_boundary
    # macOS native checkout custody asks ps for this fixture process's birth
    # time. Keep the real custody/lock/recovery code, fake only that OS command.
    import subprocess
    def external_process_boundary(argv, **kwargs):
        if Path(argv[0]).name == "ps" and "lstart=" in argv:
            return subprocess.CompletedProcess(argv, 0, "Wed Oct 21 12:00:00 2026\n", "")
        raise AssertionError("unexpected external recovery command")
    subprocess.run = external_process_boundary


class Dependencies(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in REAL: return None
        if fullname.startswith(("hermes_cli.", "agent.", "tools.", "pm.", "gateway.", "tui_gateway.", "rich.")) or fullname in {
                "agent", "tools", "pm", "gateway", "tui_gateway", "rich", "toolsets", "registration_lifecycle", "hermes_logging"}:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
    def create_module(self, spec): return fake_module(spec.name)
    def exec_module(self, module): pass
sys.meta_path.insert(0, Dependencies())

result = {"case": CASE, "imports": [], "events": events}
try:
    if CASE == "public-admitted":
        # Independent precondition: a real process-bound public packet is
        # admitted before full imports, without granting native account access.
        from tools.wiki_native_host_wire import bootstrap_agent
        result["pre_admitted_session"] = bootstrap_agent(None)
    for name in ("hermes_cli.main", "model_tools"):
        importlib.import_module(name)
        result["imports"].append(name)
    env = importlib.import_module("hermes_cli.env_loader")
    plugins = importlib.import_module("hermes_cli.plugins")
    # Exercise the real refresh method directly too; no manager/factory stub.
    manager = object.__new__(plugins.PluginManager)
    manager._plugin_secret_sources_reconciled = False
    before_refresh = events.count("external-source")
    manager._refresh_secret_sources_after_discovery()
    result["refresh_reapplied"] = events.count("external-source") > before_refresh
    if CASE == "public-reload":
        for key in ("HERMES_WIKI_NATIVE_CHANNEL", "HERMES_KANBAN_TASK", "HERMES_KANBAN_RUN_ID", "HERMES_KANBAN_CLAIM_LOCK"):
            os.environ.pop(key, None)
        guard = importlib.import_module("tools.wiki_native_startup_guard")
        importlib.reload(guard)
        for module in (env, plugins, sys.modules["model_tools"], sys.modules["hermes_cli.main"]):
            importlib.reload(module)
        env.load_hermes_dotenv(project_env=ROOT / ".env")
        plugins.start_background_plugin_discovery()
        manager._refresh_secret_sources_after_discovery()
    if CASE.startswith("public"):
        scope = importlib.import_module("agent.secret_scope")
        result["deep_holds"] = []
        for callback in (lambda: env._load_dotenv_with_fallback(NATIVE_HOME / ".env", override=True),
                lambda: env.hydrate_profile_secret_sources(NATIVE_HOME),
                lambda: env._apply_external_secret_sources(NATIVE_HOME),
                lambda: scope.load_env_file(NATIVE_HOME / ".env"),
                lambda: scope.refresh_installed_secret_scope(NATIVE_HOME)):
            try:
                callback()
                result["deep_holds"].append("NOT-HELD")
            except PermissionError as error:
                result["deep_holds"].append(str(error))
    startup = importlib.import_module("hermes_cli.mcp_startup")
    startup.set_mcp_server_filter("synthetic-native")
    result["filter"] = startup.get_mcp_server_filter()
    result["marker"] = os.environ.get("SYNTHETIC_IMPORT_MARKER")
    result["external_marker"] = os.environ.get("SYNTHETIC_EXTERNAL_MARKER")
    result["external_cache"] = len(env._APPLIED_HOMES)
except BaseException as error:
    import traceback
    result["trace"] = traceback.format_exc()
    result["error"] = type(error).__name__ + ":" + str(error)
print(json.dumps(result, sort_keys=True))
