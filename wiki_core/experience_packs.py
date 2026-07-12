"""Public facade for the deterministic Wiki Viva experience-pack kernel.

The implementation is split by responsibility so each security boundary stays
reviewable: shared contracts, source validation, lock/composition state and the
bounded lifecycle mutation layer.  Callers should import this facade.
"""

from wiki_core._experience_pack_common import (
    ASSET_SCHEMA_VERSION,
    COMPOSITION_SCHEMA_VERSION,
    CORE_VERSION,
    LOCK_SCHEMA_VERSION,
    MIGRATION_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
    PackError,
    PackFile,
    PackSource,
    canonical_json,
    version_satisfies,
)
from wiki_core._experience_pack_lifecycle import (
    assert_review_branch,
    disable_pack,
    install_pack,
    remove_pack,
    upgrade_pack,
    validate_installation,
)
from wiki_core._experience_pack_temporal import (
    PACK_TEMPORAL_ADAPTER_VERSION,
    load_active_temporal_adapters,
    temporal_adapter_projection,
)
from wiki_core._experience_pack_state import (
    compose_active_packs,
    list_packs,
    load_lock,
)
from wiki_core._experience_pack_validation import (
    inspect_pack,
    load_registry,
    preview_pack,
    resolve_pack,
    validate_manifest,
)
from wiki_core.experience_pack_fixtures import (
    FIXTURE_COMPILER_SCHEMA_VERSION,
    compile_pack_fixture,
)

__all__ = [
    "ASSET_SCHEMA_VERSION",
    "COMPOSITION_SCHEMA_VERSION",
    "CORE_VERSION",
    "FIXTURE_COMPILER_SCHEMA_VERSION",
    "LOCK_SCHEMA_VERSION",
    "MIGRATION_SCHEMA_VERSION",
    "PACK_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "REGISTRY_SCHEMA_VERSION",
    "PackError",
    "PackFile",
    "PackSource",
    "PACK_TEMPORAL_ADAPTER_VERSION",
    "assert_review_branch",
    "canonical_json",
    "compose_active_packs",
    "compile_pack_fixture",
    "disable_pack",
    "inspect_pack",
    "install_pack",
    "list_packs",
    "load_lock",
    "load_active_temporal_adapters",
    "load_registry",
    "preview_pack",
    "remove_pack",
    "resolve_pack",
    "upgrade_pack",
    "validate_installation",
    "validate_manifest",
    "temporal_adapter_projection",
    "version_satisfies",
]
