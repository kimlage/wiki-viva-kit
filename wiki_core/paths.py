from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import WikiConfig


@dataclass(frozen=True)
class WikiPaths:
    root: Path
    config: WikiConfig

    @property
    def memory_root(self) -> Path:
        return self.root / self.config.paths["memory_root"]

    @property
    def references_root(self) -> Path:
        return self.root / self.config.paths["references_root"]

    @property
    def raw_root(self) -> Path:
        return self.root / self.config.paths["raw_root"]

    @property
    def derived_root(self) -> Path:
        return self.root / self.config.paths["derived_root"]

    @property
    def source_manifests(self) -> Path:
        return self.derived_root / "source-manifests"

    @property
    def source_text(self) -> Path:
        return self.derived_root / "source-text"

    @property
    def chunks(self) -> Path:
        return self.derived_root / "chunks"

    @property
    def indexes(self) -> Path:
        return self.derived_root / "indexes"

    @property
    def extraction_events(self) -> Path:
        return self.derived_root / "extraction-events"

    @property
    def llm_cache(self) -> Path:
        return self.derived_root / "llm-cache"

    @property
    def coverage(self) -> Path:
        return self.derived_root / "coverage"

    def ensure(self) -> None:
        for path in (
            self.source_manifests,
            self.source_text,
            self.chunks,
            self.indexes,
            self.extraction_events,
            self.llm_cache,
            self.coverage,
        ):
            path.mkdir(parents=True, exist_ok=True)
