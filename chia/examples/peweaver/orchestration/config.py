"""Configuration for the bounded PEWeaver local/cloud boundary.

This file deliberately has no CHIA/Ray or cloud SDK dependency.  Environment
values are read for execution, but credentials and key contents are never
placed in the serializable configuration or a run manifest.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class OrchestrationConfig:
    """Explicit, bounded settings for one orchestration invocation.

    ``run_vertex`` is intentionally false by default.  When true, the runner
    still requires both the CLI authorization flag and the environment gate.
    ``ray_address`` is optional and is only used by the GCP-side dispatch
    command; no Ray process is started by this package.
    """

    benchmark_root: Path
    manifest_dir: Path
    timeout_seconds: float = 60.0
    yosys: str = ""
    ray_address: str = ""
    run_vertex: bool = False
    vertex_model: str = "gemini-2.5-flash"
    vertex_project: str = ""
    vertex_location: str = "us-central1"
    vertex_timeout_seconds: int = 120

    @classmethod
    def from_environment(cls, root: Path | None = None, manifest_dir: Path | None = None) -> "OrchestrationConfig":
        base = Path(root or Path(__file__).resolve().parents[1]).resolve()
        out = Path(manifest_dir or _env("PEWEAVER_RUN_MANIFEST_DIR", str(Path(__file__).resolve().parent / "runs"))).resolve()
        return cls(
            benchmark_root=base,
            manifest_dir=out,
            timeout_seconds=float(_env("PEWEAVER_EVALUATOR_TIMEOUT", "60")),
            yosys=_env("PEWEAVER_YOSYS"),
            ray_address=_env("RAY_ADDRESS"),
            run_vertex=False,
            vertex_model=_env("VERTEX_GEMINI_MODEL", "gemini-2.5-flash"),
            vertex_project=_env("GOOGLE_CLOUD_PROJECT"),
            vertex_location=_env("GOOGLE_CLOUD_LOCATION", "us-central1"),
            vertex_timeout_seconds=int(_env("PEWEAVER_VERTEX_TIMEOUT", "120")),
        )

    def public_dict(self) -> dict[str, Any]:
        """Return only safe-to-persist configuration metadata.

        In particular, this excludes ``ray_address`` because addresses can
        contain topology details, and excludes every credential/key setting.
        Paths are represented as strings for JSON stability.
        """
        data = asdict(self)
        data["benchmark_root"] = str(self.benchmark_root)
        data["manifest_dir"] = str(self.manifest_dir)
        data.pop("ray_address", None)
        data["vertex_project"] = self.vertex_project or "<unset>"
        return data

    def canonical_json(self) -> str:
        return json.dumps(self.public_dict(), sort_keys=True, separators=(",", ":"))

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.benchmark_root.is_dir():
            errors.append(f"benchmark root does not exist: {self.benchmark_root}")
        required = (
            self.benchmark_root / "equivalence_runner.py",
            self.benchmark_root / "manifest_schema.py",
            self.benchmark_root / "__init__.py",
        )
        for path in required:
            if not path.is_file():
                errors.append(f"required PEWeaver source is missing: {path}")
        if self.timeout_seconds <= 0:
            errors.append("timeout_seconds must be positive")
        if self.vertex_timeout_seconds <= 0:
            errors.append("vertex_timeout_seconds must be positive")
        if self.vertex_project and ("REPLACE_WITH" in self.vertex_project or "<" in self.vertex_project):
            errors.append("vertex project is still a placeholder")
        if self.vertex_model and ("REPLACE_WITH" in self.vertex_model or "<" in self.vertex_model):
            errors.append("vertex model is still a placeholder")
        return errors
