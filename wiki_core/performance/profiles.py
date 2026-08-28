from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .models import PerformanceContractError, sha256_value


@dataclass(frozen=True)
class FixtureProfile:
    name: str
    pages: int
    relations: int
    events: int
    soak_iterations: int
    estimated_browsers: int
    estimated_cpu_cores: int
    estimated_memory_bytes: int
    estimated_disk_bytes: int
    estimated_duration_seconds: int
    heavy: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        return sha256_value(self.to_dict())


PROFILES = {
    "cycle1": FixtureProfile(
        "cycle1", 100, 1_000, 100, 1, 2, 2, 512 * 1024**2, 64 * 1024**2, 180, False
    ),
    "standard": FixtureProfile(
        "standard", 1_000, 10_000, 10_000, 1, 2, 4, 2 * 1024**3, 512 * 1024**2, 1_200, True
    ),
    "stress": FixtureProfile(
        "stress", 10_000, 100_000, 100_000, 1, 2, 8, 8 * 1024**3, 4 * 1024**3, 7_200, True
    ),
    "soak": FixtureProfile(
        "soak", 10_000, 100_000, 100_000, 12, 2, 8, 10 * 1024**3, 8 * 1024**3, 43_200, True
    ),
}


def profile_for(name: str) -> FixtureProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise PerformanceContractError(f"unknown performance profile: {name}") from exc
