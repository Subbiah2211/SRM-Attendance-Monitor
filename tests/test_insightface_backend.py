"""Real-model checks against actual faces.

Skipped automatically when the weights are absent, so CI and licence-constrained
machines stay green without them. These are the only tests that exercise real
detection and real embeddings, and they assert the property the whole system rests on:
the same face scores near 1.0 against itself while different faces score far enough
below the configured threshold that it can actually separate them.

Sample images ship with insightface. ``t1.jpg`` is a group photo of several distinct
people, which is the useful one here; ``Tom_Hanks_54745.png`` is a pre-aligned 112x112
ArcFace crop rather than a detectable scene, so it exercises the aligned-input path.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from attendance.config import QualitySettings, Settings
from attendance.faces.quality import QualityGate
from attendance.types import DetectedFace

SAMPLES = Path(__import__("insightface").__file__).parent / "data" / "images"
GROUP_PHOTO = SAMPLES / "t1.jpg"
PREALIGNED_CROP = SAMPLES / "Tom_Hanks_54745.png"

_settings = Settings()
_pack_dir = _settings.inference.model_dir / _settings.inference.model_pack
weights_present = (_pack_dir / "det_10g.onnx").exists() and (_pack_dir / "w600k_r50.onnx").exists()

pytestmark = pytest.mark.skipif(
    not weights_present,
    reason=f"model weights not present in {_pack_dir}; run 'attendance models download'",
)


@pytest.fixture(scope="module")
def backend():
    from attendance.faces.insightface_backend import InsightFaceBackend

    return InsightFaceBackend(
        model_dir=_settings.inference.model_dir,
        model_pack=_settings.inference.model_pack,
        provider="auto",
    )


@pytest.fixture(scope="module")
def group_image():
    image = cv2.imread(str(GROUP_PHOTO))
    assert image is not None
    return image


@pytest.fixture(scope="module")
def group_faces(backend, group_image) -> list[DetectedFace]:
    return backend.detect(group_image)


def test_backend_reports_expected_contract(backend):
    assert backend.embedding_dim == 512
    assert backend.model_version == "insightface-buffalo_l-v1"
    assert "ExecutionProvider" in backend.provider


def test_detects_every_face_in_a_group_photo(backend, group_faces):
    assert len(group_faces) >= 5
    for face in group_faces:
        assert face.detector_score > 0.5
        assert face.landmarks is not None and face.landmarks.shape == (5, 2)
        assert face.box.width > 0 and face.box.height > 0


def test_alignment_produces_the_arcface_input_size(backend, group_image, group_faces):
    aligned = backend.align(group_image, group_faces[0])
    assert aligned.shape == (112, 112, 3)


def test_embedding_is_normalized_and_deterministic(backend, group_image, group_faces):
    first = backend.embed(group_image, group_faces[0])
    second = backend.embed(group_image, group_faces[0])

    assert first.vector.shape == (512,)
    assert np.isclose(np.linalg.norm(first.vector), 1.0, atol=1e-4)
    assert first.cosine_similarity(second) > 0.9999


def test_prealigned_crop_can_be_embedded_directly(backend):
    """The enrollment path may receive an already-cropped reference photo."""
    aligned = cv2.imread(str(PREALIGNED_CROP))
    embedding = backend.embed_aligned(aligned)

    assert embedding.vector.shape == (512,)
    assert np.isclose(np.linalg.norm(embedding.vector), 1.0, atol=1e-4)


def test_same_face_survives_jpeg_recompression(backend, group_image, group_faces, tmp_path):
    """Re-encoding is the realistic runtime case, so the embedding must barely move."""
    reference_face = max(group_faces, key=lambda f: f.box.area)
    reference = backend.embed(group_image, reference_face)

    path = tmp_path / "recompressed.jpg"
    cv2.imwrite(str(path), group_image, [cv2.IMWRITE_JPEG_QUALITY, 70])
    recompressed = cv2.imread(str(path))

    redetected = backend.detect(recompressed)
    same_face = max(redetected, key=lambda f: f.box.iou(reference_face.box))
    assert same_face.box.iou(reference_face.box) > 0.8, "could not re-locate the same face"

    again = backend.embed(recompressed, same_face)
    assert reference.cosine_similarity(again) > 0.9


def test_different_identities_stay_below_the_match_threshold(backend, group_image, group_faces):
    """The gap between self-similarity and cross-identity similarity is what makes the
    configured threshold meaningful, so assert it on real faces rather than trusting it."""
    embeddings = [backend.embed(group_image, face) for face in group_faces]

    cross = [
        embeddings[i].cosine_similarity(embeddings[j])
        for i in range(len(embeddings))
        for j in range(i + 1, len(embeddings))
    ]
    worst = max(cross)

    print(
        f"\n{len(embeddings)} faces: worst cross-identity similarity {worst:.3f}, "
        f"threshold {_settings.matching.similarity_threshold}"
    )
    assert worst < _settings.matching.similarity_threshold, (
        f"two different people scored {worst:.3f}, at or above the configured threshold "
        f"{_settings.matching.similarity_threshold} -- that is a false accept"
    )


def test_real_faces_clear_the_quality_gate(backend, group_image, group_faces):
    largest = max(group_faces, key=lambda f: f.box.area)
    aligned = backend.align(group_image, largest)

    assessment = QualityGate(QualitySettings(min_face_height_px=40)).assess(largest, aligned)

    assert assessment.passed, assessment.reasons
    assert assessment.metrics["yaw_ratio"] < 0.45


def test_inference_latency_is_within_the_spec_budget(backend, group_image, group_faces):
    """Spec section 6.1 budgets under 500ms end to end and expects inference to be a
    small fraction of it. This is CoreML on a laptop rather than the CUDA target, so
    treat it as an upper bound, not the pilot benchmark."""
    backend.detect(group_image)  # warm up

    detect_ms, embed_ms = [], []
    for _ in range(5):
        started = time.perf_counter()
        faces = backend.detect(group_image)
        detect_ms.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        backend.embed(group_image, faces[0])
        embed_ms.append((time.perf_counter() - started) * 1000)

    detect_median = float(np.median(detect_ms))
    embed_median = float(np.median(embed_ms))
    print(
        f"\n{backend.provider}: detect {detect_median:.1f}ms (full frame, "
        f"{len(group_faces)} faces) + embed {embed_median:.1f}ms per face"
    )
    assert detect_median + embed_median < 500.0
