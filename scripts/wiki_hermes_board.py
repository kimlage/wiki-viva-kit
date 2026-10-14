#!/usr/bin/env python3
"""Install the optional Hermes Desktop view; no action copies or agent hooks."""
from __future__ import annotations
import argparse
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit


def validate_board_url(value: str) -> str:
    parsed = urlsplit(value)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        local = False
        port = None
    if (parsed.scheme != "http" or not local or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"/board", "/board/"}
            or port == 0):
        raise ValueError("Board URL must be a loopback HTTP /board URL without credentials, query or fragment")
    return value


def install(template: Path, destination: Path, url: str) -> Path:
    url = validate_board_url(url)
    source = template.read_text(encoding="utf-8")
    if source.count("'__WIKI_BOARD_URL__'") != 1:
        raise ValueError("Invalid board template")
    content = source.replace("'__WIKI_BOARD_URL__'", json.dumps(url))
    target = destination / "wiki-viva-board" / "plugin.js"
    if target.exists() and target.read_text(encoding="utf-8") != content:
        raise FileExistsError("Existing plugin differs; preserve and review it before replacing")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--plugins-dir", type=Path, default=Path.home() / ".hermes/desktop-plugins")
    args = parser.parse_args()
    template = Path(__file__).resolve().parents[1] / "docs/references/templates/deploy/hermes/plugin.js"
    print(install(template, args.plugins_dir, args.url))


if __name__ == "__main__":
    main()
