from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wiki_core.config import WikiConfig, freshness_for
from wiki_core.ids import slugify
from wiki_core.page_types import PageTypeRegistry

TEMPLATE_VERSION = "1"


@dataclass(frozen=True)
class ResolvedTemplate:
    page_type: str
    template_path: str
    overlay_path: str | None
    template_id: str
    template_version: str
    text: str


def _override_for(config: WikiConfig, page_type: str) -> dict[str, Any]:
    overrides = config.templates.get("page_type_overrides") or {}
    value = overrides.get(page_type) if isinstance(overrides, dict) else None
    return value if isinstance(value, dict) else {}


def _template_path(config: WikiConfig, registry: PageTypeRegistry, page_type: str) -> str:
    shape = registry.page_types[page_type]
    # Pack templates are immutable installed artifacts. A local overlay or
    # page-type override must never redirect creation outside the verified
    # bundle pinned by wiki.packs.lock.yaml.
    if isinstance(shape.get("experience_pack"), dict):
        return str(shape.get("template") or "")
    override = _override_for(config, page_type)
    if override.get("template"):
        return str(override["template"])
    return str(shape.get("template") or "")


def _overlay_path(config: WikiConfig, page_type: str) -> str | None:
    override = _override_for(config, page_type)
    overlay = override.get("overlay")
    return str(overlay) if overlay else None


def _template_body(raw: str) -> str:
    match = re.search(r"```yaml\n(.*?)\n```\n?(.*)", raw, re.S)
    if match:
        frontmatter = match.group(1).strip()
        if frontmatter.startswith("---"):
            frontmatter = frontmatter[3:].strip()
        if frontmatter.endswith("---"):
            frontmatter = frontmatter[:-3].strip()
        body = match.group(2).strip()
        return f"---\n{frontmatter}\n---\n\n{body}\n"
    return raw


def resolve_template(
    root: Path,
    config: WikiConfig,
    registry: PageTypeRegistry,
    page_type: str,
) -> ResolvedTemplate:
    if page_type not in registry.page_types:
        raise ValueError(f"unknown page_type: {page_type}")
    template_path = _template_path(config, registry, page_type)
    if not template_path or template_path == "none":
        raise ValueError(f"page_type {page_type!r} has no instantiable template")
    base_file = root / template_path
    if not base_file.exists():
        raise FileNotFoundError(template_path)
    shape = registry.page_types[page_type]
    pack = shape.get("experience_pack")
    if isinstance(pack, dict):
        try:
            relative = base_file.relative_to(root)
            base_file.resolve(strict=False).relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"installed pack template escaped repository for {page_type!r}") from exc
        current = root
        has_symlink = False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                has_symlink = True
                break
        if not base_file.is_file() or has_symlink:
            raise ValueError(f"installed pack template unavailable for {page_type!r}")
        raw = base_file.read_bytes()
        if (
            len(raw) != pack.get("template_size")
            or hashlib.sha256(raw).hexdigest() != pack.get("template_sha256")
        ):
            raise ValueError(f"installed pack template drift for {page_type!r}")
        overlay_path = None
        template_id = f"{pack.get('id')}:{page_type}"
        template_version = str(pack.get("version") or "")
        text = _template_body(raw.decode("utf-8"))
    else:
        overlay_path = _overlay_path(config, page_type)
        template_id = f"{page_type}-default"
        template_version = TEMPLATE_VERSION
        text = _template_body(base_file.read_text(encoding="utf-8"))
    if overlay_path:
        overlay_file = root / overlay_path
        if not overlay_file.exists():
            raise FileNotFoundError(overlay_path)
        text = text.rstrip() + "\n\n" + overlay_file.read_text(encoding="utf-8").strip() + "\n"
    return ResolvedTemplate(
        page_type=page_type,
        template_path=template_path,
        overlay_path=overlay_path,
        template_id=template_id,
        template_version=template_version,
        text=text,
    )


def instantiate_template(
    resolved: ResolvedTemplate,
    *,
    title: str,
    context: str,
    config: WikiConfig,
    today: dt.date | None = None,
) -> str:
    today = today or dt.date.today()
    page_id = f"{resolved.page_type}-{slugify(title)}"
    replacements = {
        "page_id": page_id,
        "page_type": resolved.page_type,
        "title": title,
        "context": context,
        # Core templates historically used this placeholder without a matching
        # renderer value.  Besides leaking template syntax into new pages,
        # ``owner: {{owner_id}}`` is not valid YAML and makes every nested
        # frontmatter object disappear when the canonical parser fails closed.
        # The configured owner label is the only portable owner identity
        # available at creation time; slugging it keeps the scalar YAML-safe.
        "owner_id": slugify(config.owner_label),
        "updated_at": today.isoformat(),
        "stale_after_days": str(freshness_for(context, resolved.page_type, config)),
        "template_id": resolved.template_id,
        "template_version": resolved.template_version,
    }
    text = resolved.text
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    lines = text.splitlines()
    if lines and lines[0] == "---":
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            end = -1
        if end > 0:
            fm = lines[:end]
            body = lines[end:]
            present = {line.split(":", 1)[0].strip() for line in fm if ":" in line}
            override_keys = set(replacements)
            fm = [
                f"{line.split(':', 1)[0].strip()}: {replacements[line.split(':', 1)[0].strip()]}"
                if ":" in line and line.split(":", 1)[0].strip() in override_keys
                else line
                for line in fm
            ]
            additions = []
            for key, value in replacements.items():
                if key not in present:
                    additions.append(f"{key}: {value}")
            if "template_ref" not in present:
                additions.append(f"template_ref: {resolved.template_path}")
            if resolved.overlay_path and "template_overlay" not in present:
                additions.append(f"template_overlay: {resolved.overlay_path}")
            lines = [*fm, *additions, *body]
            text = "\n".join(lines) + "\n"
    return text


def default_output_path(registry: PageTypeRegistry, page_type: str, title: str) -> str:
    shape = registry.page_types[page_type]
    dirs = shape.get("allowed_dirs") or []
    if not dirs:
        raise ValueError(f"page_type {page_type!r} has no allowed_dirs")
    return f"{str(dirs[0]).rstrip('/')}/{slugify(title)}.md"
