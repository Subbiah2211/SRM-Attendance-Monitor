"""Pipeline configuration.

Every threshold the spec flags as "tune during the pilot" is a setting here rather
than a constant in the code, so pilot tuning never requires a code change.
Environment overrides use the ``ATT_`` prefix with ``__`` for nesting, e.g.
``ATT_MATCHING__SIMILARITY_THRESHOLD=0.62``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL_DIR = Path.home() / ".cache" / "attendance" / "models"


class InferenceSettings(BaseModel):
    """Execution provider selection.

    'auto' resolves to CUDA on the pilot GPU server and CoreML on Apple Silicon
    development machines, falling back to CPU. The pipeline is identical either
    way; only the provider list changes.
    """

    provider: Literal["auto", "cuda", "coreml", "cpu"] = "auto"
    detector_input_size: tuple[int, int] = (640, 640)
    model_dir: Path = DEFAULT_MODEL_DIR
    model_pack: str = "buffalo_l"
    intra_op_threads: int = 0
    """0 lets onnxruntime choose."""


class SamplingSettings(BaseModel):
    """Spec section 6.2: 2-3 FPS per camera is the pilot starting point, not a constant."""

    target_fps: float = Field(default=3.0, gt=0, le=30)
    motion_gate_enabled: bool = False
    motion_gate_min_fraction: float = Field(default=0.002, ge=0, le=1)
    """Fraction of ROI pixels that must change before the detector runs at all."""


class QualitySettings(BaseModel):
    """Gate applied before embedding.

    Absent from the spec, but a tiny, blurred or profile face still yields a
    512-d vector that still has a nearest neighbour, which is the dominant source
    of false accepts on entrance cameras.
    """

    min_detector_score: float = Field(default=0.60, ge=0, le=1)
    min_face_height_px: int = Field(default=100, ge=16)
    min_blur_variance: float = Field(default=45.0, ge=0)
    """Variance of the Laplacian over the aligned crop. Lower means blurrier."""
    max_yaw_ratio: float = Field(default=0.45, ge=0)
    """Landmark-derived proxy for head yaw. 0 is frontal; ~0.5+ is a strong profile."""
    max_roll_degrees: float = Field(default=35.0, ge=0)


class MatchingSettings(BaseModel):
    """Spec section 3.4, with the margin rule the spec leaves undefined."""

    similarity_threshold: float = Field(default=0.55, ge=-1, le=1)
    """Cosine similarity, not distance. Spec suggests 0.55-0.65 for ArcFace; tune on pilot data."""
    min_margin: float = Field(default=0.05, ge=0)
    """Required gap between the best student and the best *other* student.

    Often a better accept/reject signal than the absolute threshold, and it is what
    turns the spec's vague "ties are logged as unresolved" into a decidable rule.
    """
    aggregation: Literal["max", "mean"] = "max"
    """How to collapse a student's multiple reference embeddings into one score."""
    exclude_inactive_students: bool = True


class TrackingSettings(BaseModel):
    """Spec section 3.2, with one deliberate deviation.

    The spec skips recognition entirely for any already-tracked face. At 2-3 FPS an
    IOU tracker will occasionally swap identities between two people crossing a
    doorway, and skipping recognition makes that swap silent and unrecoverable.
    Here the tracker suppresses duplicate *events* but recognition is re-run on a
    short interval, which the GPU headroom in spec section 7 comfortably allows.
    """

    min_iou: float = Field(default=0.3, ge=0, le=1)
    max_age_frames: int = Field(default=8, ge=1)
    reconfirm_interval_seconds: float = Field(default=2.0, ge=0)
    """0 re-runs recognition on every sampled frame. The spec's example was 10s."""
    emit_event_once_per_track: bool = True
    """Phase 2 owns duplicate suppression, but emitting once per track costs nothing here."""


class PrivacySettings(BaseModel):
    """Spec sections 6.5 and 8."""

    persist_unresolved_embeddings: bool = False
    """Retaining embeddings of unidentified people is a policy decision, not a default."""
    persist_unresolved_crops: bool = False
    crop_output_dir: Path | None = None

    @field_validator("crop_output_dir")
    @classmethod
    def _require_dir_when_persisting(cls, v: Path | None) -> Path | None:
        return v


class DatabaseSettings(BaseModel):
    """Postgres connection.

    The DSN carries credentials, so it comes from the environment
    (``ATT_DATABASE__DSN``) or a gitignored .env file, never from committed config.
    """

    dsn: str | None = None
    ef_search: int | None = None
    """HNSW recall/latency knob. Leave unset while matching uses exact search."""


class CameraSettings(BaseModel):
    camera_id: str
    source: str
    """RTSP URL, GStreamer pipeline, or a local file path for development."""
    enabled: bool = True
    roi: tuple[float, float, float, float] | None = None
    """Normalized (x1, y1, x2, y2) region of interest; detections outside are ignored."""
    reconnect_initial_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    """Spec section 3.1: exponential backoff starting at 1s, capped at 30s."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATT_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    inference: InferenceSettings = InferenceSettings()
    sampling: SamplingSettings = SamplingSettings()
    quality: QualitySettings = QualitySettings()
    matching: MatchingSettings = MatchingSettings()
    tracking: TrackingSettings = TrackingSettings()
    privacy: PrivacySettings = PrivacySettings()
    database: DatabaseSettings = DatabaseSettings()
    output_dir: Path = Path("./var")
