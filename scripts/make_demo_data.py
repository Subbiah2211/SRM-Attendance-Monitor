"""Build a self-contained demo dataset from the sample photo shipped with InsightFace.

Produces an enrollment directory, a roster, and a short clip that stands in for a gate
camera. The clip is deliberately degraded relative to the enrollment crops -- rescaled,
brightness-jittered and JPEG-recompressed per frame -- so runtime embeddings are not
byte-identical to the enrolled ones. Without that, every similarity would be 1.0 and the
round trip would prove only that the plumbing is connected, not that matching works.

This is a development fixture, not an accuracy benchmark: six faces from one well-lit
photo say nothing about real camera conditions.
"""

from __future__ import annotations

import csv
from pathlib import Path

import cv2
import insightface
import numpy as np

from attendance.config import Settings
from attendance.faces.insightface_backend import InsightFaceBackend

SOURCE_PHOTO = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
OUTPUT_DIR = Path("var/demo")
CROP_MARGIN = 0.5
"""Fraction of face width/height added on each side, so the crop is detectable."""

FRAME_COUNT = 90
FRAME_RATE = 30.0

NAMES = [
    "Ananya Raghavan",
    "Brian Okafor",
    "Chen Wei",
    "Divya Menon",
    "Erik Lindqvist",
    "Farah Siddiqui",
]


def main() -> None:
    settings = Settings()
    backend = InsightFaceBackend(
        model_dir=settings.inference.model_dir,
        model_pack=settings.inference.model_pack,
        provider=settings.inference.provider,
    )

    image = cv2.imread(str(SOURCE_PHOTO))
    if image is None:
        raise SystemExit(f"could not read {SOURCE_PHOTO}")

    # Left-to-right ordering keeps the assigned identifiers stable across runs.
    faces = sorted(backend.detect(image), key=lambda f: f.box.x1)
    print(f"detected {len(faces)} faces in {SOURCE_PHOTO.name}")

    enroll_dir = OUTPUT_DIR / "enroll"
    enroll_dir.mkdir(parents=True, exist_ok=True)

    roster_rows = []
    for index, face in enumerate(faces):
        university_id = f"CS21B{45 + index:03d}"
        crop = _crop_with_margin(image, face.box, CROP_MARGIN)

        # A reference photo containing two faces is ambiguous and the enrollment tool
        # rejects it, so verify the margin actually isolated one person.
        found = backend.detect(crop)
        if len(found) != 1:
            print(f"  {university_id}: crop has {len(found)} faces, skipping")
            continue

        student_dir = enroll_dir / university_id
        student_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(student_dir / "ref.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
        roster_rows.append((university_id, NAMES[index % len(NAMES)]))
        print(f"  {university_id}: {crop.shape[1]}x{crop.shape[0]} crop -> {student_dir.name}")

    roster_path = OUTPUT_DIR / "roster.csv"
    with roster_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["university_id", "full_name"])
        writer.writerows(roster_rows)
    print(f"wrote {roster_path} ({len(roster_rows)} students)")

    clip_path = OUTPUT_DIR / "gate.mp4"
    _write_degraded_clip(image, clip_path)
    print(f"wrote {clip_path} ({FRAME_COUNT} frames @ {FRAME_RATE:g} fps)")


def _crop_with_margin(image: np.ndarray, box, margin: float) -> np.ndarray:
    pad_x, pad_y = box.width * margin, box.height * margin
    x1 = int(max(0, box.x1 - pad_x))
    y1 = int(max(0, box.y1 - pad_y))
    x2 = int(min(image.shape[1], box.x2 + pad_x))
    y2 = int(min(image.shape[0], box.y2 + pad_y))
    return image[y1:y2, x1:x2].copy()


def _write_degraded_clip(image: np.ndarray, path: Path) -> None:
    """Write frames that resemble a camera feed rather than copies of the source."""
    height, width = image.shape[:2]
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), FRAME_RATE, (width, height)
    )
    if not writer.isOpened():
        raise SystemExit("OpenCV could not open an mp4 writer")

    rng = np.random.default_rng(seed=7)
    try:
        for _ in range(FRAME_COUNT):
            frame = image

            # Downscale and back up: approximates a camera resolving less detail than
            # the enrollment photo did.
            scale = 0.85 + 0.1 * float(rng.random())
            small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            frame = cv2.resize(small, (width, height), interpolation=cv2.INTER_LINEAR)

            brightness = 1.0 + 0.12 * float(rng.normal())
            frame = np.clip(frame.astype(np.float32) * brightness, 0, 255).astype(np.uint8)

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ok:
                frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

            writer.write(frame)
    finally:
        writer.release()


if __name__ == "__main__":
    main()
