from __future__ import annotations

import pytest

from wiki_core.source_recipe import (
    SOURCE_RECIPE_SAFETY_ERROR_CODE,
    SOURCE_RECIPE_STRUCTURE_ERROR_CODES,
    extract_recipe_mapping,
    parse_recipe,
    validate_recipe,
)

GOOD_CONFIG = """---
page_id: source-config-slack-fin
page_type: source_config
---

# Slack finance config

```yaml
recipe:
  schema_version: wiki_source_recipe.v1
  platform: slack
  locator: "T024/finance"
  source_kind: collection
  pipelines:
    - { kind: metadata, cadence_days: 30 }
    - { kind: content, cadence_days: 7 }
  streams:
    - id: "#financeiro"
      label: "Finanças do time"
      selected: true
      privacy: private_sensitive_allowed
      target_pages: [memorias/financeiro/index.md]
    - id: "dm:joao"
      selected: false
      skip_reason: "pessoal, fora do escopo"
  how_to_export: |
    Exportar via Slack export.
  ingest:
    argv: ["python3", "scripts/wiki_ingest.py", "--source", "{path}"]
  schedule: { mode: recurring, cadence_days: 7 }
```
"""


def test_extract_and_parse_a_valid_recipe() -> None:
    mapping = extract_recipe_mapping(GOOD_CONFIG)
    assert mapping is not None
    recipe = parse_recipe(mapping)
    assert recipe.platform == "slack"
    assert recipe.locator == "T024/finance"
    assert [p.kind for p in recipe.pipelines] == ["metadata", "content"]
    assert len(recipe.streams) == 2
    fin = recipe.streams[0]
    assert fin.selected and fin.target_pages == ("memorias/financeiro/index.md",)
    assert recipe.streams[1].selected is False and recipe.streams[1].skip_reason
    assert validate_recipe(recipe) == []
    assert recipe.to_json()["streams"][0]["id"] == "#financeiro"


def test_recipe_exposes_a_consumer_owned_deterministic_refresh_adapter() -> None:
    mapping = extract_recipe_mapping(GOOD_CONFIG)
    assert mapping is not None
    mapping["refresh"] = {
        "argv": ["python3", "scripts/source_inventory.py", "--source", "{source_id}", "--locator", "{locator}"]
    }
    recipe = parse_recipe(mapping)
    assert recipe.refresh_argv == (
        "python3",
        "scripts/source_inventory.py",
        "--source",
        "{source_id}",
        "--locator",
        "{locator}",
    )
    assert recipe.to_json()["refresh"]["argv"] == list(recipe.refresh_argv)


def test_absent_recipe_returns_none() -> None:
    assert extract_recipe_mapping("# a page with no recipe block\n") is None
    assert extract_recipe_mapping("```yaml\nfoo: bar\n```\n") is None


def test_validation_catches_structural_problems() -> None:
    recipe = parse_recipe(
        {
            "platform": "telepathy",
            "locator": "",
            "pipelines": [{"kind": "wat", "cadence_days": 0}],
            "streams": [
                {"id": "a"},
                {"id": "a"},
                {"id": "b", "selected": False},
            ],
        }
    )
    errors = " | ".join(validate_recipe(recipe))
    assert "unknown platform" in errors
    assert "locator is required" in errors
    assert "unknown pipeline kind" in errors
    assert "positive cadence_days" in errors
    assert "duplicate stream id" in errors
    assert "without a skip_reason" in errors


def test_recipe_must_not_carry_credentials() -> None:
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": "x",
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [],
            "api_token": "xoxb-should-never-be-here",
        }
    )
    assert validate_recipe(recipe) == [SOURCE_RECIPE_SAFETY_ERROR_CODE]


def test_recipe_rejects_a_credential_in_a_VALUE_not_just_a_key() -> None:
    # A secret hidden under an innocent key name must still be caught. The
    # token-shaped strings are ASSEMBLED from fragments so this test file carries
    # no literal secret (repo push-protection scanners flag literals).
    slack_like = "-".join(["xox" + "b", "2233445566", "AbCdEfGhIjKlMnOp"])
    bearer_like = "sk-" + "a" * 24
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": slack_like,  # a token where a locator should be
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [{"id": "s1", "how_to_export": f"Authorization: Bearer {bearer_like}"}],
        }
    )
    errors = validate_recipe(recipe)
    assert errors == [SOURCE_RECIPE_SAFETY_ERROR_CODE]
    # The secret itself is never echoed back.
    serialized_errors = " | ".join(errors)
    assert "xox" not in serialized_errors and "sk-" not in serialized_errors


