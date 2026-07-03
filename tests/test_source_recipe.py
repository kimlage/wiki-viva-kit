from __future__ import annotations

from wiki_core.source_recipe import (
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
    errors = " | ".join(validate_recipe(recipe))
    assert "must not contain credentials" in errors


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
    errors = " | ".join(validate_recipe(recipe))
    assert "credential-looking value" in errors
    # The secret itself is never echoed back.
    assert "xox" not in errors and "sk-" not in errors


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
