from __future__ import annotations

from abc import ABC, abstractmethod

from attendance.types import Frame, SourceMode


class VideoSource(ABC):
    """A camera or file that yields BGR frames.

    Implementations differ in how they must be consumed (see SourceMode), which the
    sampler needs to know: a file has to be decoded frame by frame to advance,
    whereas a live stream should always skip to the newest frame available.
    """

    camera_id: str
    mode: SourceMode

    @property
    @abstractmethod
    def native_fps(self) -> float | None:
        """Source frame rate, or None if unknown."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def read(self) -> Frame | None:
        """Return the next frame, or None if the source is exhausted or stalled."""

    @property
    @abstractmethod
    def is_exhausted(self) -> bool:
        """True when no further frames will ever arrive (end of file). Always False for live."""

    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
