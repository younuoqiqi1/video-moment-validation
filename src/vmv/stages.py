"""Stage abstractions and result structures."""

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class StageResult:
    stage: str
    status: str  # e.g., "passed", "failed", "blocked"
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
