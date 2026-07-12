from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

import scripts.wiki_pack as wiki_pack
from wiki_core.config import WikiConfig
from wiki_core.experience_pack_fixtures import compile_pack_fixture
from wiki_core.experience_packs import PackError, install_pack
from wiki_core.output_safety import OUTPUT_OWNER_FILENAME
from wiki_core.web.snapshot import build_snapshot, snapshot_contract_errors


KIT_ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha(pack: Path) -> str:
    rows = [
        {
            "path": item.relative_to(pack).as_posix(),
            "sha256": _sha(item),
            "size": item.stat().st_size,
        }
        for item in sorted(pack.rglob("*"), key=lambda item: item.as_posix())
        if item.is_file()
    ]
    return hashlib.sha256(
        json.dumps(
            rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _repo(tmp_path: Path, pack_id: str) -> Path:
    root = tmp_path / pack_id
    root.mkdir(parents=True)
    source = root / "packs" / pack_id
    shutil.copytree(KIT_ROOT / "packs" / pack_id, source)
    manifest = yaml.safe_load((source / "pack.yaml").read_text(encoding="utf-8"))
    _write_yaml(
        root / "packs/registry.yaml",
        {
            "schema_version": "wiki_experience_pack_registry.v1",
            "packs": {
                pack_id: {
                    "default_version": manifest["version"],
                    "versions": {
                        manifest["version"]: {
                            "path": pack_id,
                            "manifest_sha256": _sha(source / "pack.yaml"),
                            "tree_sha256": _tree_sha(source),
                        }
                    },
                }
            },
        },
    )
    _write_yaml(
        root / "wiki.templates.yaml",
        {
            "schema_version": "wiki_templates.v2",
            "packages": {
                "quadrant_lenses": {"blocks": []},
                "gamification": {"blocks": []},
            },
        },
    )
    install_pack(root, pack_id, enforce_git_gate=False)
    return root


def _output(root: Path, name: str) -> Path:
    return root / ".wiki-viva/fixture-output" / name


def _activate_output(root: Path, output: Path, pack_id: str) -> None:
    shutil.copytree(root / "packs", output / "packs")
    shutil.copy2(root / "wiki.templates.yaml", output / "wiki.templates.yaml")
    install_pack(output, pack_id, enforce_git_gate=False)


def test_shipped_fixture_compiler_blocks_match_closed_schema() -> None:
    schema = json.loads(
        (
            KIT_ROOT
            / "docs/references/schemas/wiki-experience-pack-fixture-compiler-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    paths = [
        *sorted((KIT_ROOT / "packs/personal-finance/fixtures").glob("dense/scenario.yaml")),
        *sorted((KIT_ROOT / "packs/personal-finance/fixtures").glob("failure-*/scenario.yaml")),
        *sorted((KIT_ROOT / "packs/study-research/fixtures").glob("dense/scenario.yaml")),
        *sorted((KIT_ROOT / "packs/study-research/fixtures").glob("failure/scenario.yaml")),
    ]
    assert len(paths) == 7
    for path in paths:
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        validator.validate(scenario["compiler"])


@pytest.mark.parametrize(
    ("pack_id", "fixture", "expected_counts", "expected_kinds"),
    [
        (
            "personal-finance",
            "fixtures/dense",
            {
                "personal_finance_account": 6,
                "personal_finance_transaction": 720,
                "personal_finance_obligation": 36,
                "personal_finance_category": 24,
                "personal_finance_reconciliation": 72,
                "personal_finance_monthly_closing": 12,
            },
            {
                "personal-finance.transaction-occurred",
                "personal-finance.obligation-due",
                "personal-finance.reconciliation-recorded",
                "personal-finance.monthly-period",
                "personal-finance.monthly-closed",
            },
        ),
        (
            "study-research",
            "fixtures/dense",
            {
                "study_research_source": 24,
                "study_research_note": 48,
                "study_research_concept": 16,
                "study_research_claim": 20,
                "study_research_synthesis": 3,
            },
            {
                "study-research.learning-captured",
                "study-research.learning-reviewed",
                "study-research.claim-recorded",
                "study-research.claim-verified",
                "study-research.claim-superseded",
            },
        ),
    ],
)
def test_dense_fixture_compiler_materializes_declared_counts_and_valid_snapshot(
    tmp_path: Path,
    pack_id: str,
    fixture: str,
    expected_counts: dict[str, int],
    expected_kinds: set[str],
) -> None:
    root = _repo(tmp_path, pack_id)
    output = _output(root, "dense")
    report = compile_pack_fixture(root, pack_id, fixture, output)

    assert report["mode"] == "dense"
    assert report["diagnostic_codes"] == []
    assert {
        page_type: report["type_counts"][page_type]
        for page_type in expected_counts
    } == expected_counts
    assert (output / OUTPUT_OWNER_FILENAME).is_file()
    _activate_output(root, output, pack_id)
    snapshot = build_snapshot(
        output,
        WikiConfig(repo_id=f"{pack_id}-dense-fixture"),
        generated_at="2026-07-11T12:00:00Z",
    )
    assert snapshot_contract_errors(snapshot) == []
    assert len(snapshot["pages.json"]["pages"]) == report["page_count"]
    temporal = snapshot["temporal_graph.json"]
    assert temporal["diagnostics"] == []
    kinds = {event["kind"] for event in temporal["events"]}
    assert expected_kinds.issubset(kinds)
    assert all(
        event.get("lane") in {"source", "page"}
        for event in temporal["events"]
        if event["kind"] in expected_kinds
    )


@pytest.mark.parametrize(
    ("pack_id", "fixture", "diagnostic"),
    [
        ("personal-finance", "fixtures/failure-missing-source", "missing_source"),
        (
            "personal-finance",
            "fixtures/failure-duplicate-transaction",
            "duplicate_transaction",
        ),
        (
            "personal-finance",
            "fixtures/failure-late-close",
            "late_monthly_close",
        ),
        (
            "personal-finance",
            "fixtures/failure-public-export",
            "private_financial_fields_require_redaction",
        ),
        (
            "study-research",
            "fixtures/failure",
            "conflicting_evidence_requires_review",
        ),
    ],
)
def test_failure_fixture_compiler_applies_mutation_and_requires_exact_diagnostic(
    tmp_path: Path,
    pack_id: str,
    fixture: str,
    diagnostic: str,
) -> None:
    root = _repo(tmp_path, pack_id)
    output = _output(root, fixture.replace("/", "-"))
    report = compile_pack_fixture(root, pack_id, fixture, output)

    assert report["mode"] == "failure"
    assert report["diagnostic_codes"] == [diagnostic]
    assert list((output / "memories/fixture").glob("*.md"))


def test_fixture_compiler_rejects_repo_memory_namespace_and_unowned_output(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, "study-research")
    for target in (
        root,
        root / "memories",
        root / ".wiki-viva/fixture-output",
    ):
        with pytest.raises(PackError, match="fixture_output_target_invalid"):
            compile_pack_fixture(root, "study-research", "fixtures/failure", target)

    unowned = _output(root, "unowned")
    unowned.mkdir(parents=True)
    sentinel = unowned / "keep.txt"
    sentinel.write_text("owner data\n", encoding="utf-8")
    with pytest.raises(PackError, match="fixture_output_target_invalid"):
        compile_pack_fixture(root, "study-research", "fixtures/failure", unowned)
    assert sentinel.read_text(encoding="utf-8") == "owner data\n"


def test_fixture_compiler_blocks_page_id_traversal_before_any_output(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, "personal-finance")
    pack = root / "packs/personal-finance"
    page = pack / "fixtures/normal/pages/transaction-housing.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "page_id: finance-transaction-housing",
            "page_id: ../../escaped",
        ),
        encoding="utf-8",
    )
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["personal-finance"]["versions"]["0.1.0"][
        "tree_sha256"
    ] = _tree_sha(pack)
    _write_yaml(registry_path, registry)
    output = _output(root, "traversal")

    with pytest.raises(PackError, match="fixture_page_id_required"):
        compile_pack_fixture(
            root,
            "personal-finance",
            "fixtures/failure-duplicate-transaction",
            output,
        )
    assert not output.exists()
    assert not list(root.rglob("escaped.md"))


def test_fixture_compiler_never_replaces_output_owned_by_another_fixture(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, "study-research")
    output = _output(root, "stable-owned")
    compile_pack_fixture(root, "study-research", "fixtures/dense", output)
    before = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }

    with pytest.raises(PackError, match="fixture_output_target_invalid"):
        compile_pack_fixture(root, "study-research", "fixtures/failure", output)
    after = {
        path.relative_to(output).as_posix(): path.read_bytes()
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_pack_cli_materializes_only_managed_fixture_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path, "study-research")
    relative = Path(".wiki-viva/fixture-output/cli-failure")
    assert wiki_pack.main(
        [
            "--root",
            str(root),
            "compile-fixture",
            "study-research",
            "fixtures/failure",
            "--output",
            str(relative),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostic_codes"] == [
        "conflicting_evidence_requires_review"
    ]
    assert (root / relative / OUTPUT_OWNER_FILENAME).is_file()

    assert wiki_pack.main(
        [
            "--root",
            str(root),
            "compile-fixture",
            "study-research",
            "fixtures/failure",
            "--output",
            "memories",
        ]
    ) == 2
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["error"]["code"] == "fixture_output_target_invalid"
