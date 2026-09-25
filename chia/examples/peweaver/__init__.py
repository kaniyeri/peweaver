"""Small, dependency-free PEWeaver verification runner."""

from .equivalence_runner import EquivalenceResult, Manifest, discover_manifests, run_manifest

__all__ = ["EquivalenceResult", "Manifest", "discover_manifests", "run_manifest"]