@pytest.mark.parametrize(
    "secret",
    [
        "github_" + "pat_" + "A" * 30,
        "sk-" + "ant-" + "A" * 30,
        "sk_" + "live_" + "A" * 20,
        "postgresql" + "://alice:SuperSecret42@db.example",
    ],
)
def test_recipe_uses_the_canonical_secret_detector_taxonomy(secret: str) -> None:
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": secret,
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [],
        }
    )

    assert validate_recipe(recipe) == [SOURCE_RECIPE_SAFETY_ERROR_CODE]


def test_recipe_v2_auth_pointer_and_schedule_are_additive_and_pointer_only() -> None:
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": "T1",
            "source_kind": "collection",
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [{"id": "eng", "cadence_days": 3}],
            "auth": {"method": "mcp", "ref": "slack-mcp", "scopes": ["channels:history"], "note": "read-only"},
            "schedule": {"mode": "recurring", "cadence_days": 14},
        }
    )
    assert recipe.auth is not None and recipe.auth.method == "mcp" and recipe.auth.ref == "slack-mcp"
    assert recipe.schedule is not None and recipe.schedule.mode == "recurring"
    assert recipe.streams[0].cadence_days == 3  # per-stream override
    assert validate_recipe(recipe) == []
    # to_json carries the pointer (never a secret value).
    j = recipe.to_json()
    assert j["auth"]["ref"] == "slack-mcp" and j["schedule"]["cadence_days"] == 14


def test_recipe_v2_rejects_bad_auth_method_and_env_ref_shape() -> None:
    bad = parse_recipe(
        {
            "platform": "slack",
            "locator": "T1",
            "source_kind": "collection",
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [],
            "auth": {"method": "telepathy", "ref": "x"},
            "schedule": {"mode": "on_demand", "cadence_days": 0},
        }
    )
    assert any("auth.method" in e for e in validate_recipe(bad))
    env_bad = parse_recipe(
        {
            "platform": "web",
            "locator": "https://x",
            "source_kind": "endpoint",
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [],
            "auth": {"method": "env", "ref": "lower-case-not-env"},
            "schedule": {"mode": "on_demand", "cadence_days": 0},
        }
    )
    assert any("env var name" in e for e in validate_recipe(env_bad))


def test_non_numeric_cadence_days_does_not_crash() -> None:
    # A hand-authored "weekly" cadence coerces to 0 (then validation flags it),
    # never raising ValueError from int().
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": "T1",
            "pipelines": [{"kind": "content", "cadence_days": "weekly"}],
            "streams": [],
        }
    )
    assert recipe.pipelines[0].cadence_days == 0
    assert any("positive cadence_days" in e for e in validate_recipe(recipe))


def test_malformed_nested_recipe_shapes_are_lenient_and_code_only() -> None:
    recipe = parse_recipe(
        {
            "platform": "slack",
            "locator": "T1",
            "pipelines": [{"kind": "content", "cadence_days": 7}],
            "streams": [
                {
                    "id": "broken",
                    "filters": ["not", "a", "mapping"],
                    "target_pages": "not-a-list",
                }
            ],
            "ingest": "not-a-mapping",
            "auth": {"method": "mcp", "ref": "source-mcp", "scopes": "all"},
            "schedule": "weekly",
        }
    )

    errors = validate_recipe(recipe)
    assert set(recipe.structural_error_codes) <= SOURCE_RECIPE_STRUCTURE_ERROR_CODES
    assert set(recipe.structural_error_codes) <= set(errors)
    assert recipe.streams[0].filters == {}
    assert recipe.streams[0].target_pages == ()
    assert recipe.ingest_argv == ()
    assert not any("not-a-mapping" in error or "not-a-list" in error for error in errors)
