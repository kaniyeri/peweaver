#!/usr/bin/env python3
"""Fail-closed verifier for the submission-edge artifact index.

The verifier is intentionally read-only. It validates the nested release-index
schema before hashing any files, rejects paths outside the supplied repository
root, and returns nonzero for every malformed, missing, modified, or
size-mismatched artifact.

Usage:
    verify_artifact_index.py --manifest audit/artifact_index.json
    verify_artifact_index.py --manifest <path> --root <repo-root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SIZE_KEYS = ("bytes", "size_bytes")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entries(manifest: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("manifest must be a non-empty object")
    for category, records in manifest.items():
        if not isinstance(records, dict) or not records:
            raise ValueError(f"category {category!r} must be a non-empty object")
        for name, record in records.items():
            if not isinstance(record, dict):
                raise ValueError(f"entry {category}/{name} must be an object")
            yield f"{category}/{name}", record


def verify(manifest_path: Path, root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "manifest": str(manifest_path),
        "root": str(root),
        "entries": 0,
        "checked": 0,
        "duplicate_paths": 0,
        "errors": [],
    }
    errors: list[str] = result["errors"]

    try:
        manifest = json.loads(manifest_path.read_text())
        entries = list(_entries(manifest))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"manifest: {exc}")
        return result

    result["entries"] = len(entries)
    root_resolved = root.resolve()
    seen: dict[Path, tuple[str, int]] = {}

    for label, record in entries:
        path_value = record.get("path")
        digest = record.get("sha256")
        size_values = [record[key] for key in SIZE_KEYS if key in record]

        if not isinstance(path_value, str) or not path_value:
            errors.append(f"{label}: path must be a non-empty string")
            continue
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            errors.append(f"{label}: sha256 must be 64 lowercase hexadecimal characters")
            continue
        if len(size_values) != 1 or not isinstance(size_values[0], int) or isinstance(size_values[0], bool):
            errors.append(f"{label}: exactly one integer size field is required")
            continue
        expected_size = size_values[0]
        if expected_size < 0:
            errors.append(f"{label}: size must be non-negative")
            continue

        relative = Path(path_value)
        if relative.is_absolute():
            errors.append(f"{label}: path must be relative: {path_value}")
            continue
        resolved = (root_resolved / relative).resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            errors.append(f"{label}: path escapes root: {path_value}")
            continue

        prior = seen.get(resolved)
        if prior is not None:
            result["duplicate_paths"] += 1
            if prior != (digest, expected_size):
                errors.append(f"{label}: duplicate path has conflicting expectations: {path_value}")
            continue
        seen[resolved] = (digest, expected_size)

        if not resolved.is_file():
            errors.append(f"{label}: missing file: {path_value}")
            continue
        result["checked"] += 1
        actual_size = resolved.stat().st_size
        if actual_size != expected_size:
            errors.append(
                f"{label}: size mismatch for {path_value}: expected {expected_size}, got {actual_size}"
            )
            continue
        actual_digest = sha256_file(resolved)
        if actual_digest != digest:
            errors.append(
                f"{label}: hash mismatch for {path_value}: expected {digest}, got {actual_digest}"
            )

    result["ok"] = not errors and result["checked"] == len(seen)
    if not result["ok"] and not errors:
        errors.append("verification did not check every unique manifest path")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    result = verify(args.manifest, args.root)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
