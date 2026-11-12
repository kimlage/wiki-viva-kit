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

    def _collection_layout(self, dirname_key: str) -> tuple[Path, str]:
        """Validate the configured names before discovering or selecting pages."""
        from .context_policy import safe_path

        memory = safe_path(self.config.paths["memory_root"])
        dirname = safe_path(self.config.paths[dirname_key])
        if Path(memory).is_absolute() or Path(dirname).is_absolute() or len(Path(dirname).parts) != 1:
            raise ValueError("collection dirname must be one path segment")
        return self.root / memory, dirname

    def collection_root(self, path: Path, dirname_key: str) -> Path | None:
        """Nearest named collection owning a path, without scanning other contexts.

        This is layout membership only, never an access or routing grant.
        """
        memory, dirname = self._collection_layout(dirname_key)
        try:
            relative = path.relative_to(memory)
        except ValueError:
            return None
        if ".." in relative.parts:
            return None
        for parent in relative.parents:
            if parent.name == dirname:
                return memory / parent
        return None

    def collection_files(self, dirname_key: str, *, reads=None) -> list[Path]:
        """Legacy and context-local Markdown, once each, inside the wiki boundary.

        Discover names under memory only; callers still filter page types and
        enforce their explicit selection/authorization. Guarded callers use
        their admitted metadata and bodies, never a new filesystem readset.
        """
        from .traversal import wiki_markdown_files

        memory, _ = self._collection_layout(dirname_key)
        candidates = (wiki_markdown_files(memory, wiki_root=self.root) if reads is None
                      else reads.markdown(memory, self.root))
        return [path for path in candidates if self.collection_root(path, dirname_key) is not None]

    def action_files(self) -> list[Path]:
        return self.collection_files("actions_dirname")

    def source_files(self, *, reads=None) -> list[Path]:
        return self.collection_files("sources_dirname", reads=reads)

    def collection_selector(self, dirname_key: str) -> dict[str, str]:
        """Projection predicate matching discovery, including future local pages."""
        memory, dirname = self._collection_layout(dirname_key)
        return {"path_prefix": self.rel(memory), "path_directory": dirname}

    def action_path(self, page_ref: str) -> Path:
        """Select one action path without requiring the legacy global directory."""
        from .context_policy import safe_path
        from .traversal import require_wiki_boundaries

        try:
            memory, _ = self._collection_layout("actions_dirname")
            require_wiki_boundaries(self.root, directories=(memory,))
        except ValueError:
            raise ValueError("invalid configured actions directory") from None
        path = self.root / safe_path(page_ref)
        if path.suffix.lower() != ".md" or self.collection_root(path, "actions_dirname") is None:
            raise ValueError("action outside configured actions directory")
        try:
            require_wiki_boundaries(self.root, files=(path,))
        except ValueError:
            raise ValueError("invalid configured actions directory") from None
        return path

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
    def source_state(self) -> Path:
        """Per-source incremental cursor state (Singer STATE analogue). Mutable,
        derived, gitignored — NEVER in the versioned source config."""
        return self.derived_root / "source-state"

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
