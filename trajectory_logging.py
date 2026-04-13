from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_server import score_summary_from_level


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrajectoryLogger:
    def __init__(self, log_dir: Path, interface: str, seed: int, level_id: int):
        self.log_dir = log_dir
        self.interface = interface
        self.seed = seed
        self.level_id = level_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        file_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = self.log_dir / f"td-{interface}-trajectory-{file_timestamp}.jsonl"
        self._finished_logged = False
        self._closed = False
        self.log(
            "run_started",
            interface=interface,
            seed=seed,
            initial_level_id=level_id,
        )

    def log(self, event: str, **payload: Any):
        record = {
            "event": event,
            "timestamp": _timestamp(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def log_board_snapshot(self, level, trigger: str, command: str | None, result: str):
        self.log(
            "board_snapshot",
            trigger=trigger,
            command=command,
            result=result,
            snapshot=level.replay_snapshot(),
        )
        self.maybe_log_finished(level)

    def maybe_log_finished(self, level):
        if self._finished_logged or level.end_state not in {"Win", "Loss"}:
            return
        self._finished_logged = True
        self.log("run_finished", **score_summary_from_level(level))

    def close(self, level):
        if self._closed:
            return
        self.maybe_log_finished(level)
        self.log("run_closed", **score_summary_from_level(level))
        self._closed = True
