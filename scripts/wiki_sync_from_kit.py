#!/usr/bin/env python3
"""Idempotent downstream sync for Wiki Viva Kit-owned files.

The command deliberately has only two operating modes:

* ``--dry-run`` prints B0 and never mutates the consumer;
* apply performs C1, then configured C2 generators, then explicit C3 commands.

The consumer PR is the review, rollback and promotion boundary.  ``kit.lock``
records the exact source and managed-file state without host paths or evidence.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


DEFAULT_MANIFEST = Path("docs/references/upgrades/sync-manifest.yaml")
LOCK_NAME = "kit.lock"


class SyncError(RuntimeError):
    """Expected operator-facing sync failure."""


def _run(argv: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SyncError(f"command failed ({shlex.join(argv)}): {detail}")
    return result


def _check_source(kit: Path, sha: str) -> None:
    """Keep the selected Git revision stable during sync."""
    current = _run(["git", "rev-parse", "HEAD"], cwd=kit).stdout.strip()
    if current != sha:
        raise SyncError("kit source revision changed; SHA-backed sync refused")


def _check_consumer_root(consumer: Path) -> None:
    top = _run(["git", "rev-parse", "--show-toplevel"], cwd=consumer).stdout.strip()
    if Path(top).resolve() != consumer.resolve():
        raise SyncError("consumer path must be its Git root")


def _check_distinct_roots(kit: Path, consumer: Path) -> None:
    kit_root = _run(["git", "rev-parse", "--show-toplevel"], cwd=kit).stdout.strip()
    consumer_root = _run(["git", "rev-parse", "--show-toplevel"], cwd=consumer).stdout.strip()
    if Path(kit_root).resolve() == Path(consumer_root).resolve():
        raise SyncError("kit and consumer must be different Git worktree roots")


def _check_consumer_path(consumer: Path, rel: str) -> None:
    """Refuse paths outside the consumer or through another Git worktree."""
    if (not isinstance(rel, str) or not rel or "\\" in rel or Path(rel).is_absolute()
            or any(part in ("", ".", "..", ".git") for part in rel.split("/"))):
        raise SyncError("unsafe consumer path")
    current = consumer
    for part in rel.split("/"):
        current = current / part
        if current.is_symlink():
            raise SyncError("consumer path crosses a symlink")
        if os.path.lexists(current / ".git"):
            raise SyncError("consumer path crosses a nested repository")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(payload.encode("utf-8"))


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SyncError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"{path.name} must contain a YAML mapping")
    return value


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.strip("/")
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        ancestors = ("/".join(path.split("/")[:depth]) for depth in range(1, path.count("/") + 2))
        return any(fnmatch.fnmatchcase(ancestor, prefix) for ancestor in ancestors)
    # Manifest patterns are repository-root-relative. PurePosixPath.match()
    # treats a bare filename as a basename match at any depth, which made a
    # root-only block such as ``wiki.config.yaml`` also remove the demo's own
    # self-contained fixture registry.
    return fnmatch.fnmatchcase(path, pattern)


def _validate_manifest(value: dict[str, Any]) -> None:
    if value.get("schema_version") != "wiki_viva_sync_manifest.v1":
        raise SyncError("sync manifest must use wiki_viva_sync_manifest.v1")
    portable = value.get("portable")
    if not isinstance(portable, dict) or not portable.get("allow"):
        raise SyncError("sync manifest portable.allow must be a non-empty list")
    for key in ("allow", "block"):
        patterns = portable.get(key, [])
        if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
            raise SyncError(f"sync manifest portable.{key} must be a list of strings")
    c2 = value.get("c2_commands", [])
    if not isinstance(c2, list) or not all(isinstance(item, list) and item for item in c2):
        raise SyncError("sync manifest c2_commands must be a list of argv lists")


def _git_bytes(kit: Path, *args: str, data: bytes | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=kit, input=data, capture_output=True)
    if result.returncode:
        raise SyncError("kit Git content unavailable")
    return result.stdout


def _tracked_files(kit: Path, manifest: dict[str, Any], sha: str) -> dict[str, dict[str, Any]]:
    raw = _git_bytes(kit, "ls-tree", "-r", "-z", sha).decode("utf-8")
    allowed = manifest["portable"]["allow"]
    blocked = manifest["portable"].get("block", [])
    selected: dict[str, dict[str, Any]] = {}
    for record in raw.split("\0"):
        if not record:
            continue
        meta, path = record.split("\t", 1)
        mode, kind, blob = meta.split()
        if not any(_matches(path, pattern) for pattern in allowed):
            continue
        if any(_matches(path, pattern) for pattern in blocked):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise SyncError(f"portable selection refuses non-regular file {path} ({mode})")
        selected[path] = {"blob": blob, "mode": mode}
    if not selected:
        raise SyncError("portable selection is empty")
    batch = _git_bytes(kit, "cat-file", "--batch", data="".join(
        item["blob"] + "\n" for item in selected.values()).encode("ascii"))
    offset = 0
    for item in selected.values():
        end = batch.find(b"\n", offset)
        if end < 0:
            raise SyncError("kit Git content incomplete")
        fields = batch[offset:end].split()
        if len(fields) != 3 or fields[0].decode("ascii") != item["blob"] or fields[1] != b"blob" or not fields[2].isdigit():
            raise SyncError("kit Git content invalid")
        size = int(fields[2])
        payload = batch[end + 1:end + 1 + size]
        offset = end + 1 + size
        if len(payload) != size or batch[offset:offset + 1] != b"\n":
            raise SyncError("kit Git content incomplete")
        offset += 1
        item.pop("blob")
        item.update(sha256=_sha256_bytes(payload), size=size, payload=payload)
    if offset != len(batch):
        raise SyncError("kit Git content invalid")
    return dict(sorted(selected.items()))


def _load_lock(consumer: Path) -> dict[str, Any]:
    path = consumer / LOCK_NAME
    if path.is_symlink():
        raise SyncError("kit.lock cannot be a symlink")
    if not path.exists():
        return {}
    value = _load_yaml(path)
    if value.get("schema_version") != "wiki_viva_kit_lock.v1":
        raise SyncError("existing kit.lock has an unsupported schema_version")
    return value


def _consumer_state(consumer: Path, paths: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for rel in paths:
        path = consumer / rel
        if path.is_symlink():
            state[rel] = {"kind": "symlink"}
        elif path.is_file():
            mode = "100755" if os.access(path, os.X_OK) else "100644"
            state[rel] = {"kind": "file", "sha256": _sha256_bytes(path.read_bytes()), "mode": mode}
        elif path.exists():
            state[rel] = {"kind": "other"}
        else:
            state[rel] = {"kind": "missing"}
    return state


def _git_dirty(root: Path) -> list[str]:
    result = _run(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    return [item for item in result.stdout.split("\0") if item]


def build_plan(kit: Path, consumer: Path, manifest_path: Path, c3_commands: list[list[str]]) -> dict[str, Any]:
    _check_consumer_root(consumer)
    _check_distinct_roots(kit, consumer)
    try:
        manifest_rel = manifest_path.relative_to(kit).as_posix()
    except ValueError as exc:
        raise SyncError("sync manifest must belong to the kit") from exc
    source_sha = _run(["git", "rev-parse", "HEAD"], cwd=kit).stdout.strip()
    _check_source(kit, source_sha)
    try:
        manifest = yaml.safe_load(_git_bytes(kit, "show", f"{source_sha}:{manifest_rel}"))
    except yaml.YAMLError as exc:
        raise SyncError("sync manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise SyncError("sync manifest must contain a YAML mapping")
    _validate_manifest(manifest)
    files = _tracked_files(kit, manifest, source_sha)
    previous = _load_lock(consumer).get("managed_files", {})
    if not isinstance(previous, dict):
        raise SyncError("kit.lock managed_files must be a mapping")
    for rel in set(files) | set(previous):
        _check_consumer_path(consumer, rel)
    current = _consumer_state(consumer, {**files, **previous})

    added: list[str] = []
    changed: list[str] = []
    unchanged: list[str] = []
    for rel, expected in files.items():
        actual = current[rel]
        if actual["kind"] == "missing":
            added.append(rel)
        elif actual.get("sha256") == expected["sha256"] and actual.get("mode") == expected["mode"]:
            unchanged.append(rel)
        else:
            if rel not in previous:
                raise SyncError(f"unmanaged consumer file conflicts: {rel}")
            old = previous[rel]
            if not isinstance(old, dict) or actual.get("sha256") != old.get("sha256") or actual.get("mode") != old.get("mode"):
                raise SyncError(f"previously managed consumer file changed: {rel}")
            changed.append(rel)
    removed = sorted(set(previous) - set(files))
    for rel in removed:
        actual, old = current[rel], previous[rel]
        if actual["kind"] != "missing" and (not isinstance(old, dict)
                or actual.get("sha256") != old.get("sha256") or actual.get("mode") != old.get("mode")):
            raise SyncError(f"previously managed consumer file changed: {rel}")
    _check_source(kit, source_sha)
    tree = [{"path": rel, "sha256": item["sha256"], "mode": item["mode"]} for rel, item in files.items()]
    return {
        "schema_version": "wiki_viva_sync_plan.v1",
        "mode": "B0_dry_run",
        "source_sha": source_sha,
        "manifest_sha256": _canonical_sha256(manifest),
        "portable_tree_sha256": _canonical_sha256(tree),
        "consumer_dirty": _git_dirty(consumer),
        "c1": {
            "managed_total": len(files),
            "add": added,
            "change": changed,
            "remove_previously_managed": removed,
            "unchanged": len(unchanged),
        },
        "c2_commands": manifest.get("c2_commands", []),
        "c3_commands": c3_commands,
        "_files": files,
        "_manifest": manifest,
        "_consumer_state": current,
    }


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if not key.startswith("_")}


def _print_plan(plan: dict[str, Any], *, as_json: bool) -> None:
    public = _public_plan(plan)
    if as_json:
        print(json.dumps(public, indent=2, ensure_ascii=False, sort_keys=True))
        return
    c1 = public["c1"]
    print(f"B0 source: {public['source_sha']}")
    print(
        "C1 managed={managed_total} add={add} change={change} remove={remove} unchanged={unchanged}".format(
            managed_total=c1["managed_total"], add=len(c1["add"]), change=len(c1["change"]),
            remove=len(c1["remove_previously_managed"]), unchanged=c1["unchanged"]
        )
    )
    for label, key in (("+", "add"), ("~", "change"), ("-", "remove_previously_managed")):
        for path in c1[key]:
            print(f"  {label} {path}")
    for argv in public["c2_commands"]:
        print(f"C2: {shlex.join(argv)}")
    if public["c3_commands"]:
        for argv in public["c3_commands"]:
            print(f"C3: {shlex.join(argv)}")
    else:
        print("C3: no consumer-owned command declared")
    if public["consumer_dirty"]:
        print(f"NOTICE: consumer has {len(public['consumer_dirty'])} dirty entry/entries")


def _copy_c1(kit: Path, consumer: Path, plan: dict[str, Any]) -> None:
    _check_consumer_root(consumer)
    _check_distinct_roots(kit, consumer)
    _check_source(kit, plan["source_sha"])
    files = plan["_files"]
    affected = plan["c1"]["remove_previously_managed"] + plan["c1"]["add"] + plan["c1"]["change"]
    for rel in affected:
        _check_consumer_path(consumer, rel)
    if _consumer_state(consumer, {rel: {} for rel in affected}) != {
            rel: plan["_consumer_state"][rel] for rel in affected}:
        raise SyncError("consumer changed after B0; review the plan again")
    for rel in plan["c1"]["remove_previously_managed"]:
        _check_consumer_path(consumer, rel)
        target = consumer / rel
        if target.is_symlink() or target.is_file():
            target.unlink()
    for rel in plan["c1"]["add"] + plan["c1"]["change"]:
        _check_consumer_path(consumer, rel)
        target = consumer / rel
        if target.exists() and not target.is_file():
            raise SyncError(f"C1 refuses to replace non-file path: {rel}")
        if target.is_symlink():
            raise SyncError(f"C1 refuses to replace symlink: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".wiki-sync-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(files[rel]["payload"])
                stream.flush()
            os.chmod(temp_name, 0o755 if files[rel]["mode"] == "100755" else 0o644)
            _check_consumer_path(consumer, rel)
            before = plan["_consumer_state"][rel]
            if _consumer_state(consumer, {rel: {}})[rel] != before:
                raise SyncError(f"consumer target changed before write: {rel}")
            if before["kind"] == "missing":
                # Linking a prepared file fails atomically if a new destination
                # appeared since the state check; replace would overwrite it.
                try:
                    os.link(temp_name, target)
                except FileExistsError as exc:
                    raise SyncError(f"consumer target changed before write: {rel}") from exc
            else:
                os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


def _verify_c1(consumer: Path, plan: dict[str, Any]) -> None:
    """Do not record a lock if C2 or C3 changed the managed C1 files."""
    files = plan["_files"]
    for rel in files:
        _check_consumer_path(consumer, rel)
    state = _consumer_state(consumer, files)
    for rel, expected in files.items():
        actual = state[rel]
        if (actual.get("kind") != "file" or actual.get("sha256") != expected["sha256"]
                or actual.get("mode") != expected["mode"]):
            raise SyncError(f"managed C1 file changed during C2/C3: {rel}")


def _write_lock(consumer: Path, plan: dict[str, Any]) -> None:
    lock = {
        "schema_version": "wiki_viva_kit_lock.v1",
        "source_sha": plan["source_sha"],
        "manifest_sha256": plan["manifest_sha256"],
        "portable_tree_sha256": plan["portable_tree_sha256"],
        "managed_files": {
            rel: {"sha256": item["sha256"], "mode": item["mode"]}
            for rel, item in plan["_files"].items()
        },
    }
    payload = yaml.safe_dump(lock, sort_keys=True, allow_unicode=True)
    fd, temp_name = tempfile.mkstemp(prefix=".kit.lock.", dir=consumer)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, consumer / LOCK_NAME)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _parse_command(raw: str) -> list[str]:
    command = shlex.split(raw)
    if not command:
        raise argparse.ArgumentTypeError("command cannot be empty")
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, default=Path.cwd())
    parser.add_argument("--consumer", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print B0 without mutation")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    parser.add_argument("--allow-dirty", action="store_true", help="allow apply in a dirty consumer")
    parser.add_argument("--c3-command", action="append", default=[], type=_parse_command)
    args = parser.parse_args(argv)

    kit = args.kit.resolve()
    consumer = args.consumer.resolve()
    manifest_path = (args.manifest.resolve() if args.manifest else kit / DEFAULT_MANIFEST)
    try:
        if not (kit / ".git").exists() and _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=kit).stdout.strip() != "true":
            raise SyncError("--kit must be a Git worktree")
        if not consumer.is_dir():
            raise SyncError("--consumer must be an existing directory")
        if _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=consumer).stdout.strip() != "true":
            raise SyncError("--consumer must be a Git worktree")
        plan = build_plan(kit, consumer, manifest_path, args.c3_command)
        _print_plan(plan, as_json=args.json)
        if args.dry_run:
            return 0
        if plan["consumer_dirty"] and not args.allow_dirty:
            raise SyncError("apply requires a clean consumer; review B0 or pass --allow-dirty deliberately")
        _copy_c1(kit, consumer, plan)
        _check_source(kit, plan["source_sha"])
        for command in plan["c2_commands"]:
            _run([str(part) for part in command], cwd=consumer)
        for command in plan["c3_commands"]:
            _run(command, cwd=consumer)
        _check_source(kit, plan["source_sha"])
        _verify_c1(consumer, plan)
        _write_lock(consumer, plan)
        print(f"APPLIED source={plan['source_sha']} managed={len(plan['_files'])} lock={LOCK_NAME}")
        return 0
    except (SyncError, OSError) as exc:
        print(f"wiki_sync_from_kit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
