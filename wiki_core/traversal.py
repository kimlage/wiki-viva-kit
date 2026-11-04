"""Local wiki traversal without crossing a nested Git repository.

A wiki node is still visited; a child directory with its own .git file or
folder is a separate repository, regardless of the parent's ignore rules.
The selected traversal root itself may be a repository root. Symlinked files
and directories are never followed. This controls discovery, not permissions.
"""
from __future__ import annotations

import os
from pathlib import Path


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


def wiki_files(base: Path, *, wiki_root: Path | None = None, suffix: str | None = None) -> list[Path]:
    """Return regular files under base, pruning nested Git roots.

    If ``wiki_root`` is supplied, check every component between that root and
    base too, so selecting a subdirectory inside a clone does not bypass the
    boundary. A separately selected repository can be traversed as its own root.
    """
    base = Path(base)
    if '..' in base.parts or (wiki_root is not None and '..' in Path(wiki_root).parts):
        return []
    if base.is_symlink() or not base.is_dir():
        return []
    if wiki_root is not None:
        root = Path(wiki_root).absolute()
        try:
            relative = base.absolute().relative_to(root)
        except ValueError:
            return []
        current = root
        for name in relative.parts:
            current /= name
            if current.is_symlink() or os.path.lexists(current / '.git'):
                return []
    def fail(error: OSError) -> None:
        raise error
    result: list[Path] = []
    for directory, subdirs, files in os.walk(base, followlinks=False, onerror=fail):
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
