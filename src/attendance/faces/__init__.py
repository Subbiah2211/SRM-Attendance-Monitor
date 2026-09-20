from attendance.faces.base import FaceBackend
from attendance.faces.mock_backend import MockFaceBackend
from attendance.faces.quality import QualityGate

__all__ = ["FaceBackend", "MockFaceBackend", "QualityGate", "build_backend"]


def build_backend(settings, kind: str = "insightface") -> FaceBackend:
    """Construct a backend by name.

    The indirection exists so the licensing question in spec section 3.3 can be
    answered by swapping a string, and so a benchmark harness can iterate over
    several backends against the same footage.
    """
    if kind == "mock":
        return MockFaceBackend()
    if kind == "insightface":
        from attendance.faces.insightface_backend import InsightFaceBackend

        return InsightFaceBackend(
            model_dir=settings.inference.model_dir,
            model_pack=settings.inference.model_pack,
            provider=settings.inference.provider,
            detector_input_size=settings.inference.detector_input_size,
            intra_op_threads=settings.inference.intra_op_threads,
        )
    raise ValueError(f"unknown face backend: {kind}")
