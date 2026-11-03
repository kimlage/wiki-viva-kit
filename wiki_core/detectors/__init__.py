"""Reusable secret/PII/entity detectors for the living wiki.

This package centralizes detection so callers (e.g. ``scripts/wiki_audit.py``)
can import a single, well-tested surface instead of carrying ad-hoc regexes.

Public surface:

- :class:`Finding` -- frozen dataclass describing a single detection.
- :func:`scan_text` -- run every detector over a string.
- :func:`scan_file` -- read a file as text and run :func:`scan_text`.

Security note: a :class:`Finding` never carries a raw secret. The ``excerpt``
field is always redacted via :func:`redact` so logs/reports stay safe to share.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    """A single detection result.

    Attributes:
        kind: Specific detector kind, e.g. ``"aws_access_key"``, ``"cpf"``.
        category: One of ``"secret"``, ``"pii"``, ``"entity"``.
        severity: One of ``"critico"``, ``"alto"``, ``"medio"``, ``"baixo"``.
        line: 1-based line number where the match starts.
        excerpt: Always redacted -- never the full raw secret.
        detector: Source module, ``"secrets"``/``"sensitive_terms"``/``"entities"``.
    """

    kind: str
    category: str
    severity: str
    line: int
    excerpt: str
    detector: str


def redact(value: str, *, keep: int = 4) -> str:
    """Mask the middle of ``value``, keeping at most ``keep`` edge chars.

    Shows at most the first and last ``keep`` characters and replaces the
    middle with ``*``. If the value is short (``len <= keep * 2``) every
    character is masked so nothing recoverable leaks.

    Examples:
        ``redact("AKIAIOSFODNN7EXAMPLE")`` -> ``"AKIA************MPLE"``
        ``redact("short")`` -> ``"*****"``
    """
    if keep < 0:
        keep = 0
    length = len(value)
    if length == 0:
        return ""
    if length <= keep * 2:
        return "*" * length
    head = value[:keep]
    tail = value[length - keep :]
    return f"{head}{'*' * (length - keep * 2)}{tail}"


def line_of(text: str, index: int) -> int:
    """Return the 1-based line number for the character ``index`` in ``text``."""
    if index <= 0:
        return 1
    return text.count("\n", 0, index) + 1


def scan_text(text: str) -> list[Finding]:
    """Aggregate every detector over ``text``.

    Combines secrets, sensitive terms (PII) and entities, then de-duplicates
    by ``(kind, line, excerpt)`` while preserving first-seen order.
    """
    # Imported lazily to keep module import order simple and avoid cycles.
    from .entities import scan_entities
    from .secrets import scan_secrets
    from .sensitive_terms import scan_sensitive_terms

    findings: list[Finding] = []
    findings.extend(scan_secrets(text))
    findings.extend(scan_sensitive_terms(text))
    findings.extend(scan_entities(text))

    seen: set[tuple[str, int, str]] = set()
    deduped: list[Finding] = []
    for finding in findings:
        key = (finding.kind, finding.line, finding.excerpt)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def contains_secret_structure(value: object) -> bool:
    """Scan raw returned strings and serialized associations for access secrets.

    PII findings are not a reason to reject. Invalid or cyclic structures fail
    without exposing their contents; callers choose their own opaque error.
    """
    def secret(text: str) -> bool:
        return any(finding.category == "secret" for finding in scan_text(text))

    def raw(item: object) -> bool:
        if isinstance(item, str):
            return secret(item)
        if isinstance(item, dict):
            for key, child in item.items():
                if raw(key) or raw(child):
                    return True
                # Preserve a string key/value association before escaping,
                # including values whose own quotes are meaningful to a detector.
                if isinstance(key, str) and isinstance(child, str) and secret(key + ": " + child):
                    return True
            return False
        if isinstance(item, (list, tuple)):
            return any(raw(child) for child in item)
        if item is None or isinstance(item, (bool, int, float)):
            return False
        return secret(str(item))

    try:
        if raw(value):
            return True
        return secret(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str))
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError("invalid structured data") from None


def scan_file(path: str | Path) -> list[Finding]:
    """Read ``path`` as text and scan it; return ``[]`` for binary files.

    A file is treated as binary (and skipped) if its raw bytes contain a NUL
    byte. Decoding uses UTF-8 with ``errors="replace"`` so odd encodings do not
    crash the scan.
    """
    path = Path(path)
    raw = path.read_bytes()
    if b"\x00" in raw:
        return []
    text = raw.decode("utf-8", errors="replace")
    return scan_text(text)


__all__ = ["Finding", "redact", "line_of", "scan_text", "scan_file", "contains_secret_structure"]
