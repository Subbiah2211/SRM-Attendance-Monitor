"""Face quality gate.

Runs between detection and embedding. A 30-pixel, motion-blurred or strongly
profiled face still produces a well-formed 512-d vector, and that vector still has a
nearest neighbour above almost any threshold, so gating on quality does more for the
false-accept rate than tuning the similarity threshold does.

Every rejection is returned with its reason and metrics so the pilot can see *why*
faces are being dropped and re-tune, rather than just observing missed identifications.
"""

from __future__ import annotations

import cv2
import numpy as np

from attendance.config import QualitySettings
from attendance.types import DetectedFace, QualityAssessment


class QualityGate:
    def __init__(self, settings: QualitySettings) -> None:
        self.settings = settings

    def assess(self, face: DetectedFace, aligned: np.ndarray) -> QualityAssessment:
        reasons: list[str] = []
        metrics: dict[str, float] = {
            "detector_score": face.detector_score,
            "face_height_px": face.box.height,
            "face_width_px": face.box.width,
        }

        if face.detector_score < self.settings.min_detector_score:
            reasons.append(
                f"detector_score {face.detector_score:.2f} < {self.settings.min_detector_score:.2f}"
            )

        if face.box.height < self.settings.min_face_height_px:
            reasons.append(
                f"face_height {face.box.height:.0f}px < {self.settings.min_face_height_px}px"
            )

        blur = _blur_variance(aligned)
        metrics["blur_variance"] = blur
        if blur < self.settings.min_blur_variance:
            reasons.append(f"blur_variance {blur:.1f} < {self.settings.min_blur_variance:.1f}")

        if face.landmarks is not None and len(face.landmarks) >= 5:
            yaw = _yaw_ratio(face.landmarks)
            roll = _roll_degrees(face.landmarks)
            metrics["yaw_ratio"] = yaw
            metrics["roll_degrees"] = roll
            if yaw > self.settings.max_yaw_ratio:
                reasons.append(f"yaw_ratio {yaw:.2f} > {self.settings.max_yaw_ratio:.2f}")
            if abs(roll) > self.settings.max_roll_degrees:
                reasons.append(f"roll {roll:.0f}deg > {self.settings.max_roll_degrees:.0f}deg")

        return QualityAssessment(passed=not reasons, reasons=tuple(reasons), metrics=metrics)


def _blur_variance(aligned: np.ndarray) -> float:
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _yaw_ratio(landmarks: np.ndarray) -> float:
    """Proxy for head yaw from five-point landmarks.

    Compares how far the nose sits from each eye. On a frontal face the two distances
    match and the ratio is near 0; as the head turns, the nose moves toward one eye.
    Normalized by interocular distance so it is scale invariant.
    """
    left_eye, right_eye, nose = landmarks[0], landmarks[1], landmarks[2]
    interocular = float(np.linalg.norm(right_eye - left_eye))
    if interocular < 1e-6:
        return 1.0
    to_left = float(np.linalg.norm(nose - left_eye))
    to_right = float(np.linalg.norm(nose - right_eye))
    return abs(to_left - to_right) / interocular


def _roll_degrees(landmarks: np.ndarray) -> float:
    left_eye, right_eye = landmarks[0], landmarks[1]
    delta = right_eye - left_eye
    return float(np.degrees(np.arctan2(float(delta[1]), float(delta[0]))))
