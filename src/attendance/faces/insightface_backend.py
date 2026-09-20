"""SCRFD detection + ArcFace embedding via InsightFace on onnxruntime.

Spec section 3.3 names this the production path. Note the licensing flag the spec
raises: the InsightFace *code* is MIT, but the pretrained packs (including buffalo_l)
are published for non-commercial research use. Weights are therefore never downloaded
implicitly by this module; ``attendance models download`` is an explicit, separate
step that prints the licence position first.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import structlog
from insightface.model_zoo import SCRFD, ArcFaceONNX
from insightface.utils import face_align

from attendance.faces.base import FaceBackend
from attendance.faces.providers import build_session, resolve_providers
from attendance.types import BoundingBox, DetectedFace, FaceEmbedding

log = structlog.get_logger(__name__)

DETECTOR_FILENAME = "det_10g.onnx"
RECOGNITION_FILENAME = "w600k_r50.onnx"
ALIGNED_SIZE = 112


class InsightFaceBackend(FaceBackend):
    def __init__(
        self,
        model_dir: Path,
        model_pack: str = "buffalo_l",
        provider: str = "auto",
        detector_input_size: tuple[int, int] = (640, 640),
        detector_threshold: float = 0.5,
        intra_op_threads: int = 0,
        static_shape_sessions: bool = False,
    ) -> None:
        pack_dir = Path(model_dir) / model_pack
        detector_path = pack_dir / DETECTOR_FILENAME
        recognition_path = pack_dir / RECOGNITION_FILENAME
        for path in (detector_path, recognition_path):
            if not path.exists():
                raise FileNotFoundError(
                    f"model weights missing: {path}\n"
                    f"Run: attendance models download --pack {model_pack}"
                )

        self._providers = resolve_providers(provider)
        self._detector_input_size = detector_input_size
        self._detector_threshold = detector_threshold
        self._model_pack = model_pack
        self._intra_op_threads = intra_op_threads

        detector_session = build_session(str(detector_path), self._providers, intra_op_threads)
        recognition_session = build_session(
            str(recognition_path), self._providers, intra_op_threads
        )

        # By default SCRFD compiles a second, input-size-specialized session at detect
        # time. On CoreML that path writes a compiled cache under $HOME and builds the
        # session with its own provider options rather than the ones configured here,
        # which breaks in containers and on read-only home directories. Disabling it
        # reuses the session built above, at the cost of dynamic input shapes. That
        # costs a little on CoreML and nothing meaningful on the CUDA target, so it is
        # the default; set static_shape_sessions=True to opt back into the faster,
        # cache-dependent path once a deployment can write to the cache location.
        self._detector = SCRFD(
            model_file=str(detector_path),
            session=detector_session,
            static_shape_sessions=static_shape_sessions,
        )
        self._recognizer = ArcFaceONNX(
            model_file=str(recognition_path), session=recognition_session
        )
        self._resolved_provider = detector_session.get_providers()[0]

        log.info(
            "face_backend_ready",
            backend="insightface",
            model_pack=model_pack,
            provider=self._resolved_provider,
            detector_input_size=detector_input_size,
        )

    @property
    def model_version(self) -> str:
        return f"insightface-{self._model_pack}-v1"

    @property
    def embedding_dim(self) -> int:
        return 512

    @property
    def provider(self) -> str:
        return self._resolved_provider

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        boxes, landmarks = self._detector.detect(
            image, input_size=self._detector_input_size, det_thresh=self._detector_threshold
        )
        if boxes is None or len(boxes) == 0:
            return []

        height, width = image.shape[:2]
        faces: list[DetectedFace] = []
        for index, row in enumerate(boxes):
            x1, y1, x2, y2, score = (float(v) for v in row[:5])
            face_landmarks = None
            if landmarks is not None and index < len(landmarks):
                face_landmarks = np.asarray(landmarks[index], dtype=np.float32)
            faces.append(
                DetectedFace(
                    box=BoundingBox(x1, y1, x2, y2).clipped_to(width, height),
                    detector_score=score,
                    landmarks=face_landmarks,
                )
            )
        return faces

    def align(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        if face.landmarks is not None:
            return face_align.norm_crop(image, landmark=face.landmarks, image_size=ALIGNED_SIZE)
        return _crop_and_resize(image, face.box)

    def embed(self, image: np.ndarray, face: DetectedFace) -> FaceEmbedding:
        return self.embed_aligned(self.align(image, face))

    def embed_aligned(self, aligned: np.ndarray) -> FaceEmbedding:
        raw = self._recognizer.get_feat(aligned)
        vector = np.asarray(raw, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise ValueError("embedder returned a zero vector")
        return FaceEmbedding(vector=vector / norm, model_version=self.model_version)


def _crop_and_resize(image: np.ndarray, box: BoundingBox) -> np.ndarray:
    import cv2

    x1, y1 = int(max(0, box.x1)), int(max(0, box.y1))
    x2, y2 = int(min(image.shape[1], box.x2)), int(min(image.shape[0], box.y2))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        raise ValueError("empty crop for detected face")
    return cv2.resize(crop, (ALIGNED_SIZE, ALIGNED_SIZE))
