#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CODEX_HOME = Path.home() / ".codex"


@dataclass
class LimitSnapshot:
    limit_id: str
    limit_name: str | None
    plan_type: str | None
    timestamp: str
    file: Path
    rate_limits: dict[str, Any]
    info: dict[str, Any] | None

    @property
    def primary_used(self) -> float | None:
        primary = self.rate_limits.get("primary") or {}
        return primary.get("used_percent")

    @property
    def secondary_used(self) -> float | None:
        secondary = self.rate_limits.get("secondary") or {}
        return secondary.get("used_percent")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate current Codex plan usage from the latest local token_count events "
            "written under ~/.codex/sessions."
        )
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=DEFAULT_CODEX_HOME,
        help="Codex home directory to inspect. Defaults to ~/.codex.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the latest known snapshots as JSON.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=200,
        help="Maximum number of recent rollout files to scan.",
    )
    return parser.parse_args()


def iter_recent_rollouts(codex_home: Path, max_files: int) -> list[Path]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []
    files = sorted(
        sessions_dir.rglob("rollout-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return files[:max_files]


def load_latest_snapshots(codex_home: Path, max_files: int) -> dict[str, LimitSnapshot]:
    snapshots: dict[str, LimitSnapshot] = {}
    for rollout_path in iter_recent_rollouts(codex_home, max_files):
        with rollout_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "event_msg":
                    continue
                payload = record.get("payload") or {}
                if payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits") or {}
                limit_id = rate_limits.get("limit_id")
                if not limit_id:
                    continue
                timestamp = record.get("timestamp")
                current = snapshots.get(limit_id)
                if current is not None and timestamp <= current.timestamp:
                    continue
                snapshots[limit_id] = LimitSnapshot(
                    limit_id=limit_id,
                    limit_name=rate_limits.get("limit_name"),
                    plan_type=rate_limits.get("plan_type"),
                    timestamp=timestamp,
                    file=rollout_path,
                    rate_limits=rate_limits,
                    info=payload.get("info"),
                )
    return snapshots


def format_reset(ts: int | None) -> str:
    if ts is None:
        return "unknown"
    return datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def format_percent(used_percent: float | None) -> str:
    if used_percent is None:
        return "unknown"
    left = max(0.0, 100.0 - float(used_percent))
    return f"{left:.0f}% left ({float(used_percent):.0f}% used)"


def format_tokens(info: dict[str, Any] | None) -> str | None:
    if not info:
        return None
    total = info.get("total_token_usage") or {}
    last = info.get("last_token_usage") or {}
    total_tokens = total.get("total_tokens")
    last_tokens = last.get("total_tokens")
    if total_tokens is None and last_tokens is None:
        return None
    pieces = []
    if total_tokens is not None:
        pieces.append(f"total tokens {total_tokens}")
    if last_tokens is not None:
        pieces.append(f"last turn {last_tokens}")
    return ", ".join(pieces)


def format_window(window_minutes: int | None) -> str:
    if window_minutes is None:
        return "unknown window"
    if window_minutes % (24 * 60) == 0:
        days = window_minutes // (24 * 60)
        return f"{days}d window"
    if window_minutes % 60 == 0:
        hours = window_minutes // 60
        return f"{hours}h window"
    return f"{window_minutes}m window"


def print_human(snapshots: dict[str, LimitSnapshot]) -> None:
    if not snapshots:
        print("No token_count events found in local Codex session logs.")
        return

    for limit_id in sorted(snapshots):
        snapshot = snapshots[limit_id]
        label = snapshot.limit_name or snapshot.limit_id
        print(label)
        if snapshot.plan_type:
            print(f"  plan: {snapshot.plan_type}")
        print(f"  seen: {snapshot.timestamp}")
        primary = snapshot.rate_limits.get("primary") or {}
        secondary = snapshot.rate_limits.get("secondary") or {}
        print(
            f"  {format_window(primary.get('window_minutes'))}: "
            f"{format_percent(primary.get('used_percent'))}, resets {format_reset(primary.get('resets_at'))}"
        )
        print(
            f"  {format_window(secondary.get('window_minutes'))}: "
            f"{format_percent(secondary.get('used_percent'))}, resets {format_reset(secondary.get('resets_at'))}"
        )
        credits = snapshot.rate_limits.get("credits")
        if credits is not None:
            print(f"  credits: {json.dumps(credits, sort_keys=True)}")
        token_line = format_tokens(snapshot.info)
        if token_line:
            print(f"  tokens: {token_line}")
        print(f"  source: {snapshot.file}")


def print_json(snapshots: dict[str, LimitSnapshot]) -> None:
    payload = {
        limit_id: {
            "limit_id": snapshot.limit_id,
            "limit_name": snapshot.limit_name,
            "plan_type": snapshot.plan_type,
            "timestamp": snapshot.timestamp,
            "file": str(snapshot.file),
            "rate_limits": snapshot.rate_limits,
            "info": snapshot.info,
        }
        for limit_id, snapshot in sorted(snapshots.items())
    }
    print(json.dumps(payload, indent=2))


def main() -> None:
    args = parse_args()
    snapshots = load_latest_snapshots(args.codex_home.expanduser(), args.max_files)
    if args.json:
        print_json(snapshots)
        return
    print_human(snapshots)


if __name__ == "__main__":
    main()
