"""Optional CHIA entry point; importing this file never requires Ray/CHIA."""

from __future__ import annotations

from pathlib import Path

from .equivalence_runner import run_all

try:
    from chia.base.ChiaFunction import ChiaFunction
except ImportError:  # local CLI/users without the CHIA runtime
    def ChiaFunction(**_kwargs):
        def decorate(function):
            return function
        return decorate


@ChiaFunction(resources={"yosys": 1})
def run_peweaver_benchmarks(root: str) -> list[dict]:
    return [result.json_dict() for result in run_all(Path(root))]
