"""Opt-in binding of operator subprocesses to installed code and content."""
from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[2]
_binding: tuple[Path, Path, tuple[int, int], str] | None = None
_lock = threading.Lock()
_legacy_sealed = False
_SCRIPTS = frozenset({
    'wiki_operation_compile.py', 'wiki_operational_pass.py', 'wiki_source_registry.py',
    'wiki_input_stage.py', 'wiki_audit.py', 'wiki_quality_report.py',
    'wiki_check_methodology_coverage.py', 'wiki_semantic_inventory.py',
    'wiki_pr_summary.py', 'wiki_page_graph.py', 'wiki_new_ingest.py',
    'wiki_ingest.py', 'wiki_llm_context_pass.py',
})
_BOOTSTRAP = r"""
import hashlib, os, runpy, sys
from pathlib import Path
code_arg, script, content_arg, dev, ino, expected = sys.argv[1:7]
code = Path(code_arg); content = Path(content_arg)
if (not code.is_absolute() or code.resolve(strict=True) != code or
    not content.is_absolute() or content.is_symlink() or content.resolve(strict=True) != content or
    os.environ.get('WIKI_INSTALLED_CONTENT_ROOT') != content_arg):
    raise SystemExit('installed_child_binding_mismatch')
st = content.stat()
if (st.st_dev, st.st_ino) != (int(dev), int(ino)):
    raise SystemExit('installed_child_binding_mismatch')
core, scripts, schemas = code/'wiki_core', code/'scripts', code/'docs/references/schemas'
if any(p.is_symlink() or not p.is_dir() for p in (core, scripts)) or schemas.is_symlink():
    raise SystemExit('installed_child_binding_mismatch')
resources = [p for p in core.rglob('*') if '__pycache__' not in p.parts and (p.is_file() or p.is_symlink())]
schema_files = [p for p in schemas.rglob('*') if p.suffix == '.json' or p.is_symlink()] if schemas.exists() else []
files = sorted([*resources, *scripts.glob('*.py'), *schema_files])
h = hashlib.sha256()
for path in files:
    if (path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != code and code in parent.parents)
        or not path.is_file() or path.resolve(strict=True) != path):
        raise SystemExit('installed_child_binding_mismatch')
    h.update(path.relative_to(code).as_posix().encode() + b'\0')
    h.update(hashlib.sha256(path.read_bytes()).digest())
if h.hexdigest() != expected:
    raise SystemExit('installed_child_binding_mismatch')
sys.path.insert(0, code_arg)
from wiki_core.web.installed_binding import restore
restore(code_arg,content_arg,int(dev),int(ino),expected)
sys.argv = [script, *sys.argv[7:]]
runpy.run_path(script, run_name='__main__')
"""


