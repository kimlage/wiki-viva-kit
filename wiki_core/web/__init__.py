"""Web cockpit read and action model for Wiki Viva."""

from .snapshot import WEB_SNAPSHOT_SCHEMA_VERSION, build_snapshot, write_snapshot

__all__ = ["WEB_SNAPSHOT_SCHEMA_VERSION", "build_snapshot", "write_snapshot"]
