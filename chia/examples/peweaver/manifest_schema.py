"""Validation for the agent-visible PEWeaver workload contract.

The contract describes facts the planner may use.  Evaluator-only labels such
as ``expected_equivalent`` remain outside the contract and are accepted by the
runner for scoring.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


class ManifestValidationError(ValueError):
    """A manifest failed one or more deterministic schema checks."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(str(error) for error in errors)
        super().__init__("manifest validation failed: " + "; ".join(self.errors))

    def as_dict(self) -> dict[str, Any]:
        return {"error": "manifest_validation", "details": list(self.errors)}


def _text(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be a non-empty string")


def _mapping(value: Any, field: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{field} must be an object")
        return None
    return value


def _string_list(value: Any, field: str, errors: list[str], *, allow_empty: bool = False) -> list[str] | None:
    if not isinstance(value, list) or (not allow_empty and not value):
        errors.append(f"{field} must be a non-empty list of strings")
        return None
    if not all(isinstance(item, str) and item.strip() for item in value):
        errors.append(f"{field} must contain only non-empty strings")
        return None
    return value


def _overlap_groups(value: Any, field: str, errors: list[str]) -> list[list[str]] | None:
    if not isinstance(value, list):
        errors.append(f"{field} must be a list of component-name lists")
        return None
    groups: list[list[str]] = []
    for index, group in enumerate(value):
        parsed = _string_list(group, f"{field}[{index}]", errors)
        if parsed is not None:
            groups.append(parsed)
    return groups


def validate_manifest(data: Mapping[str, Any], *, path: str | None = None) -> Mapping[str, Any]:
    """Validate and return a manifest containing a version-1 workload contract.

    The validator intentionally checks shape and safety-relevant types, while
    leaving domain-specific meanings (for example fixed-point encodings) in
    the declared contract text/object for the deterministic gates to consume.
    """

    errors: list[str] = []
    prefix = f"{path}: " if path else ""
    if not isinstance(data, Mapping):
        raise ManifestValidationError([prefix + "manifest root must be an object"])

    if data.get("schema_version") != 1:
        errors.append("schema_version must be integer 1")
    _text(data.get("name"), "name", errors)

    contract = _mapping(data.get("contract"), "contract", errors)
    if contract is not None:
        modes_value = contract.get("task_modes")
        if not isinstance(modes_value, list) or not modes_value:
            errors.append("contract.task_modes must be a non-empty list")
            modes_value = []
        mode_names: set[str] = set()
        component_names: set[str] = set()
        for index, mode in enumerate(modes_value):
            mode_map = _mapping(mode, f"contract.task_modes[{index}]", errors)
            if mode_map is None:
                continue
            mode_name = mode_map.get("name")
            _text(mode_name, f"contract.task_modes[{index}].name", errors)
            if isinstance(mode_name, str):
                if mode_name in mode_names:
                    errors.append(f"duplicate task mode name: {mode_name}")
                mode_names.add(mode_name)
            components = _string_list(
                mode_map.get("components"),
                f"contract.task_modes[{index}].components",
                errors,
            )
            if components is not None:
                component_names.update(components)
            groups = _overlap_groups(
                mode_map.get("parallel_groups", []),
                f"contract.task_modes[{index}].parallel_groups",
                errors,
            )
            if groups is not None and components is not None:
                component_set = set(components)
                for group_index, group in enumerate(groups):
                    unknown = sorted(set(group) - component_set)
                    if unknown:
                        errors.append(
                            f"contract.task_modes[{index}].parallel_groups[{group_index}] "
                            f"references unknown components: {', '.join(unknown)}"
                        )

        mutual = contract.get("top_level_mutual_exclusion")
        if not isinstance(mutual, bool):
            errors.append("contract.top_level_mutual_exclusion must be boolean")
        legal_overlap = _overlap_groups(contract.get("legal_overlap", []), "contract.legal_overlap", errors)
        if legal_overlap is not None:
            for index, group in enumerate(legal_overlap):
                unknown = sorted(set(group) - component_names)
                if unknown:
                    errors.append(
                        f"contract.legal_overlap[{index}] references unknown components: {', '.join(unknown)}"
                    )

        interfaces = _mapping(contract.get("interfaces"), "contract.interfaces", errors)
        if interfaces is not None:
            for field in ("clock", "reset", "input", "output", "fixed_point", "backpressure"):
                if field not in interfaces:
                    errors.append(f"contract.interfaces.{field} is required")
                else:
                    _text(interfaces[field], f"contract.interfaces.{field}", errors)

        performance = _mapping(contract.get("performance"), "contract.performance", errors)
        if performance is not None:
            latency = performance.get("latency_cycles")
            if not isinstance(latency, int) or isinstance(latency, bool) or latency < 0:
                errors.append("contract.performance.latency_cycles must be a non-negative integer")
            _text(performance.get("sustained_throughput"), "contract.performance.sustained_throughput", errors)

        mode_switch = _mapping(contract.get("mode_switch"), "contract.mode_switch", errors)
        if mode_switch is not None:
            _text(mode_switch.get("preconditions"), "contract.mode_switch.preconditions", errors)
            for field in ("drain_inflight", "reset_on_switch", "state_isolation"):
                if not isinstance(mode_switch.get(field), bool):
                    errors.append(f"contract.mode_switch.{field} must be boolean")

        stimulus = _mapping(contract.get("stimulus"), "contract.stimulus", errors)
        if stimulus is not None:
            _text(stimulus.get("source"), "contract.stimulus.source", errors)
            _text(stimulus.get("provenance"), "contract.stimulus.provenance", errors)

        objective = _mapping(contract.get("objective"), "contract.objective", errors)
        if objective is not None:
            _text(objective.get("primary"), "contract.objective.primary", errors)
            if not isinstance(objective.get("constraints"), Mapping):
                errors.append("contract.objective.constraints must be an object")

    if errors:
        raise ManifestValidationError([prefix + error for error in errors])
    return data
