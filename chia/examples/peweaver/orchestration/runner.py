"""Fail-closed PEWeaver orchestration entry point.

The local evaluator delegates to the existing dependency-free
``equivalence_runner``.  The optional Ray and Vertex paths are lazy and
explicitly cloud-only: importing this module never imports CHIA, Ray, or a
cloud SDK, and no path starts a Ray process or makes a network request unless
the corresponding double gate is satisfied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from .config import OrchestrationConfig
except ImportError:  # direct script execution
    from config import OrchestrationConfig


class OrchestrationError(RuntimeError):
    """A safety boundary prevented orchestration from proceeding."""


@dataclass(frozen=True)
class EvaluatorOutcome:
    status: str
    passed: bool
    candidate_accepted: bool
    results: tuple[dict[str, Any], ...]
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _formal_benchmark_root(config: OrchestrationConfig) -> Path:
    """Return the production formal corpus below the PEWeaver source root.

    ``benchmark_root`` is the source bundle root so preflight can verify the
    evaluator and schema modules beside it.  The source tree also contains
    ``testdata/`` fixtures used by unit tests; those are not production
    workloads and must not be dispatched to a cloud worker.
    """
    candidate = config.benchmark_root / "benchmarks"
    return candidate if candidate.is_dir() else config.benchmark_root


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(root: Path) -> dict[str, str]:
    """Hash source/manifests below *root* in stable relative-path order.

    The runner and schema live beside ``benchmarks`` in the PEWeaver source
    bundle, so they are included as well.  This makes a copied cloud
    ``--working-dir`` auditable instead of silently evaluating a partial tree.
    """
    values: dict[str, str] = {}
    candidates = list(root.rglob("*"))
    candidates.extend(root / name for name in ("equivalence_runner.py", "manifest_schema.py", "__init__.py"))
    for path in sorted(set(candidates)):
        relative = path.relative_to(root)
        # Run manifests and interpreter caches are outputs, not source inputs;
        # including them would make each subsequent manifest hash itself.
        if {"__pycache__", ".git", "results", "runs", "work"} & set(relative.parts):
            continue
        if any(token in relative.name.lower() for token in ("credential", "service-account", "private-key", "adc")):
            continue
        if path.is_file() and path.suffix.lower() in {
            ".json", ".sv", ".v", ".py", ".ys", ".sdc", ".txt", ".tcl",
            ".sh", ".yaml", ".yml", ".toml",
        }:
            values[str(relative)] = _sha256(path)
    return values


def preflight(config: OrchestrationConfig) -> dict[str, Any]:
    """Perform read-only local checks with no CHIA/Ray/cloud interaction."""
    errors = config.validate()
    if not config.benchmark_root.exists():
        errors.append("benchmark root is unavailable")
    corpus = _formal_benchmark_root(config)
    manifests = sorted(corpus.rglob("manifest.json")) if corpus.is_dir() else []
    if not manifests:
        errors.append("no benchmark manifests found")
    return {
        "status": "ready" if not errors else "blocked",
        "passed": not errors,
        "benchmark_root": str(config.benchmark_root),
        "manifest_count": len(manifests),
        "errors": errors,
    }


def _local_evaluator(config: OrchestrationConfig) -> list[dict[str, Any]]:
    """Invoke the existing PEWeaver deterministic formal evaluator."""
    parent = config.benchmark_root.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    try:
        from peweaver.equivalence_runner import run_all
    except ImportError:
        # When invoked from the repository root, examples is not necessarily a
        # package on sys.path; load the runner's directory as a direct module.
        runner_dir = str(config.benchmark_root.parent)
        if runner_dir not in sys.path:
            sys.path.insert(0, runner_dir)
        from equivalence_runner import run_all
    results = run_all(_formal_benchmark_root(config), yosys=config.yosys or None,
                      timeout=config.timeout_seconds)
    return [result.json_dict() for result in results]


def _known_pass(result: Mapping[str, Any]) -> bool:
    """Only an explicit expected/actual match and known status can pass."""
    status = result.get("status")
    actual = result.get("actual_equivalent")
    expected = result.get("expected_equivalent")
    return (
        status in {"equivalent", "inequivalent"}
        and isinstance(actual, bool)
        and isinstance(expected, bool)
        and actual == expected
        and result.get("passed") is True
    )


def outcome_from_results(results: Sequence[Mapping[str, Any]], error: str = "") -> EvaluatorOutcome:
    safe = tuple(dict(result) for result in results)
    passed = not error and bool(safe) and all(_known_pass(result) for result in safe)
    return EvaluatorOutcome(
        status="passed" if passed else ("error" if error else "failed"),
        passed=passed,
        # This package has no candidate-generation loop.  Preserve the hard
        # fail-closed boundary if callers later wire candidate metadata in.
        candidate_accepted=passed and all(result.get("candidate_accepted") is True for result in safe),
        results=safe,
        error=error,
    )


def evaluate_local(config: OrchestrationConfig, evaluator: Callable[[], Sequence[Mapping[str, Any]]] | None = None) -> EvaluatorOutcome:
    """Run one bounded local deterministic evaluator smoke.

    ``evaluator`` exists for unit tests and cloud-side adapters; production
    local operation uses the existing equivalence runner.  Any exception,
    timeout/tool error, unknown status, or empty result is a failure.
    """
    try:
        results = evaluator() if evaluator is not None else _local_evaluator(config)
        return outcome_from_results(results)
    except Exception as exc:  # fail closed, including evaluator/tool failure
        return outcome_from_results((), error=f"{type(exc).__name__}: {exc}")


def _vertex_authorized(cli_authorized: bool) -> bool:
    # Two independent gates: an explicit invocation flag and an env opt-in.
    return cli_authorized and os.environ.get("PEWEAVER_ALLOW_VERTEX_BILLABLE") == "1"


def _ray_resources(ray_module: Any) -> tuple[dict[str, float], dict[str, float], str]:
    """Return cluster/available resources, converting Ray failures to text."""
    try:
        cluster = dict(ray_module.cluster_resources())
        available = dict(ray_module.available_resources())
        return cluster, available, ""
    except Exception as exc:
        return {}, {}, f"resource query failed: {type(exc).__name__}: {exc}"


def _resource_error(cluster: Mapping[str, Any], available: Mapping[str, Any], name: str, amount: float) -> str:
    if float(cluster.get(name, 0.0)) < amount:
        return f"cluster has no worker advertising {name}>={amount:g}"
    if float(available.get(name, 0.0)) < amount:
        return f"no currently available {name} capacity (need {amount:g})"
    return ""


@contextmanager
def _ray_session(config: OrchestrationConfig):
    """Connect to an existing Ray cluster and shut down only our connection."""
    import ray  # lazy: cloud path only

    initialized_here = False
    try:
        if not ray.is_initialized():
            ray.init(address=config.ray_address or "auto", ignore_reinit_error=True)
            initialized_here = True
        yield ray
    finally:
        if initialized_here:
            ray.shutdown()


def vertex_connectivity_proof(config: OrchestrationConfig, *, cli_authorized: bool = False) -> dict[str, Any]:
    """Make at most one explicitly authorized Vertex Gemini proof request.

    The response text is intentionally discarded.  This is a connectivity
    proof, not an agent loop and not candidate generation.  The function is
    never called by the local default path.
    """
    if not _vertex_authorized(cli_authorized):
        return {"status": "not_authorized", "attempted": False, "passed": False, "error": "two-gate authorization required"}
    if not config.vertex_project or "REPLACE_WITH" in config.vertex_project:
        return {"status": "blocked", "attempted": False, "passed": False, "error": "Vertex project is unset or a placeholder"}
    try:
        # The proof must consume the advertised worker resource and execute
        # through CHIA; a direct head-side SDK call would test the wrong ADC.
        with _ray_session(config) as ray:
            cluster, available, resource_error = _ray_resources(ray)
            if resource_error:
                return {"status": "blocked", "attempted": False, "passed": False, "error": resource_error}
            resource_error = _resource_error(cluster, available, "vertex_creds", 0.01)
            if resource_error:
                return {"status": "blocked", "attempted": False, "passed": False, "error": resource_error}
            from chia.base.ChiaFunction import get
            from chia.models.vertex import VertexGeminiLLM

            llm = VertexGeminiLLM(
                model=config.vertex_model,
                project=config.vertex_project,
                location=config.vertex_location,
                retries=1,
                timeout_seconds=config.vertex_timeout_seconds,
                max_tokens=32,
                max_tool_iterations=0,
            )
            # Exactly one CHIA remote call.  No tools and no generation loop.
            ref = llm.prompt.options(resources={"vertex_creds": 0.01}).chia_remote(
                llm, "Reply with exactly: PEWEAVER_VERTEX_OK", []
            )
            response = get(ref)
            passed = bool(getattr(response, "success", False)) and getattr(response, "returncode", -1) == 0
            return {"status": "passed" if passed else "failed", "attempted": True, "passed": passed,
                    "error": "" if passed else "Vertex returned an unsuccessful result"}
    except Exception as exc:
        return {"status": "tool_error", "attempted": True, "passed": False,
                "error": f"{type(exc).__name__}: {exc}"}


def dispatch_ray(config: OrchestrationConfig, *, cli_authorized: bool = False) -> EvaluatorOutcome:
    """Dispatch the evaluator through an already-running CHIA/Ray cluster.

    This is GCP-only by policy. It connects to the already-running Ray head;
    it never provisions a cluster or starts a Ray daemon.
    """
    if not cli_authorized or os.environ.get("PEWEAVER_ALLOW_CHIA_DISPATCH") != "1":
        return outcome_from_results((), error="two-gate CHIA dispatch authorization required")
    try:
        with _ray_session(config) as ray:
            cluster, available, resource_error = _ray_resources(ray)
            if resource_error:
                return outcome_from_results((), error=resource_error)
            resource_error = _resource_error(cluster, available, "yosys", 1.0)
            if resource_error:
                return outcome_from_results((), error=resource_error)
            from chia.base.ChiaFunction import get
            source_parent = str(config.benchmark_root.parent.parent)
            if source_parent not in sys.path:
                sys.path.insert(0, source_parent)
            try:
                from examples.peweaver.chia_wrapper import run_peweaver_benchmarks
            except ImportError:
                # Source-bundle execution from the examples/peweaver directory.
                source_examples = str(config.benchmark_root.parent)
                if source_examples not in sys.path:
                    sys.path.insert(0, source_examples)
                from chia_wrapper import run_peweaver_benchmarks
            ref = run_peweaver_benchmarks.options(num_cpus=1).chia_remote(
                str(_formal_benchmark_root(config))
            )
            results = get(ref)
            return outcome_from_results(results)
    except Exception as exc:
        return outcome_from_results((), error=f"{type(exc).__name__}: {exc}")


def write_manifest(config: OrchestrationConfig, *, preflight_result: Mapping[str, Any], evaluator: EvaluatorOutcome | None = None,
                   vertex: Mapping[str, Any] | None = None, error: str = "", run_id: str | None = None) -> Path:
    """Write one durable, credential-free manifest using atomic replacement."""
    config.manifest_dir.mkdir(parents=True, exist_ok=True)
    identifier = run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    document = {
        "schema_version": 1,
        "run_id": identifier,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_hashes": source_hashes(config.benchmark_root),
        "config_hash": hashlib.sha256(config.canonical_json().encode()).hexdigest(),
        "config": config.public_dict(),
        "preflight": dict(preflight_result),
        "evaluator": evaluator.public_dict() if evaluator else None,
        "vertex": dict(vertex) if vertex else {"status": "not_run", "attempted": False, "passed": False},
        "error": error,
    }
    target = config.manifest_dir / f"{identifier}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "local-smoke", "cloud-dispatch"))
    parser.add_argument("--benchmark-root", type=Path)
    parser.add_argument("--manifest-dir", type=Path)
    parser.add_argument("--vertex-proof", action="store_true", help="authorize exactly one Vertex connectivity proof")
    parser.add_argument("--allow-cloud", action="store_true", help="second gate for the GCP-only CHIA dispatch")
    parser.add_argument("--json", action="store_true", help="print the manifest path and result as JSON")
    args = parser.parse_args(argv)
    config = OrchestrationConfig.from_environment(args.benchmark_root, args.manifest_dir)
    pf = preflight(config)
    outcome: EvaluatorOutcome | None = None
    vertex: Mapping[str, Any] | None = None
    error = ""
    if args.command == "preflight":
        code = 0 if pf["passed"] else 2
    elif not pf["passed"]:
        error = "; ".join(pf["errors"])
        code = 2
    elif args.command == "local-smoke":
        outcome = evaluate_local(config)
        code = 0 if outcome.passed else 1
    else:
        outcome = dispatch_ray(config, cli_authorized=args.allow_cloud)
        code = 0 if outcome.passed else 1
        if args.vertex_proof and outcome.passed:
            vertex = vertex_connectivity_proof(config, cli_authorized=True)
            if not vertex["passed"]:
                code = 1
        elif args.vertex_proof:
            vertex = {
                "status": "blocked",
                "attempted": False,
                "passed": False,
                "error": "deterministic evaluator did not pass; Vertex proof suppressed",
            }
    path = write_manifest(config, preflight_result=pf, evaluator=outcome, vertex=vertex, error=error)
    payload = {"manifest": str(path), "preflight": pf}
    if outcome:
        payload["evaluator"] = outcome.public_dict()
    if vertex:
        payload["vertex"] = dict(vertex)
    print(json.dumps(payload, sort_keys=True) if args.json else path)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
