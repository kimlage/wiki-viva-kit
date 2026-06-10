"""Low-severity entity detectors (e-mail addresses).

Entities are purely informational: they label personal data (welcome in private
pages) without implying a secret leak. Useful only at the public/export boundary.
Kept intentionally small.
"""

from __future__ import annotations

import re

from . import Finding, line_of, redact

_DETECTOR = "entities"
_CATEGORY = "entity"

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)


def scan_entities(text: str) -> list[Finding]:
    """Detect informational entities (currently e-mail addresses)."""
    findings: list[Finding] = []

    for match in _EMAIL_RE.finditer(text):
        findings.append(
            Finding(
                kind="email_address",
                category=_CATEGORY,
                severity="baixo",
                line=line_of(text, match.start()),
                excerpt=redact(match.group(0)),
                detector=_DETECTOR,
            )
        )

    return findings


__all__ = ["scan_entities"]
