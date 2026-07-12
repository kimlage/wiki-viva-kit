#!/usr/bin/env python3
"""Inspect and operate declarative Wiki Viva experience packs safely."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scripts._common import ROOT
except ModuleNotFoundError:
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

from wiki_core.experience_packs import (  # noqa: E402
    PackError,
    compile_pack_fixture,
    disable_pack,
    inspect_pack,
    install_pack,
    list_packs,
    load_registry,
    preview_pack,
    remove_pack,
    resolve_pack,
    upgrade_pack,
    validate_installation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root (defaults to the repository containing this script)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        help="repository-relative registry path (default: packs/registry.yaml)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list registered and installed packs")

    for name in ("inspect", "preview"):
        command = commands.add_parser(name, help=f"{name} a pack")
        command.add_argument("pack")
        command.add_argument("--version")

    validate = commands.add_parser("validate", help="validate one pack or the complete registry")
    validate.add_argument("pack", nargs="?")
    validate.add_argument("--version")
    validate.add_argument(
        "--all",
        action="store_true",
        help="validate every registered source version and the installed composition",
    )

    compile_fixture = commands.add_parser(
        "compile-fixture",
        help="materialize a declared dense/failure fixture in the managed output namespace",
    )
    compile_fixture.add_argument("pack")
    compile_fixture.add_argument("fixture")
    compile_fixture.add_argument(
        "--output",
        type=Path,
        required=True,
        help="dedicated .wiki-viva/fixture-output/<id> child",
    )

    for name in ("install", "upgrade"):
        command = commands.add_parser(name, help=f"{name} a pack")
        command.add_argument("pack")
        command.add_argument("--version")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--branch", help="already checked-out wiki/* review branch")

    for name in ("disable", "remove"):
        command = commands.add_parser(name, help=f"{name} an installed pack")
        command.add_argument("pack")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--branch", help="already checked-out wiki/* review branch")
    return parser


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    registry = args.registry
    if registry is not None and not registry.is_absolute():
        registry = root / registry
    try:
        if args.command == "list":
            payload = list_packs(root, registry_path=registry)
        elif args.command == "inspect":
            payload = inspect_pack(root, args.pack, version=args.version, registry_path=registry)
        elif args.command == "preview":
            payload = preview_pack(root, args.pack, version=args.version, registry_path=registry)
        elif args.command == "validate":
            if args.all:
                if args.pack is not None or args.version is not None:
                    raise PackError("validate_all_rejects_pack_or_version")
                registered = load_registry(root, registry)
                sources = []
                for pack_id, record in sorted(registered["packs"].items()):
                    for version in sorted(record["versions"]):
                        source = resolve_pack(
                            root,
                            pack_id,
                            version=version,
                            registry_path=registry,
                        )
                        sources.append(
                            {
                                "id": source.pack_id,
                                "version": source.version,
                                "tree_sha256": source.tree_sha256,
                            }
                        )
                installation = validate_installation(root)
                payload = {
                    "schema_version": "wiki_experience_pack_validation.v1",
                    "status": "valid" if not installation["errors"] else "invalid",
                    "sources": sources,
                    "installation": installation,
                    "errors": installation["errors"],
                }
            else:
                if args.pack is None:
                    raise PackError("validate_requires_pack_or_all")
                # Validate the immutable source first.  If installed, validate
                # its pinned bundle and the whole active composition as well.
                source = resolve_pack(root, args.pack, version=args.version, registry_path=registry)
                installed = validate_installation(root, args.pack)
                if installed["errors"] and installed["errors"] != [
                    {"code": "pack_not_installed", "pack": args.pack}
                ]:
                    payload = installed
                else:
                    payload = {
                        "schema_version": "wiki_experience_pack_validation.v1",
                        "status": "valid",
                        "source": {
                            "id": source.pack_id,
                            "version": source.version,
                            "tree_sha256": source.tree_sha256,
                        },
                        "installation": "not_installed" if installed["errors"] else installed,
                        "errors": [],
                    }
        elif args.command == "compile-fixture":
            output = args.output
            if not output.is_absolute():
                output = root / output
            payload = compile_pack_fixture(
                root,
                args.pack,
                args.fixture,
                output,
                registry_path=registry,
            )
        elif args.command == "install":
            payload = install_pack(
                root,
                args.pack,
                version=args.version,
                registry_path=registry,
                dry_run=args.dry_run,
                branch=args.branch,
            )
        elif args.command == "upgrade":
            payload = upgrade_pack(
                root,
                args.pack,
                version=args.version,
                registry_path=registry,
                dry_run=args.dry_run,
                branch=args.branch,
            )
        elif args.command == "disable":
            payload = disable_pack(
                root,
                args.pack,
                dry_run=args.dry_run,
                branch=args.branch,
            )
        elif args.command == "remove":
            payload = remove_pack(
                root,
                args.pack,
                dry_run=args.dry_run,
                branch=args.branch,
            )
        else:  # pragma: no cover - argparse makes this unreachable
            raise PackError("unsupported_pack_action")
    except PackError as exc:
        _print(
            {
                "schema_version": "wiki_experience_pack_error.v1",
                "status": "blocked",
                "error": {"code": exc.code, "detail": exc.detail},
            }
        )
        return 2
    except (OSError, ValueError, TypeError):
        # Do not echo arbitrary exception strings: they may include a local
        # path, parsed input or credential-shaped material.
        _print(
            {
                "schema_version": "wiki_experience_pack_error.v1",
                "status": "blocked",
                "error": {"code": "unexpected_safe_failure", "detail": ""},
            }
        )
        return 2
    _print(payload)
    return 1 if payload.get("status") == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
