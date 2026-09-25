"""Bounded PEWeaver orchestration primitives.

The module is intentionally importable with only the Python standard library.
CHIA, Ray, google-genai, and cloud credentials are required only by the
explicitly opt-in cloud entry points.
"""

from .config import OrchestrationConfig


def __getattr__(name: str):
    # Keep ``python -m peweaver.orchestration.runner`` free of an eager runner
    # import and, importantly, free of any eager CHIA/Ray import.
    if name in {"EvaluatorOutcome", "OrchestrationError", "evaluate_local", "preflight", "write_manifest"}:
        from . import runner
        return getattr(runner, name)
    raise AttributeError(name)

__all__ = [
    "EvaluatorOutcome",
    "OrchestrationConfig",
    "OrchestrationError",
    "evaluate_local",
    "preflight",
    "write_manifest",
]

# Provider-neutral model routing is likewise lazy at the package boundary: it
# does not import CHIA/Ray or construct a backend until ``call`` is invoked.
from .model_shim import (BudgetStatus, ModelRequest, ModelResponse, ModelRoute,
                         ModelStatus, ModelUsage, ProviderNeutralModelShim,
                         ShimConfig)
from .model_neutral_loop import CampaignResult, ModelNeutralCampaign

__all__ += [
    "BudgetStatus", "ModelRequest", "ModelResponse", "ModelRoute", "ModelStatus",
    "ModelUsage", "ProviderNeutralModelShim", "ShimConfig",
    "CampaignResult", "ModelNeutralCampaign",
]
