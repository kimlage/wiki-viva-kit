"""Reproducible, fail-closed performance evidence for Wiki Viva.

The package is deliberately separate from release and migration machinery.
It measures public synthetic fixtures and writes all run evidence outside the
Git subject.
"""

from .models import HARNESS_VERSION, PLAN_SCHEMA_VERSION, RECEIPT_SCHEMA_VERSION
from .runner import PerformanceRunner

__all__ = [
    "HARNESS_VERSION",
    "PLAN_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "PerformanceRunner",
]
