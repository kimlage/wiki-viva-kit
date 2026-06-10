"""PII detectors for personal identifiers (CPF, CNPJ, credit card, IBAN).

Personal data is WELCOME in private pages of this personal repo -- these
detectors do not block it. They exist to (a) label sensitivity at ingestion and
(b) feed the PUBLIC/EXPORT boundary, where PII must be redacted before a page is
shared. Access secrets are a separate concern (see ``secrets.py``), blocked
everywhere.

Credit-card candidates are validated with the Luhn checksum so numbers that
fail the check (most random digit runs) are not reported -- a big reduction in
false positives over a naive 13-19 digit match.
"""

from __future__ import annotations

import re

from . import Finding, line_of, redact

_DETECTOR = "sensitive_terms"
_CATEGORY = "pii"

_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

# Without punctuation: exactly 11/14 digits. We only report when the check digit
# matches (drastically reduces false positives on random numbers/phone numbers).
_CPF_BARE_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
_CNPJ_BARE_RE = re.compile(r"(?<!\d)\d{14}(?!\d)")


def _cpf_valid(digits: str) -> bool:
    if len(digits) != 11 or len(set(digits)) == 1:
        return False

    def dv(prefix: str, start: int) -> int:
        total = sum(int(d) * w for d, w in zip(prefix, range(start, 1, -1)))
        rest = (total * 10) % 11
        return 0 if rest == 10 else rest

    return dv(digits[:9], 10) == int(digits[9]) and dv(digits[:10], 11) == int(digits[10])


def _cnpj_valid(digits: str) -> bool:
    if len(digits) != 14 or len(set(digits)) == 1:
        return False

    def dv(prefix: str, weights: list[int]) -> int:
        total = sum(int(d) * w for d, w in zip(prefix, weights))
        rest = total % 11
        return 0 if rest < 2 else 11 - rest

    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    return dv(digits[:12], w1) == int(digits[12]) and dv(digits[:13], w2) == int(digits[13])

# 13-19 digits, optionally grouped by single spaces or hyphens. Anchored on
# non-digit boundaries so we do not slice the middle of a longer number.
_CARD_CANDIDATE_RE = re.compile(
    r"(?<![\d.-])(?:\d[ -]?){12,18}\d(?![\d.-])"
)


def _luhn_valid(digits: str) -> bool:
    """Return ``True`` if ``digits`` (digits only) passes the Luhn checksum."""
    if not digits.isdigit():
        return False
    total = 0
    # Walk right-to-left, doubling every second digit.
    for offset, char in enumerate(reversed(digits)):
        value = int(char)
        if offset % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def scan_sensitive_terms(text: str) -> list[Finding]:
    """Detect PII in ``text`` (CPF, CNPJ, credit card, IBAN).

    Informational: PII is allowed in private pages; findings drive the export
    boundary and sensitivity labels, not a block.
    """
    findings: list[Finding] = []

    for match in _CPF_RE.finditer(text):
        findings.append(
            Finding(
                kind="cpf",
                category=_CATEGORY,
                severity="alto",
                line=line_of(text, match.start()),
                excerpt=redact(match.group(0)),
                detector=_DETECTOR,
            )
        )

    for match in _CNPJ_RE.finditer(text):
        findings.append(
            Finding(
                kind="cnpj",
                category=_CATEGORY,
                severity="medio",
                line=line_of(text, match.start()),
                excerpt=redact(match.group(0)),
                detector=_DETECTOR,
            )
        )

    for match in _CARD_CANDIDATE_RE.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if not (13 <= len(digits) <= 19):
            continue
        if not _luhn_valid(digits):
            continue
        findings.append(
            Finding(
                kind="credit_card",
                category=_CATEGORY,
                severity="critico",
                line=line_of(text, match.start()),
                excerpt=redact(raw.strip()),
                detector=_DETECTOR,
            )
        )

    for match in _IBAN_RE.finditer(text):
        findings.append(
            Finding(
                kind="iban",
                category=_CATEGORY,
                severity="medio",
                line=line_of(text, match.start()),
                excerpt=redact(match.group(0)),
                detector=_DETECTOR,
            )
        )

    for match in _CPF_BARE_RE.finditer(text):
        if _cpf_valid(match.group(0)):
            findings.append(
                Finding(
                    kind="cpf_sem_pontuacao",
                    category=_CATEGORY,
                    severity="alto",
                    line=line_of(text, match.start()),
                    excerpt=redact(match.group(0)),
                    detector=_DETECTOR,
                )
            )

    for match in _CNPJ_BARE_RE.finditer(text):
        if _cnpj_valid(match.group(0)):
            findings.append(
                Finding(
                    kind="cnpj_sem_pontuacao",
                    category=_CATEGORY,
                    severity="medio",
                    line=line_of(text, match.start()),
                    excerpt=redact(match.group(0)),
                    detector=_DETECTOR,
                )
            )

    return findings


__all__ = ["scan_sensitive_terms"]
