"""File-backed video source, used for development and offline benchmarking.

Frame timestamps come from the file's presentation time rather than the wall clock,
so replaying the same clip twice produces identical ``captured_at`` values and
accuracy results are reproducible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2

from attendance.types import Frame, SourceMode
from attendance.video.base import VideoSource

_SYNTHETIC_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class FileVideoSource(VideoSource):
    mode = SourceMode.SEQUENTIAL

    def __init__(
        self,
        camera_id: str,
        path: str | Path,
        timeline_start: datetime | None = None,
        loop: bool = False,
    ) -> None:
        self.camera_id = camera_id
        self.path = Path(path)
        self.loop = loop
        self._timeline_start = timeline_start or _SYNTHETIC_EPOCH
        self._capture: cv2.VideoCapture | None = None
        self._sequence = 0
        self._exhausted = False

    @property
    def native_fps(self) -> float | None:
        if self._capture is None:
            return None
        fps = self._capture.get(cv2.CAP_PROP_FPS)
        return float(fps) if fps and fps > 0 else None

    @property
    def frame_count(self) -> int | None:
        """Total frames, or None if the container does not report it."""
        if self._capture is None:
            return None
        count = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
        return int(count) if count and count > 0 else None

    @property
    def duration_seconds(self) -> float | None:
        count, fps = self.frame_count, self.native_fps
        if not count or not fps:
            return None
        return count / fps

    @property
    def is_exhausted(self) -> bool:
        return self._exhausted

    def open(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"video file not found: {self.path}")
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            raise RuntimeError(f"could not open video file: {self.path}")
        self._capture = capture
        self._exhausted = False
        self._sequence = 0

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

    def read(self) -> Frame | None:
        if self._capture is None:
            raise RuntimeError("source not opened")
        ok, image = self._capture.read()
        if not ok:
            if self.loop:
                self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, image = self._capture.read()
            if not ok:
                self._exhausted = True
                return None

        position_ms = self._capture.get(cv2.CAP_PROP_POS_MSEC)
        if position_ms and position_ms > 0:
            captured_at = self._timeline_start + timedelta(milliseconds=position_ms)
        else:
            fps = self.native_fps or 25.0
            captured_at = self._timeline_start + timedelta(seconds=self._sequence / fps)

        frame = Frame(
            camera_id=self.camera_id,
            image=image,
            captured_at=captured_at,
            sequence=self._sequence,
        )
        self._sequence += 1
        return frame
