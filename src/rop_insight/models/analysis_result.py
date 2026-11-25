"""Analysis contracts. Image and configuration snapshots belong to one run."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from PyQt6.QtGui import QImage


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ModuleState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class ImageContext:
    image_id: str
    image: QImage
    source: str

    @classmethod
    def from_document(cls, document):
        return cls(str(uuid4()), document.image.copy(), str(document.path))


@dataclass(frozen=True)
class MaskData:
    """Original-image aligned H×W uint8 binary mask, without row padding."""
    structure: str
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class ClassificationData:
    # Canonical order: Normal, Stage 1, Stage 2, Stage 3.
    probabilities: tuple[float, float, float, float]


@dataclass(frozen=True)
class AnalysisOutput:
    """Validated JSON plus immutable original-aligned display results."""
    values: dict
    masks: tuple[MaskData, ...] = ()
    classification: ClassificationData | None = None


@dataclass(frozen=True)
class ModuleError:
    code: str
    message: str


@dataclass
class ModuleResult:
    module_id: str
    state: ModuleState = ModuleState.PENDING
    elapsed_seconds: float = 0.0
    output: AnalysisOutput | None = None
    error: ModuleError | None = None
    model_version: str | None = None


@dataclass
class AnalysisRun:
    run_id: str
    image_id: str
    config: object
    modules: dict[str, ModuleResult]
    schema_version: int = 1
    started_at: str = field(default_factory=timestamp)
    finished_at: str | None = None
    software_version: str = "unknown"
    status: str = "running"
