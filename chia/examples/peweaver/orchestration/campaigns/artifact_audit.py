#!/usr/bin/env python3
"""Model-free artifact audit: verify every pinned hash in a release manifest.

Usage:
    artifact_audit.py --manifest <manifest.json> [--root <dir>]
    artifact_audit.py --write --manifest <out.json> <path>... [--root <dir>]

The manifest lists {path, sha256, bytes} for every release artifact. The
audit fails closed: any missing, modified, or unexpected-size file is a hard
error (exit 1). This is the Workstream-0 acceptance command: the campaign
refuses to start if an immutable input is missing or changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(paths: list[Path], root: Path, note: str = "") -> dict:
    artifacts = []
    for p in paths:
        rp = p.resolve().relative_to(root.resolve())
        artifacts.append({"path": str(rp), "sha256": sha256_file(p),
                          "bytes": p.stat().st_size})
    return {"created": time.time(), "note": note, "artifacts": artifacts}


def audit(manifest_path: Path, root: Path) -> tuple[int, list[str]]:
    m = json.loads(manifest_path.read_text())
    errors: list[str] = []
    checked = 0
    for art in m.get("artifacts", []):
        p = root / art["path"]
        if not p.is_file():
            errors.append(f"MISSING: {art['path']}")
            continue
        checked += 1
        if "sha256" in art:
            actual = sha256_file(p)
            if actual != art["sha256"]:
                errors.append(f"HASH MISMATCH: {art['path']} "
                              f"(expected {art['sha256'][:16]}..., "
                              f"got {actual[:16]}...)")
        if "bytes" in art and p.stat().st_size != art["bytes"]:
            errors.append(f"SIZE MISMATCH: {art['path']}")
    return checked, errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--root", type=Path, default=Path.cwd())
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--note", default="")
    ap.add_argument("paths", nargs="*", type=Path)
    args = ap.parse_args()

    if args.write:
        missing = [str(p) for p in args.paths if not p.is_file()]
        if missing:
            print(json.dumps({"error": "missing files", "missing": missing}))
            return 2
        manifest = build_manifest(args.paths, args.root, args.note)
        args.manifest.write_text(json.dumps(manifest, indent=1))
        print(json.dumps({"wrote": str(args.manifest),
                          "artifacts": len(manifest["artifacts"])}))
        return 0

    checked, errors = audit(args.manifest, args.root)
    print(json.dumps({"checked": checked, "errors": errors,
                      "ok": not errors}, indent=1))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
