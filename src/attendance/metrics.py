"""Per-stage timing and counters.

Spec section 9 makes latency, accuracy rates and GPU utilisation the exit criteria for
Phase 2, so the pipeline has to be able to report on itself from day one. These are
plain in-process aggregates; exporting them to Prometheus later is an addition here, not
a change anywhere else.

Latency is reported against two different clocks, because the spec's sub-500ms target in
section 6.1 is ambiguous and the difference is large:

  processing latency  frame decoded -> event published. What the code controls.
  presence latency    frame captured -> event published. Includes the wait for the
                      next sample, so at 3 FPS it carries up to ~333ms of sampling
                      delay before any work happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Stage:
    name: str
    samples: list[float] = field(default_factory=list)

    def record(self, milliseconds: float) -> None:
        self.samples.append(milliseconds)

    @property
    def count(self) -> int:
        return len(self.samples)

    def summary(self) -> dict[str, float]:
        if not self.samples:
            return {}
        values = np.asarray(self.samples)
        return {
            "count": float(values.size),
            "mean_ms": float(values.mean()),
            "p50_ms": float(np.percentile(values, 50)),
            "p95_ms": float(np.percentile(values, 95)),
            "max_ms": float(values.max()),
        }


@dataclass
class PipelineMetrics:
    frames_sampled: int = 0
    faces_detected: int = 0
    faces_gated: int = 0
    faces_embedded: int = 0
    recognitions_skipped: int = 0
    events_published: int = 0
    unresolved_quality: int = 0
    unresolved_match: int = 0
    stages: dict[str, Stage] = field(default_factory=dict)

    def stage(self, name: str) -> Stage:
        return self.stages.setdefault(name, Stage(name))

    def record(self, name: str, milliseconds: float) -> None:
        self.stage(name).record(milliseconds)

    def as_dict(self) -> dict[str, object]:
        return {
            "counters": {
                "frames_sampled": self.frames_sampled,
                "faces_detected": self.faces_detected,
                "faces_gated": self.faces_gated,
                "faces_embedded": self.faces_embedded,
                "recognitions_skipped": self.recognitions_skipped,
                "events_published": self.events_published,
                "unresolved_quality": self.unresolved_quality,
                "unresolved_match": self.unresolved_match,
            },
            "latency": {
                name: stage.summary() for name, stage in self.stages.items() if stage.count
            },
        }
