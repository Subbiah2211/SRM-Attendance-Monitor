"""Execution provider resolution.

The spec targets CUDA. Development happens on Apple Silicon. Resolving the provider
at runtime from whatever onnxruntime actually has available keeps one codebase for
both, and surfacing the resolved provider lets benchmark output state plainly which
hardware a number came from.
"""

from __future__ import annotations

import onnxruntime as ort
import structlog

log = structlog.get_logger(__name__)

_PROVIDER_ALIASES = {
    "cuda": "CUDAExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
    "cpu": "CPUExecutionProvider",
}

_AUTO_PRIORITY = ("CUDAExecutionProvider", "CoreMLExecutionProvider", "CPUExecutionProvider")


def resolve_providers(requested: str) -> list[str]:
    available = set(ort.get_available_providers())

    if requested == "auto":
        chosen = [p for p in _AUTO_PRIORITY if p in available]
        return chosen or ["CPUExecutionProvider"]

    name = _PROVIDER_ALIASES[requested]
    if name not in available:
        log.warning(
            "execution_provider_unavailable",
            requested=name,
            available=sorted(available),
            falling_back_to="CPUExecutionProvider",
        )
        return ["CPUExecutionProvider"]
    if name == "CPUExecutionProvider":
        return [name]
    return [name, "CPUExecutionProvider"]


def build_session(
    model_path: str, providers: list[str], intra_op_threads: int = 0
) -> ort.InferenceSession:
    options = ort.SessionOptions()
    if intra_op_threads > 0:
        options.intra_op_num_threads = intra_op_threads
    options.log_severity_level = 3
    return ort.InferenceSession(model_path, sess_options=options, providers=providers)