def _code_digest(code: Path) -> str:
    roots = [code / 'wiki_core', code / 'scripts']
    if any(root.is_symlink() or not root.is_dir() for root in roots):
        raise ValueError('installed_code_root_invalid')
    resources = [p for p in roots[0].rglob('*') if '__pycache__' not in p.parts and (p.is_file() or p.is_symlink())]
    schemas = code / 'docs/references/schemas'
    if schemas.is_symlink():
        raise ValueError('installed_code_symlink')
    schema_files = [p for p in schemas.rglob('*') if p.suffix == '.json' or p.is_symlink()] if schemas.exists() else []
    files = sorted([*resources, *roots[1].glob('*.py'), *schema_files])
    if any(not (roots[1] / name).is_file() for name in _SCRIPTS):
        raise ValueError('installed_code_missing')
    digest = hashlib.sha256()
    for path in files:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != code and code in parent.parents):
            raise ValueError('installed_code_symlink')
        if not path.is_file() or path.resolve(strict=True) != path:
            raise ValueError('installed_code_missing')
        digest.update(path.relative_to(code).as_posix().encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def configure(content_root: Path) -> None:
    """Explicitly opt in; roots must already exist and must be distinct."""
    global _binding
    content = Path(content_root)
    if not content.is_absolute() or content.is_symlink() or content.resolve(strict=True) != content or not content.is_dir():
        raise ValueError('installed_content_root_invalid')
    code = _CODE_ROOT
    if code == content or code in content.parents or content in code.parents:
        raise ValueError('installed_roots_not_distinct')
    st = content.stat()
    identity = (st.st_dev, st.st_ino)
    candidate = (code, content, identity, _code_digest(code))
    with _lock:
        if _legacy_sealed:
            raise ValueError("installed_mode_after_legacy_start")
        if _binding is not None and _binding != candidate:
            raise ValueError('installed_binding_already_configured')
        _binding = candidate


def restore(code: str, content: str, dev: int, ino: int, digest: str) -> None:
    """Reestablish the exact parent binding in an isolated child, never rebind."""
    global _binding
    root = Path(content)
    expected = (Path(code), root, (dev, ino), digest)
    if Path(code) != _CODE_ROOT or os.environ.get('WIKI_INSTALLED_CONTENT_ROOT') != content:
        raise ValueError('installed_child_binding_mismatch')
    if not root.is_absolute() or root.is_symlink() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError('installed_child_binding_mismatch')
    st = root.stat()
    if (st.st_dev, st.st_ino) != expected[2] or _code_digest(_CODE_ROOT) != digest:
        raise ValueError('installed_child_binding_mismatch')
    with _lock:
        if _legacy_sealed or (_binding is not None and _binding != expected):
            raise ValueError('installed_child_binding_mismatch')
        _binding = expected


def seal_legacy() -> None:
    """A started legacy server cannot switch bindings while work is in flight."""
    global _legacy_sealed
    with _lock:
        if _binding is None:
            _legacy_sealed = True


def enabled() -> bool:
    return _binding is not None


def active(root: Path) -> bool:
    if _binding is None:
        return False
    if Path(root) != _binding[1] or Path(root).is_symlink() or Path(root).resolve(strict=True) != _binding[1]:
        raise ValueError('installed_content_root_changed')
    st = Path(root).stat()
    if (st.st_dev, st.st_ino) != _binding[2]:
        raise ValueError('installed_content_root_changed')
    if _code_digest(_binding[0]) != _binding[3]:
        raise ValueError('installed_code_changed')
    return True


def command(root: Path, argv: list[str]) -> tuple[list[str], dict[str, str] | None]:
    """Translate allowlisted Python dispatch to isolated installed execution."""
    if not active(root):
        return ([sys.executable, *argv[1:]] if argv and argv[0] in {'python', 'python3'} else argv), None
    if not argv or argv[0] not in {'python', 'python3', sys.executable}:
        from wiki_core.web.commands import GIT_ALLOWED
        if argv and argv[0] == "git" and tuple(argv[1:]) in GIT_ALLOWED:
            return argv, None  # Fixed Git reads remain in the content repository.
        raise ValueError("installed_command_not_allowlisted")
    if any(part in {"--root", "--repo"} or part.startswith(("--root=", "--repo=")) for part in argv[2:]):
        raise ValueError("installed_content_override_forbidden")
    script = Path(argv[1]) if len(argv) > 1 else Path()
    if script.is_absolute() or len(script.parts) != 2 or script.parts[0] != 'scripts' or script.name not in _SCRIPTS:
        raise ValueError('installed_script_not_allowlisted')
    code, content = _binding[:2]
    candidate = code / script
    if candidate.is_symlink() or (code / 'scripts').is_symlink() or not candidate.is_file() or candidate.resolve(strict=True) != candidate:
        raise ValueError('installed_script_invalid')
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env['WIKI_INSTALLED_CONTENT_ROOT'] = str(content)
    dev, ino = _binding[2]
    return [sys.executable, '-I', '-c', _BOOTSTRAP, str(code), str(candidate), str(content), str(dev), str(ino), _binding[3], *argv[2:]], env
