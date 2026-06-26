"""Reusable Markdown/Git wiki toolkit."""

from .config import WikiConfig, load_config
from .paths import WikiPaths

__version__ = "6.8.7"

__all__ = ["WikiConfig", "WikiPaths", "__version__", "load_config"]
