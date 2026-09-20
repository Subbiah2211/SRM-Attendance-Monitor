"""Frame sampler (spec section 3.2).

Reduces a decoded stream to the detector's working rate. Handles the two source
modes differently because they are genuinely different problems: a file must be
decoded frame by frame to advance, while a live stream should skip to whatever is
newest and let the rest be dropped.

Optional motion gating skips the detector on frames with no change in the region of
interest, which matters for doorway cameras that are empty most of the day.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import cv2
import numpy as np

from attendance.config import SamplingSettings
from attendance.types import Frame, SourceMode
from attendance.video.base import VideoSource


class FrameSampler:
    def __init__(
        self,
        source: VideoSource,
        settings: SamplingSettings,
        roi: tuple[float, float, float, float] | None = None,
    ) -> None:
        self.source = source
        self.settings = settings
        self.roi = roi
        self.interval_seconds = 1.0 / settings.target_fps
        self._previous_gray: np.ndarray | None = None
        self.frames_seen = 0
        self.frames_yielded = 0
        self.frames_motion_gated = 0

    def __iter__(self) -> Iterator[Frame]:
        if self.source.mode is SourceMode.SEQUENTIAL:
            yield from self._iter_sequential()
        else:
            yield from self._iter_latest()

    def _iter_sequential(self) -> Iterator[Frame]:
        """Decode every frame, emit roughly ``target_fps`` of them, evenly spaced."""
        native_fps = self.source.native_fps or 25.0
        stride = max(1, round(native_fps / self.settings.target_fps))
        index = 0
        while True:
            frame = self.source.read()
            if frame is None:
                return
            self.frames_seen += 1
            if index % stride == 0 and self._passes_motion_gate(frame):
                self.frames_yielded += 1
                yield frame
            index += 1

    def _iter_latest(self) -> Iterator[Frame]:
        """Poll the freshest frame on a fixed cadence, dropping anything in between."""
        next_deadline = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_deadline:
                time.sleep(next_deadline - now)
            next_deadline = max(time.monotonic(), next_deadline + self.interval_seconds)

            frame = self.source.read()
            if frame is None:
                if self.source.is_exhausted:
                    return
                continue
            self.frames_seen += 1
            if self._passes_motion_gate(frame):
                self.frames_yielded += 1
                yield frame

    def _passes_motion_gate(self, frame: Frame) -> bool:
        if not self.settings.motion_gate_enabled:
            return True

        region = frame.image
        if self.roi is not None:
            height, width = frame.shape
            x1, y1, x2, y2 = self.roi
            region = frame.image[
                int(y1 * height) : int(y2 * height), int(x1 * width) : int(x2 * width)
            ]
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._previous_gray is None or self._previous_gray.shape != gray.shape:
            self._previous_gray = gray
            return True

        delta = cv2.absdiff(self._previous_gray, gray)
        self._previous_gray = gray
        changed = float(np.count_nonzero(delta > 25)) / float(delta.size)
        if changed < self.settings.motion_gate_min_fraction:
            self.frames_motion_gated += 1
            return False
        return True
