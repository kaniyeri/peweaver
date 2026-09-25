"""Small typed contracts shared by PEWeaver evaluator nodes and drivers.

The protocol is deliberately narrower than a general workflow framework.  A
driver owns candidate staging and a model-free evaluator owns acceptance; this
module only standardizes the boundary between them and keeps physical metrics
usable as bounded feedback.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence


STATUS_PASS = "passed"
STATUS_REJECT = "rejected"
STATUS_RETRY = "retryable_infrastructure_failure"
STATUS_INVALID = "invalid_result"


class EvaluatorProtocol(Protocol):
    """Build/run/map shape adapted from the CHIA evaluator examples."""

    def build(self, candidate: str, context: Mapping[str, Any]) -> Any: ...

    def run(self, built: Any, context: Mapping[str, Any]) -> Any: ...

    def map_result(self, raw: Any) -> "EvaluationResult": ...


@dataclass(frozen=True)
class EvaluationResult:
    """A model-independent, serializable evaluator outcome."""

    status: str
    passed: bool
    candidate_accepted: bool = False
    retryable: bool = False
    metrics: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Sequence[str] = field(default_factory=tuple)
    artifact_refs: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = {
            "status": self.status,
            "passed": self.passed,
            "candidate_accepted": self.candidate_accepted,
            "retryable": self.retryable,
            "metrics": dict(self.metrics),
            "diagnostics": list(self.diagnostics),
            "artifact_refs": dict(self.artifact_refs),
        }
        # Reject NaN/Infinity before an outcome can enter the archive.
        json.dumps(result, allow_nan=False)
        return result


def map_node_result(raw: Mapping[str, Any]) -> EvaluationResult:
    """Normalize a CHIA node dictionary without guessing missing booleans."""
    passed = raw.get("passed")
    retry = raw.get("retry", False)
    if type(passed) is not bool or type(retry) is not bool:
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("passed and retry must be boolean",),
        )
    candidate_accepted = raw.get("candidate_accepted", False)
    if type(candidate_accepted) is not bool:
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("candidate_accepted must be boolean",),
        )
    metrics = raw.get("metrics", {})
    if not isinstance(metrics, Mapping):
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("metrics must be a mapping",),
        )
    try:
        json.dumps(metrics, allow_nan=False)
    except (TypeError, ValueError):
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("metrics must contain finite JSON values",),
        )
    status = str(raw.get("status") or (STATUS_RETRY if retry else
                                        STATUS_PASS if passed else STATUS_REJECT))
    diagnostics = raw.get("diagnostics", ())
    if isinstance(diagnostics, str):
        diagnostics = (diagnostics,)
    elif not isinstance(diagnostics, Sequence):
        diagnostics = ("diagnostics must be a sequence",)
    artifact_refs = raw.get("artifact_refs", {})
    if not isinstance(artifact_refs, Mapping):
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("artifact_refs must be a mapping",),
        )
    status = str(raw.get("status") or (STATUS_RETRY if retry else
                                        STATUS_PASS if passed else STATUS_REJECT))
    if (status == STATUS_INVALID or retry and passed
            or (passed and status in {STATUS_REJECT, STATUS_RETRY})
            or (not passed and status == STATUS_PASS)):
        return EvaluationResult(
            status=STATUS_INVALID,
            passed=False,
            diagnostics=("status contradicts passed/retry",),
        )
    return EvaluationResult(
        status=status,
        passed=passed,
        candidate_accepted=candidate_accepted,
        retryable=retry,
        metrics=dict(metrics),
        diagnostics=tuple(str(item) for item in diagnostics),
        artifact_refs=dict(artifact_refs),
    )


def config_fingerprint(config: Mapping[str, Any]) -> str:
    """Return the stable hash used to reject incompatible archive resumes."""
    encoded = json.dumps(config, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def timing_feedback(metrics: Mapping[str, Any]) -> str:
    """Make a short timing/physical summary safe to feed to a model."""
    labels = (
        ("timing_met", "timing_met"),
        ("setup_slack_ns", "setup_slack_ns"),
        ("hold_slack_ns", "hold_slack_ns"),
        ("cell_area_um2", "cell_area_um2"),
        ("drc_violations", "drc_violations"),
    )
    parts: list[str] = []
    for key, label in labels:
        value = metrics.get(key)
        if value is None:
            continue
        if isinstance(value, float) and not math.isfinite(value):
            parts.append(f"{label}=invalid_nonfinite")
        else:
            parts.append(f"{label}={value}")
    return "Timing/physical feedback: " + ("; ".join(parts) or "no metrics")


__all__ = [
    "EvaluationResult",
    "EvaluatorProtocol",
    "STATUS_INVALID",
    "STATUS_PASS",
    "STATUS_REJECT",
    "STATUS_RETRY",
    "config_fingerprint",
    "map_node_result",
    "timing_feedback",
]
