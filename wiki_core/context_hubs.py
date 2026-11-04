"""Shared editorial hub discovery; never context-policy authority or read grants."""
from pathlib import Path
from wiki_core.traversal import wiki_markdown_files
from wiki_core.config import WikiConfig
from wiki_core.frontmatter import parse_frontmatter


def context_memory_root(root: Path, config: WikiConfig) -> Path | None:
    """Validate the configured editorial subtree without reading page bodies."""
    value = config.paths["memory_root"]
    if not isinstance(value, str) or not value:
        return None
    prefix = value.rstrip("/") + "/"
    base = root / prefix
    configured = Path(value)
    if (configured.is_absolute() or ".." in configured.parts or not configured.parts
        or value != configured.as_posix()
        or base.is_symlink() or not base.resolve().is_relative_to(root.resolve())
        or any(parent.is_symlink() for parent in base.parents if parent != root and root in parent.parents)):
        return None
    return base


def is_editorial_context_hub(values: dict, context: str) -> bool:
    """Qualify authored metadata; filenames and diagnostic fallbacks are not identity."""
    page_id = values.get("page_id")
    return (values.get("page_type") == "context_hub"
            and values.get("context") == context
            and isinstance(page_id, str) and bool(page_id.strip())
            and not any(ord(char) < 32 for char in page_id))


def discover_context_hubs(root: Path, config: WikiConfig, *, contexts=None,
                          read_page=parse_frontmatter) -> tuple[dict[str, list[str]], list[str]]:
    """Resolve authored context_hub identities and same-context moc_parent roots.

    Missing identities retain the conventional relative path for the auditor's
    missing-primary-page gate. Consumers must check existence/type and errors.
    Ambiguity/cycles never authorize a consumer to choose an arbitrary hub.
    """
    prefix = str(config.paths["memory_root"]).rstrip("/") + "/"
    by_context: dict[str, dict[str, str | None]] = {context: {} for context in (contexts if contexts is not None else config.contexts)}
    base = root / prefix
    errors: list[str] = []
    if context_memory_root(root, config) is None:
        return {}, ["unsafe context memory root"]
    for path in sorted(wiki_markdown_files(base, wiki_root=root)) if base.is_dir() else []:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and root in parent.parents):
            continue
        values, _ = read_page(path)
        context = values.get("context")
        if (isinstance(context, str) and context in by_context
                and is_editorial_context_hub(values, context)):
            parent = values.get("moc_parent")
            by_context[context][path.relative_to(root).as_posix()] = parent if isinstance(parent, str) else None
    pages: dict[str, list[str]] = {}
    for context, hubs in by_context.items():
        identity_path = Path(context)
        if identity_path.is_absolute() or ".." in identity_path.parts or not identity_path.parts:
            errors.append("unsafe editorial context identity")
            continue
        # A same-context parent identifies an internal hub; a parent in an
        # outside this context (or no parent) leaves this hub a root candidate.
        matches = [path for path, parent in hubs.items() if parent not in hubs]
        for path in hubs:
            seen: set[str] = set()
            current = path
            while current in hubs:
                if current in seen:
                    errors.append(f"context {context}: cyclic context hub ancestry: {path}")
                    break
                seen.add(current)
                current = hubs[current]
        if len(matches) > 1:
            errors.append(f"context {context}: multiple context hubs: {', '.join(matches)}")
        if hubs and not matches:
            errors.append(f"context {context}: no root context hub")
        if matches:
            pages[context] = matches
        else:
            fallback = root / f"{prefix}{context}/index.md"
            if any(part.is_symlink() for part in (fallback, *fallback.parents) if part != root and root in part.parents):
                errors.append(f"context {context}: unsafe context hub path")
            else:
                pages[context] = [fallback.relative_to(root).as_posix()]
    return pages, errors
