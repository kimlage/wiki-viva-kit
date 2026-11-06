"""Stable, per-source namespaces for protected ingestion artifacts.

The namespace is a routing convention, not an access grant or a filesystem
ACL. The caller must authorize both actors, the source and every artifact and
recheck those authorities around I/O.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from wiki_core.context_policy import safe_path
from wiki_core.repository_reader import canonical_path
from wiki_core.traversal import is_protected_artifact

_NAMESPACE = 'by-source-v1'


def _context_path(value: str) -> str:
    value = safe_path(value, allow_root=True)
    if value != '.':
        canonical_path(value)
        if is_protected_artifact(Path(value)):
            raise ValueError('protected cache context unavailable')
    return value


def _source_path(value: str) -> str:
    value = safe_path(value)
    canonical_path(value)
    if is_protected_artifact(Path(value)):
        raise ValueError('protected cache source unavailable')
    return value


def partition_component(context_id: str, integrator_context: str, source_ref: str) -> str:
    """Return a stable relative component; does not read paths or grant access.

    The approved-policy revision and source contents are intentionally absent:
    an operator can authorize this literal namespace before policy approval.
    Canonical JSON avoids ambiguity between the three separate fields.
    """
    payload = {
        'context_id': _context_path(context_id),
        'integrator_context': _context_path(integrator_context),
        'source_ref': _source_path(source_ref),
        'version': 1,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return _NAMESPACE + '/' + hashlib.sha256(encoded).hexdigest()
