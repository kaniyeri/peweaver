"""Bounded Sol-lead/DeepSeek-worker campaign adapter.

This controller deliberately does not know how to accept RTL or run physical
design.  The caller supplies isolated candidate staging and a model-free
evaluator callback.  Consequently a model response can never itself mark a
candidate accepted, and a candidate hash change during an uncertain call is
handled by :mod:`model_shim` before any failover is attempted.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .model_shim import ModelRequest, ModelResponse, ProviderNeutralModelShim


@dataclass(frozen=True)
class CampaignResult:
    run_id: str
    status: str
    candidate_accepted: bool = False
    lead: ModelResponse | None = None
    turns: tuple[ModelResponse, ...] = field(default_factory=tuple)
    evaluator_results: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "candidate_accepted": self.candidate_accepted,
            "lead": self.lead.public_dict() if self.lead else None,
            "turns": [turn.public_dict() for turn in self.turns],
            "evaluator_results": [dict(result) for result in self.evaluator_results],
            "error": self.error,
        }


class ModelNeutralCampaign:
    """Run one bounded lead/worker campaign around a model-free evaluator.

    ``stage_candidate`` must copy exactly one candidate into an isolated
    evaluator checkout and return its resulting hash.  It must return ``None``
    on any protected-file or staging violation. ``evaluate_candidate`` should
    run the existing immutable regression/GLS/physical ladder and return
    records containing explicit boolean ``passed`` and ``candidate_accepted``
    fields.  The latter is mandatory for acceptance.
    """

    def __init__(self, shim: ProviderNeutralModelShim, *, max_turns: int = 3,
                 clock: Callable[[], float] = time.time,
                 lead_plan_max_chars: int = 4096,
                 feedback_max_chars: int = 1200) -> None:
        self.shim = shim
        self.max_turns = max_turns
        self.clock = clock
        self.lead_plan_max_chars = max(0, lead_plan_max_chars)
        self.feedback_max_chars = max(0, feedback_max_chars)

    def run(
        self,
        *,
        run_id: str,
        work_id: str,
        context_hash: str,
        candidate_hash: str,
        lead_prompt: str,
        worker_prompt: str,
        candidate_hash_reader: Callable[[], str],
        stage_candidate: Callable[[str], str | None] | None,
        evaluate_candidate: Callable[[str], Mapping[str, Any]] | None,
        deadline: float = 0.0,
        token_cap: int = 4096,
    ) -> CampaignResult:
        if self.max_turns <= 0 or not candidate_hash:
            return CampaignResult(run_id, "blocked", error="invalid_campaign_bounds")
        lead = self.shim.call(ModelRequest.create(
            run_id=run_id, work_id=work_id, role="lead", prompt=lead_prompt,
            context_hash=context_hash, candidate_hash=candidate_hash,
            candidate_hash_reader=candidate_hash_reader, deadline=deadline,
            token_cap=token_cap, estimated_input_tokens=max(1, (len(lead_prompt) + 3) // 4),
            request_id=f"{run_id}:lead"))
        if not lead.success:
            return CampaignResult(run_id, "lead_failed", lead=lead, error=lead.error or lead.status)
        # Sol is advisory architecture context. Verify that even a successful
        # lead call did not edit the candidate before handing its bounded plan
        # to the worker; no lead failover or acceptance occurs after mutation.
        try:
            if candidate_hash_reader() != candidate_hash:
                return CampaignResult(run_id, "candidate_mutated_by_lead", lead=lead,
                                      error="lead_candidate_mutated")
        except Exception:
            return CampaignResult(run_id, "candidate_mutated_by_lead", lead=lead,
                                  error="lead_candidate_unreadable")

        lead_output = lead.output or ""
        lead_hash = hashlib.sha256(lead_output.encode("utf-8")).hexdigest()
        lead_plan = lead_output[:self.lead_plan_max_chars]
        plan_context = (
            "\n--- SOL ARCHITECTURE PLAN (bounded; advisory) ---\n"
            f"plan_sha256={lead_hash} plan_chars={len(lead_plan)} "
            f"plan_truncated={'true' if len(lead_output) > len(lead_plan) else 'false'}\n"
            f"{lead_plan}\n"
            "--- END SOL ARCHITECTURE PLAN ---\n"
        )

        turns: list[ModelResponse] = []
        evaluator_results: list[Mapping[str, Any]] = []
        feedback = worker_prompt + plan_context
        current_hash = candidate_hash
        for turn in range(1, self.max_turns + 1):
            response = self.shim.call(ModelRequest.create(
                run_id=run_id, work_id=work_id, role="worker",
                prompt=feedback, context_hash=context_hash,
                candidate_hash=current_hash,
                candidate_hash_reader=candidate_hash_reader,
                deadline=deadline, token_cap=token_cap,
                estimated_input_tokens=max(1, (len(feedback) + 3) // 4),
                request_id=f"{run_id}:worker:{turn}"))
            turns.append(response)
            if not response.success:
                return CampaignResult(run_id, "worker_failed", lead=lead,
                                      turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                      error=response.error or response.status)
            if stage_candidate is None or evaluate_candidate is None:
                # A model response without an evaluator is evidence only, not
                # a candidate decision.
                return CampaignResult(run_id, "model_output_unvalidated", lead=lead,
                                      turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                      error="candidate_staging_and_evaluator_required")
            staged_hash = stage_candidate(response.output)
            if not staged_hash or staged_hash == current_hash:
                return CampaignResult(run_id, "candidate_rejected", lead=lead,
                                      turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                      error="candidate_staging_failed_or_unchanged")
            # The staging callback is responsible for the isolated copy; this
            # check catches a callback that returns an untrusted/non-hash value.
            if len(staged_hash) != 64 or any(ch not in "0123456789abcdef" for ch in staged_hash.lower()):
                return CampaignResult(run_id, "candidate_rejected", lead=lead,
                                      turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                      error="invalid_candidate_hash")
            try:
                if candidate_hash_reader() != staged_hash:
                    return CampaignResult(run_id, "candidate_rejected", lead=lead,
                                          turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                          error="staged_candidate_hash_mismatch")
            except Exception:
                return CampaignResult(run_id, "candidate_rejected", lead=lead,
                                      turns=tuple(turns), evaluator_results=tuple(evaluator_results),
                                      error="candidate_hash_unreadable")
            current_hash = staged_hash
            evaluation = dict(evaluate_candidate(current_hash))
            evaluator_results.append(evaluation)
            if evaluation.get("passed") is True and evaluation.get("candidate_accepted") is True:
                return CampaignResult(run_id, "accepted", True, lead, tuple(turns),
                                      tuple(evaluator_results))
            # Keep the next turn bounded and model-neutral. Do not include raw
            # evaluator logs in the shim ledger; the evaluator owns its logs.
            feedback = (worker_prompt + plan_context
                        + "\nThis candidate failed the immutable evaluator. "
                        "Repair one atomic hypothesis and return the staged candidate artifact.\n"
                        + _bounded_feedback(evaluation, self.feedback_max_chars))
        return CampaignResult(run_id, "exhausted", lead=lead, turns=tuple(turns),
                              evaluator_results=tuple(evaluator_results), error="turn_budget_exhausted")


def _bounded_feedback(evaluation: Mapping[str, Any], limit: int) -> str:
    """Keep evaluator feedback to a small, caller-sanitized status summary."""
    allowed = ("status", "reason", "error_code", "summary", "mismatch")
    parts: list[str] = []
    for key in allowed:
        value = evaluation.get(key)
        if value is None:
            continue
        text = str(value).replace("\r", " ").replace("\n", " ")
        # A caller must provide sanitized values; this strips obvious control
        # characters as a final bounded defense without copying raw logs.
        text = "".join(ch for ch in text if ch.isprintable())
        parts.append(f"{key}={text}")
    result = "Evaluator summary (caller-supplied, bounded): " + "; ".join(parts)
    return result[:max(0, limit)]


__all__ = ["CampaignResult", "ModelNeutralCampaign"]
