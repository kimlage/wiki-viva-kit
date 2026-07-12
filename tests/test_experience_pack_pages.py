from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

import scripts.wiki_new as wiki_new
from wiki_core.config import WikiConfig
from wiki_core.experience_packs import PackError, disable_pack, install_pack, load_lock
from wiki_core.frontmatter import parse_frontmatter_flat
from wiki_core.page_types import load_page_type_registry, validate_shape
from wiki_core.templates import (
    default_output_path,
    instantiate_template,
    resolve_template,
)


KIT_ROOT = Path(__file__).resolve().parents[1]
STUDY_PACK = KIT_ROOT / "packs/study-research"
FINANCE_PACK = KIT_ROOT / "packs/personal-finance"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


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


def _repo(tmp_path: Path, *, core_collision: bool = False) -> Path:
    root = tmp_path / "wiki"
    root.mkdir(parents=True)
    core_types: dict[str, object] = {
        "context_note": {
            "template": "docs/context-note.md",
            "allowed_dirs": ["memories"],
            "required_frontmatter": ["page_id", "page_type"],
            "field_types": {},
        }
    }
    if core_collision:
        core_types["study_research_note"] = {
            "template": "docs/context-note.md",
            "allowed_dirs": ["memories"],
            "required_frontmatter": ["page_id", "page_type"],
            "field_types": {},
        }
    _write_yaml(
        root / "wiki.page-types.yaml",
        {"schema_version": "wiki_page_types.v1", "page_types": core_types},
    )
    (root / "docs").mkdir()
    (root / "docs/context-note.md").write_text(
        "---\npage_type: context_note\n---\n\n# Context note\n",
        encoding="utf-8",
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
    shutil.copytree(STUDY_PACK, root / "packs/study-research")
    _write_yaml(
        root / "packs/registry.yaml",
        {
            "schema_version": "wiki_experience_pack_registry.v1",
            "packs": {
                "study-research": {
                    "default_version": "0.1.0",
                    "versions": {
                        "0.1.0": {
                            "path": "study-research",
                            "manifest_sha256": _sha(
                                root / "packs/study-research/pack.yaml"
                            ),
                            "tree_sha256": _tree_sha(
                                root / "packs/study-research"
                            ),
                        }
                    },
                }
            },
        },
    )
    return root


def _installed(root: Path) -> Path:
    entry = load_lock(root)["packs"]["study-research"]
    return root / entry["installed_path"]


def _register_finance(root: Path) -> None:
    shutil.copytree(FINANCE_PACK, root / "packs/personal-finance")
    registry_path = root / "packs/registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["packs"]["personal-finance"] = {
        "default_version": "0.1.0",
        "versions": {
            "0.1.0": {
                "path": "personal-finance",
                "manifest_sha256": _sha(root / "packs/personal-finance/pack.yaml"),
                "tree_sha256": _tree_sha(root / "packs/personal-finance"),
            }
        },
    }
    _write_yaml(registry_path, registry)


def test_active_pack_type_creates_from_verified_installed_template(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    registry = load_page_type_registry(root)
    assert registry is not None
    page_type = "study_research_note"
    shape = registry.page_types[page_type]
    assert shape["experience_pack"]["id"] == "study-research"
    assert shape["template"].startswith(
        ".wiki-viva/packs/study-research/0.1.0/templates/"
    )

    untrusted = root / "docs/untrusted.md"
    untrusted.write_text(
        "---\nvisibility: public\n---\n\n# Wrong template\n", encoding="utf-8"
    )
    config = WikiConfig(
        templates={
            **WikiConfig().templates,
            "page_type_overrides": {page_type: {"template": "docs/untrusted.md"}},
        }
    )
    resolved = resolve_template(root, config, registry, page_type)
    text = instantiate_template(
        resolved,
        title="Causal inference notes",
        context="research",
        config=config,
    )
    values = parse_frontmatter_flat(text)
    output = default_output_path(registry, page_type, "Causal inference notes")

    assert "# Research note" in text
    assert "Wrong template" not in text
    assert values["template_id"] == "study-research:study_research_note"
    assert values["template_version"] == "0.1.0"
    assert values["visibility"] == "private"
    assert output == ("memories/packs/study-research/note/causal-inference-notes.md")
    assert validate_shape(root, output, values, text, shape) == []


def test_wiki_new_cli_writes_active_pack_page_to_its_owned_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wiki_new.py",
            "--type",
            "study_research_question",
            "--title",
            "What would falsify this?",
            "--context",
            "research",
        ],
    )

    assert wiki_new.main() == 0
    relative = "memories/packs/study-research/question/what-would-falsify-this.md"
    assert capsys.readouterr().out.strip() == relative
    page = root / relative
    assert page.is_file()
    text = page.read_text(encoding="utf-8")
    assert "page_type: study_research_question" in text
    assert "visibility: private" in text
    assert "template_id: study-research:study_research_question" in text


