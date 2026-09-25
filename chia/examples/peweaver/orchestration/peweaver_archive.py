"""One small SQLite lineage archive for PEWeaver campaign metadata.

SQLite stores the controller checkpoint, state transitions, and metric
references. Tool logs and large outputs remain content-addressed files under
the run's artifact directory. The archive is controller-owned; model workers
never write it.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


class SQLiteArchive:
    """Append-only attempt metadata with a guarded run configuration."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                parent_hash TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                turn INTEGER NOT NULL,
                workspace_hash TEXT NOT NULL,
                base_workspace_hash TEXT NOT NULL DEFAULT '',
                candidate_sha256 TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL,
                level INTEGER NOT NULL,
                status TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                artifact_refs_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                UNIQUE(run_id, turn)
            );
            CREATE INDEX IF NOT EXISTS attempts_by_run
                ON attempts(run_id, turn);
            """
        )
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(runs)")}
        if "checkpoint_json" not in columns:
            self._db.execute(
                "ALTER TABLE runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'"
            )
        attempt_columns = {
            row[1] for row in self._db.execute("PRAGMA table_info(attempts)")}
        for name in ("base_workspace_hash", "candidate_sha256"):
            if name not in attempt_columns:
                self._db.execute(
                    f"ALTER TABLE attempts ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
        if "checkpoint_json" not in attempt_columns:
            self._db.execute(
                "ALTER TABLE attempts ADD COLUMN checkpoint_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )
        self._db.commit()

    def start_run(self, *, run_id: str, mode: str, parent_hash: str = "",
                  config_hash: str, metadata: Mapping[str, Any] | None = None,
                  checkpoint: Mapping[str, Any] | None = None,
                  resume: bool = False) -> dict[str, Any] | None:
        now = time.time()
        metadata_json = _json(dict(metadata or {}))
        checkpoint_json = _json(dict(checkpoint or {}))
        row = self._db.execute(
            "SELECT mode, parent_hash, config_hash, checkpoint_json "
            "FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is not None:
            if not resume:
                raise RuntimeError("archive start refused: run already exists")
            if (row["mode"], row["parent_hash"], row["config_hash"]) != (
                mode, parent_hash, config_hash
            ):
                raise RuntimeError("archive resume refused: run configuration changed")
            self._db.execute(
                "UPDATE runs SET status='running', updated_at=? WHERE run_id=?",
                (now, run_id),
            )
            stored_checkpoint = json.loads(row["checkpoint_json"] or "{}")
        else:
            if resume:
                raise RuntimeError("archive resume refused: lineage database missing")
            self._db.execute(
                """INSERT INTO runs
                   (run_id, mode, parent_hash, config_hash, status,
                    metadata_json, checkpoint_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, mode, parent_hash, config_hash, "running",
                 metadata_json, checkpoint_json, now, now),
            )
            stored_checkpoint = dict(checkpoint or {})
        self._db.commit()
        return stored_checkpoint or dict(checkpoint or {})

    def record_attempt(self, *, run_id: str, turn: int, workspace_hash: str,
                        verdict: str, level: int, status: str,
                        base_workspace_hash: str = "",
                        candidate_sha256: str = "",
                        metrics: Mapping[str, Any] | None = None,
                       detail: Mapping[str, Any] | None = None,
                       artifact_refs: Mapping[str, Any] | None = None,
                       checkpoint: Mapping[str, Any] | None = None) -> None:
        if checkpoint is None:
            raise ValueError("attempt checkpoint is required")
        now = time.time()
        checkpoint_json = _json(dict(checkpoint))
        encoded = {
            "workspace_hash": workspace_hash,
            "base_workspace_hash": base_workspace_hash,
            "candidate_sha256": candidate_sha256,
            "verdict": verdict,
            "level": int(level),
            "status": status,
            "metrics_json": _json(dict(metrics or {})),
            "detail_json": _json(dict(detail or {})),
            "artifact_refs_json": _json(dict(artifact_refs or {})),
            "checkpoint_json": checkpoint_json,
        }
        try:
            self._db.execute("BEGIN IMMEDIATE")
            run = self._db.execute(
                "SELECT 1 FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise RuntimeError("attempt references unknown run")
            existing = self._db.execute(
                "SELECT workspace_hash, base_workspace_hash, candidate_sha256, "
                "verdict, level, status, metrics_json, detail_json, "
                "artifact_refs_json, checkpoint_json FROM attempts "
                "WHERE run_id=? AND turn=?",
                (run_id, int(turn)),
            ).fetchone()
            if existing is None:
                self._db.execute(
                    """INSERT INTO attempts
                       (run_id, turn, workspace_hash, base_workspace_hash,
                        candidate_sha256, verdict, level, status, metrics_json,
                        detail_json, artifact_refs_json, checkpoint_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, int(turn), encoded["workspace_hash"],
                     encoded["base_workspace_hash"], encoded["candidate_sha256"],
                     encoded["verdict"],
                     encoded["level"], encoded["status"],
                     encoded["metrics_json"], encoded["detail_json"],
                     encoded["artifact_refs_json"], encoded["checkpoint_json"], now),
                )
            else:
                existing_values = {key: existing[key] for key in encoded
                                   if key in existing.keys()}
                if existing_values != encoded:
                    raise RuntimeError("archive lineage conflict for attempt")
            self._db.execute(
                "UPDATE runs SET checkpoint_json=?, updated_at=? WHERE run_id=?",
                (checkpoint_json, now, run_id),
            )
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def checkpoint(self, run_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT checkpoint_json FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("archive run not found")
        return json.loads(row["checkpoint_json"] or "{}")

    def update_checkpoint(self, run_id: str,
                          checkpoint: Mapping[str, Any]) -> None:
        """Persist a non-evaluator controller transition atomically."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            changed = self._db.execute(
                "UPDATE runs SET checkpoint_json=?, updated_at=? WHERE run_id=?",
                (_json(dict(checkpoint)), time.time(), run_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("archive run not found")
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise

    def finish_run(self, run_id: str, status: str) -> None:
        self._db.execute(
            "UPDATE runs SET status=?, updated_at=? WHERE run_id=?",
            (status, time.time(), run_id),
        )
        self._db.commit()

    def attempts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM attempts WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "turn": row["turn"],
                "workspace_hash": row["workspace_hash"],
                "base_workspace_hash": row["base_workspace_hash"],
                "candidate_sha256": row["candidate_sha256"],
                "verdict": row["verdict"],
                "level": row["level"],
                "status": row["status"],
                "metrics": json.loads(row["metrics_json"]),
                "detail": json.loads(row["detail_json"]),
                "artifact_refs": json.loads(row["artifact_refs_json"]),
                "checkpoint": json.loads(row["checkpoint_json"]),
            }
            for row in rows
        ]

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "SQLiteArchive":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["SQLiteArchive"]
