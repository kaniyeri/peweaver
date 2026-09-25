#!/usr/bin/env python3
"""Create the synthesis liberty with the pinned ORFS sky130hd DONT_USE cells
removed (abc has no dont_use support). Stdlib-only, fail-closed.

The exclusion prefixes mirror the OpenROAD-flow-scripts sky130hd platform
(config.mk DONT_USE_CELLS: probe/probec/lpflow cells) and must stay
consistent with the set_dont_use list in openroad/fft64_flow.tcl.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EXCLUDE_PREFIXES = (
    "sky130_fd_sc_hd__probe",
    "sky130_fd_sc_hd__probec",
    "sky130_fd_sc_hd__lpflow_",
)
CELL_RE = re.compile(r"^\s*cell\s*\(\s*\"?([^)\"]+)\"?\s*\)")


def excluded(name: str) -> bool:
    return any(name.startswith(prefix) for prefix in EXCLUDE_PREFIXES)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <liberty-in> <liberty-out>", file=sys.stderr)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    lines = src.read_text(encoding="utf-8", errors="strict").splitlines(keepends=True)

    out: list[str] = []
    removed: list[str] = []
    kept_cells = 0
    depth = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if depth == 1:
            m = CELL_RE.match(line)
            if m:
                name = m.group(1)
                block = [line]
                balance = line.count("{") - line.count("}")
                if excluded(name):
                    # swallow the whole cell block (brace-balanced)
                    while balance > 0 or ("{" not in "".join(block)):
                        i += 1
                        if i >= len(lines):
                            die_unterminated(name)
                        line = lines[i]
                        block.append(line)
                        balance += line.count("{") - line.count("}")
                    removed.append(name)
                    i += 1
                    continue
                kept_cells += 1
        depth += line.count("{") - line.count("}")
        out.append(line)
        i += 1

    dst.write_text("".join(out), encoding="utf-8")
    print(f"filter_liberty.py: kept {kept_cells} cells, removed {len(removed)}: "
          f"{', '.join(removed)}; wrote {dst}")
    return 0


def die_unterminated(name: str):
    sys.exit(f"filter_liberty.py: unterminated cell block {name} in liberty")


if __name__ == "__main__":
    raise SystemExit(main())