def test_wiki_new_rejects_output_traversal_and_symlink_escape_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    traversal_root = _repo(tmp_path / "traversal")
    install_pack(traversal_root, "study-research", enforce_git_gate=False)
    monkeypatch.setattr(wiki_new, "ROOT", traversal_root)
    for output in (
        "../../escaped.md",
        "/tmp/wiki-viva-absolute-escape.md",
        "memories/packs/study-research/question/../escaped.md",
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "wiki_new.py",
                "--type",
                "study_research_question",
                "--title",
                "Traversal attempt",
                "--output",
                output,
            ],
        )
        assert wiki_new.main() == 2
        assert "ERROR:" in capsys.readouterr().err
    assert not list(tmp_path.rglob("escaped.md"))
    assert not Path("/tmp/wiki-viva-absolute-escape.md").exists()

    symlink_root = _repo(tmp_path / "symlink")
    install_pack(symlink_root, "study-research", enforce_git_gate=False)
    outside = tmp_path / "outside"
    outside.mkdir()
    pack_namespace = symlink_root / "memories/packs/study-research"
    pack_namespace.mkdir(parents=True)
    (pack_namespace / "question").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(wiki_new, "ROOT", symlink_root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wiki_new.py",
            "--type",
            "study_research_question",
            "--title",
            "Symlink attempt",
        ],
    )
    assert wiki_new.main() == 2
    assert "symlink" in capsys.readouterr().err.lower()
    assert list(outside.iterdir()) == []


def test_wiki_new_rejects_invalid_render_and_never_clobbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wiki_new.py",
            "--type",
            "study_research_question",
            "--title",
            "Harmless\nvisibility: public",
        ],
    )
    assert wiki_new.main() == 2
    assert "rendered `title` does not match" in capsys.readouterr().err
    question_dir = root / "memories/packs/study-research/question"
    assert not question_dir.exists()

    destination = question_dir / "existing.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("do not replace\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wiki_new.py",
            "--type",
            "study_research_question",
            "--title",
            "Existing",
            "--output",
            "memories/packs/study-research/question/existing.md",
        ],
    )
    assert wiki_new.main() == 2
    assert "destination exists" in capsys.readouterr().err
    assert destination.read_text(encoding="utf-8") == "do not replace\n"


