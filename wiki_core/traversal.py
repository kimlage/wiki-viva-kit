"""Local wiki traversal without crossing a nested Git repository.

A wiki node is still visited; a child directory with its own .git file or
folder is a separate repository, regardless of the parent's ignore rules.
The selected traversal root itself may be a repository root. Symlinked files
and directories are never followed. This controls discovery, not permissions.
"""
from __future__ import annotations

import os
from pathlib import Path


def is_in_nested_git(path: Path, *, wiki_root: Path) -> bool:
    """Check a selected path without crossing a nested Git or symlink boundary."""
    path, wiki_root = Path(path), Path(wiki_root)
    try:
        relative = path.absolute().relative_to(wiki_root.absolute())
    except ValueError:
        raise ValueError('discovery path outside wiki root') from None
    if '..' in relative.parts:
        raise ValueError('unsafe discovery path')
    root = wiki_root.resolve()
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink() or os.path.lexists(current / '.git'):
            return True
    return bool(relative.parts and (root / relative).is_symlink())


def require_wiki_boundaries(wiki_root: Path, *, directories=(), files=()) -> None:
    """Reject selected paths across a nested repository or symlink before use."""
    root = Path(wiki_root)
    absolute_root, resolved_root = root.absolute(), root.resolve()
    def selected(path):
        try:
            relative = Path(path).absolute().relative_to(absolute_root)
        except ValueError:
            raise ValueError('derived_path_crosses_repository_boundary') from None
        if '..' in relative.parts:
            raise ValueError('derived_path_crosses_repository_boundary')
        return resolved_root / relative
    for directory in directories:
        if is_in_nested_git(selected(Path(directory) / '_wiki_boundary_'), wiki_root=resolved_root):
            raise ValueError('derived_path_crosses_repository_boundary')
    for path in files:
        if is_in_nested_git(selected(path), wiki_root=resolved_root):
            raise ValueError('derived_path_crosses_repository_boundary')
def require_wiki_path(root: Path, relative: str) -> Path:
    """Select a local path without crossing symlinks or a nested Git root.

    The supplied root is trusted and may itself be relative. This does not
    authorize access or protect against a concurrent filesystem replacement.
    """
    from wiki_core.context_policy import safe_path
    relative = safe_path(relative, allow_root=True)
    current = Path(root).resolve(strict=True)
    if not current.is_dir():
        raise ValueError('wiki root unavailable')
    if relative == '.':
        return current
    from wiki_core.repository_reader import canonical_path
    canonical_path(relative)
    selected = current / relative
    require_wiki_boundaries(current, directories=(selected,))
    return selected


def reject_nested_git(base: Path, *, include_hidden: bool = True) -> None:
    """Fail a selected directory collection if it contains another repo.

    Selection of the repository root itself remains possible. Failure avoids
    presenting a silently truncated directory capture as complete.
    """
    def fail(error: OSError) -> None:
        raise error
    for directory, subdirs, files in os.walk(base, followlinks=False, onerror=fail):
        current = Path(directory)
        for name in subdirs:
            if name == '.git' or (not include_hidden and name.startswith('.')):
                continue
            path = current / name
            if path.is_symlink():
                raise ValueError('source_directory_symlink: select regular source files')
            if os.path.lexists(path / '.git'):
                raise ValueError('source_directory_nested_repository: select repository explicitly')
        subdirs[:] = [name for name in subdirs if name != '.git' and (include_hidden or not name.startswith('.'))]
        if any((current / name).is_symlink() for name in files if include_hidden or not name.startswith('.')):
            raise ValueError('source_directory_symlink: select regular source files')


def wiki_files(base: Path, *, wiki_root: Path | None = None, suffix: str | None = None,
               max_entries: int | None = None) -> list[Path]:
    """Return regular files under base, pruning nested Git roots.

    If ``wiki_root`` is supplied, check every component between that root and
    base too, so selecting a subdirectory inside a clone does not bypass the
    boundary. A separately selected repository can be traversed as its own root.
    """
    base = Path(base)
    if wiki_root is None and '..' in base.parts:
        return []
    if wiki_root is not None:
        root = Path(wiki_root).absolute()
        try:
            relative = base.absolute().relative_to(root)
        except ValueError:
            return []
        if '..' in relative.parts:
            return []
        current = Path(wiki_root).resolve()
        for name in relative.parts:
            current /= name
            if current.is_symlink() or os.path.lexists(current / '.git'):
                return []
    if base.is_symlink() or not base.is_dir():
        return []
    def fail(error: OSError) -> None:
        raise error
    result: list[Path] = []
    seen_entries = 0
    for directory, subdirs, files in os.walk(base, followlinks=False, onerror=fail):
        seen_entries += len(subdirs) + len(files)
        if max_entries is not None and seen_entries > max_entries:
            raise ValueError('wiki traversal entry limit exceeded')
        current = Path(directory)
        subdirs[:] = sorted(name for name in subdirs
                           if name != '.git'
                           and not (current / name).is_symlink()
                           and not os.path.lexists(current / name / '.git'))
        for name in sorted(files):
            path = current / name
            if name != '.git' and (suffix is None or name.endswith(suffix)) and not path.is_symlink() and path.is_file():
                result.append(path)
    return sorted(result)


def wiki_markdown_files(base: Path, *, wiki_root: Path | None = None) -> list[Path]:
    return wiki_files(base, wiki_root=wiki_root, suffix='.md')
