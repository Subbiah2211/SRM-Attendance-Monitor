from attendance.video.base import VideoSource
from attendance.video.file import FileVideoSource
from attendance.video.rtsp import RtspVideoSource
from attendance.video.sampler import FrameSampler

__all__ = ["VideoSource", "FileVideoSource", "RtspVideoSource", "FrameSampler", "open_source"]


def open_source(camera_id: str, source: str, **kwargs) -> VideoSource:
    """Pick an implementation from the source string.

    A local file path gives development parity with the live path: same sampler,
    same detector, same matcher, only the decode differs.
    """
    lowered = source.lower()
    if lowered.startswith(("rtsp://", "rtsps://")) or "!" in source:
        return RtspVideoSource(camera_id=camera_id, source=source, **kwargs)
    return FileVideoSource(camera_id=camera_id, path=source, **kwargs)