def test_pack_shape_enforces_privacy_and_declared_fields(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    registry = load_page_type_registry(root)
    assert registry is not None
    page_type = "study_research_claim"
    shape = registry.page_types[page_type]
    resolved = resolve_template(root, WikiConfig(), registry, page_type)
    text = instantiate_template(
        resolved,
        title="A synthetic claim",
        context="research",
        config=WikiConfig(),
    )

    public_text = text.replace("visibility: private", "visibility: public", 1)
    public_errors = validate_shape(
        root,
        "memories/packs/study-research/claim/a-synthetic-claim.md",
        parse_frontmatter_flat(public_text),
        public_text,
        shape,
    )
    assert any("visibility` must remain `private" in error for error in public_errors)

    missing_field_text = text.replace("evidence_against: []\n", "", 1)
    field_errors = validate_shape(
        root,
        "memories/packs/study-research/claim/a-synthetic-claim.md",
        parse_frontmatter_flat(missing_field_text),
        missing_field_text,
        shape,
    )
    assert any(
        "missing declared pack field `evidence_against`" in error
        for error in field_errors
    )


def test_multiple_pack_page_type_contracts_compose_without_domain_hardcoding(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    _register_finance(root)
    install_pack(root, "study-research", enforce_git_gate=False)
    install_pack(root, "personal-finance", enforce_git_gate=False)
    registry = load_page_type_registry(root)
    assert registry is not None
    contributed = {
        page_type
        for page_type, shape in registry.page_types.items()
        if isinstance(shape.get("experience_pack"), dict)
    }
    assert len(contributed) == 13
    assert {
        "study_research_synthesis",
        "personal_finance_transaction",
        "personal_finance_monthly_closing",
    } <= contributed

    resolved = resolve_template(
        root,
        WikiConfig(),
        registry,
        "personal_finance_transaction",
    )
    text = instantiate_template(
        resolved,
        title="Synthetic grocery transaction",
        context="finance",
        config=WikiConfig(),
    )
    assert "# Transaction" in text
    assert "visibility: private" in text
    assert "template_version: 0.1.0" in text


def test_pack_page_type_namespace_follows_configured_memory_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _repo(tmp_path)
    (root / "wiki.config.yaml").write_text(
        "paths:\n  memory_root: memorias\n",
        encoding="utf-8",
    )
    install_pack(root, "study-research", enforce_git_gate=False)

    registry = load_page_type_registry(root)

    assert registry is not None
    assert registry.page_types["study_research_note"]["allowed_dirs"] == [
        "memorias/packs/study-research/note"
    ]
    assert (
        default_output_path(
            registry,
            "study_research_note",
            "Notas de causalidade",
        )
        == "memorias/packs/study-research/note/notas-de-causalidade.md"
    )

    monkeypatch.setattr(wiki_new, "ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wiki_new.py",
            "--type",
            "study_research_note",
            "--title",
            "Notas de causalidade",
            "--context",
            "research",
        ],
    )
    assert wiki_new.main() == 0
    assert capsys.readouterr().out.strip() == (
        "memorias/packs/study-research/note/notas-de-causalidade.md"
    )
    assert (
        root / "memorias/packs/study-research/note/notas-de-causalidade.md"
    ).is_file()


def test_pack_page_type_and_template_drift_fail_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    install_pack(root, "study-research", enforce_git_gate=False)
    registry = load_page_type_registry(root)
    assert registry is not None

    template = _installed(root) / "templates/note.md"
    template.write_text(
        template.read_text(encoding="utf-8") + "\nDrift.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="installed pack template drift"):
        resolve_template(root, WikiConfig(), registry, "study_research_note")
    with pytest.raises(PackError, match="active_pack_page_types_unverified"):
        load_page_type_registry(root)


def test_core_and_active_pack_page_type_conflict_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path, core_collision=True)
    install_pack(root, "study-research", enforce_git_gate=False)
    with pytest.raises(PackError, match="page_type_conflict: study_research_note"):
        load_page_type_registry(root)


def test_core_only_and_disabled_pack_remain_compatible(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    core_registry = load_page_type_registry(root)
    assert core_registry is not None
    assert set(core_registry.page_types) == {"context_note"}

    install_pack(root, "study-research", enforce_git_gate=False)
    disable_pack(root, "study-research", enforce_git_gate=False)
    # Disabled bundles do not contribute runtime types and cannot make the
    # core-only authoring surface depend on their mutable artifact state.
    (_installed(root) / "page-types.yaml").write_text(
        "disabled drift\n", encoding="utf-8"
    )
    disabled_registry = load_page_type_registry(root)
    assert disabled_registry is not None
    assert set(disabled_registry.page_types) == {"context_note"}
