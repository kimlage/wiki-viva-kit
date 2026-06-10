from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    # Normalize accents to ASCII (NFKD) before filtering: 'Relatorio Medico' and
    # 'café' stop colliding with forms like 'caf!' (accent collision finding)
    # and produce readable slugs ('relatorio-medico', 'cafe').
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"
