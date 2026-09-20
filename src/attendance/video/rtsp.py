"""Live RTSP source (spec section 3.1).

A background thread decodes continuously and keeps only the newest frame, which is
the OpenCV equivalent of the spec's ``appsink max-buffers=1 drop=true``: the sampler
always gets the freshest frame rather than working through a backlog.

Decode backend selection is intentionally pluggable. On the pilot GPU server, pass a
full GStreamer pipeline string ending in ``appsink`` to get hardware decode (NVDEC).
Without one, this falls back to OpenCV's FFMPEG backend, which works everywhere
including Apple Silicon development machines but decodes on the CPU.

Note the spec's example pipeline uses ``nvv4l2decoder``, which is the Jetson element.
On a datacenter or workstation card (L4/T4/RTX) the equivalent is ``nvh264dec``.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import cv2
import structlog

from attendance.types import Frame, SourceMode
from attendance.video.base import VideoSource

log = structlog.get_logger(__name__)


class RtspVideoSource(VideoSource):
    mode = SourceMode.LATEST

    def __init__(
        self,
        camera_id: str,
        source: str,
        reconnect_initial_seconds: float = 1.0,
        reconnect_max_seconds: float = 30.0,
        open_timeout_seconds: float = 10.0,
    ) -> None:
        self.camera_id = camera_id
        self.source = source
        self.reconnect_initial_seconds = reconnect_initial_seconds
        self.reconnect_max_seconds = reconnect_max_seconds
        self.open_timeout_seconds = open_timeout_seconds

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._frame_available = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._sequence = 0
        self._dropped = 0
        self._reconnects = 0

    @property
    def native_fps(self) -> float | None:
        return None

    @property
    def is_exhausted(self) -> bool:
        return False

    @property
    def dropped_frames(self) -> int:
        """Frames decoded but never sampled. Expected to be large and is not a fault."""
        return self._dropped

    @property
    def reconnect_count(self) -> int:
        return self._reconnects

    def open(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._decode_loop, name=f"rtsp-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def read(self) -> Frame | None:
        """Hand back the newest decoded frame, or None if nothing has arrived yet."""
        with self._lock:
            frame = self._latest
            self._latest = None
        if frame is None:
            self._frame_available.clear()
        return frame

    def wait_for_frame(self, timeout: float) -> bool:
        return self._frame_available.wait(timeout=timeout)

    def _build_capture(self) -> cv2.VideoCapture:
        if "!" in self.source:
            return cv2.VideoCapture(self.source, cv2.CAP_GSTREAMER)
        capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _decode_loop(self) -> None:
        backoff = self.reconnect_initial_seconds
        while not self._stop.is_set():
            capture = self._build_capture()
            if not capture.isOpened():
                capture.release()
                log.warning(
                    "camera_connect_failed",
                    camera_id=self.camera_id,
                    retry_in_seconds=round(backoff, 1),
                )
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self.reconnect_max_seconds)
                self._reconnects += 1
                continue

            log.info("camera_connected", camera_id=self.camera_id)
            backoff = self.reconnect_initial_seconds
            self._pump(capture)
            capture.release()

            if not self._stop.is_set():
                self._reconnects += 1
                log.warning(
                    "camera_stream_lost",
                    camera_id=self.camera_id,
                    retry_in_seconds=round(backoff, 1),
                    reconnects=self._reconnects,
                )
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, self.reconnect_max_seconds)

    def _pump(self, capture: cv2.VideoCapture) -> None:
        consecutive_failures = 0
        while not self._stop.is_set():
            ok, image = capture.read()
            if not ok:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    return
                continue
            consecutive_failures = 0

            frame = Frame(
                camera_id=self.camera_id,
                image=image,
                captured_at=datetime.now(UTC),
                sequence=self._sequence,
            )
            self._sequence += 1
            with self._lock:
                if self._latest is not None:
                    self._dropped += 1
                self._latest = frame
            self._frame_available.set()
