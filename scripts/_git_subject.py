"""Compatibility loader for the standard-library-only Git subject helper.

The cockpit's Node-only job invokes a Python script without installing the
full wiki runtime. Load the portable implementation by file path so importing
this compatibility module does not execute ``wiki_core.__init__``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


_IMPLEMENTATION = Path(__file__).resolve().parents[1] / "wiki_core" / "git_subject.py"
_SPEC = importlib.util.spec_from_file_location("_wiki_git_subject_core", _IMPLEMENTATION)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - defensive runtime guard
    raise ImportError("could not load wiki_core/git_subject.py")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

FINGERPRINT_VERSION = _MODULE.FINGERPRINT_VERSION
GitSubjectError = _MODULE.GitSubjectError
collect_git_subject = _MODULE.collect_git_subject

__all__ = [
    "FINGERPRINT_VERSION",
    "GitSubjectError",
    "collect_git_subject",
]
