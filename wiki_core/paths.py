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
    def skills_root(self) -> Path:
        return self.root / self.config.paths["skills_root"]

    # ---- composed layout (memory subtree) ----------------------------------

    @property
    def system_dir(self) -> Path:
        return self.memory_root / self.config.paths["system_dirname"]

    @property
    def ingest_dir(self) -> Path:
        return self.system_dir / self.config.paths["ingest_dirname"]

    @property
    def ingest_events_dir(self) -> Path:
        return self.ingest_dir / self.config.paths["events_dirname"]

    @property
    def ingest_archive_dir(self) -> Path:
        return self.ingest_dir / self.config.paths["archive_dirname"]

    @property
    def decisions_dir(self) -> Path:
        return self.memory_root / self.config.paths["decisions_dirname"]

    @property
    def actions_dir(self) -> Path:
        return self.memory_root / self.config.paths["actions_dirname"]

    @property
    def pending_actions_file(self) -> Path:
        return self.actions_dir / self.config.paths["pending_actions_filename"]

    @property
    def sources_dir(self) -> Path:
        return self.memory_root / self.config.paths["sources_dirname"]

    @property
    def log_page(self) -> Path:
        return self.system_dir / "log.md"

    @property
    def operation_page(self) -> Path:
        return self.root / self.config.paths["operation_page"]

    @property
    def operational_pass_page(self) -> Path:
        return self.root / self.config.paths["operational_pass_page"]

    @property
    def command_reference_page(self) -> Path:
        return self.root / self.config.paths["command_reference_page"]

    @property
    def source_registry_page(self) -> Path:
        return self.root / self.config.paths["source_registry_page"]

    @property
    def input_stage_page(self) -> Path:
        root_entity = self.config.root_entity or {}
        page = str(root_entity.get("input_stage_page") or "memories/system/input-stage.md")
        return self.root / page

    @property
    def templates_root(self) -> Path:
        return self.references_root / "templates" / "wiki"

    def rel(self, path: Path) -> str:
        """Repo-relative POSIX string (the shape gates and links compare on)."""
        return path.relative_to(self.root).as_posix()

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

    @property
    def input_stage(self) -> Path:
        return self.derived_root / "input-stage"

    @property
    def input_stage_catalog(self) -> Path:
        return self.input_stage / "input-catalog.json"

    def ensure(self) -> None:
        for path in (
            self.source_manifests,
            self.source_text,
            self.chunks,
            self.indexes,
            self.extraction_events,
            self.llm_cache,
            self.coverage,
            self.input_stage,
        ):
            path.mkdir(parents=True, exist_ok=True)
