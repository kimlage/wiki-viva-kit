from wiki_core.source_schedule import (
    SCHEDULE_MODES,
    SOURCE_KINDS,
    SOURCE_SCHEDULE_SCHEMA_VERSION,
    infer_source_kind,
    validate_schedule,
    validate_source_kind,
)


def test_shared_source_schedule_contract_is_versioned_and_complete() -> None:
    assert SOURCE_SCHEDULE_SCHEMA_VERSION == "wiki_source_schedule.v1"
    assert SOURCE_KINDS == {"item", "collection", "account", "endpoint", "repository"}
    assert SCHEDULE_MODES == {"one_shot", "on_demand", "recurring", "event_driven"}


def test_only_recurring_sources_use_time_based_cadence() -> None:
    assert validate_schedule("recurring", 7) == []
    assert validate_schedule("recurring", 0) == ["a recurring schedule needs a positive cadence_days"]
    for mode in ("one_shot", "on_demand", "event_driven"):
        assert validate_schedule(mode, 0) == []
        assert validate_schedule(mode, 7) == [f"a {mode} schedule must use cadence_days: 0"]


def test_platform_kind_inference_is_shared_without_overriding_explicit_recipes() -> None:
    assert infer_source_kind("drive") == "collection"
    assert infer_source_kind("gmail") == "account"
    assert infer_source_kind("repo") == "repository"
    assert infer_source_kind("web") == "endpoint"
    assert infer_source_kind("manual") == "item"
    assert validate_source_kind("collection") == []
    assert "unknown source_kind" in validate_source_kind("folder")[0]
