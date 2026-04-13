from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from game_server import score_summary_from_snapshot


ROOT = Path(__file__).resolve().parent
REAL_CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
DEFAULT_LOG_DIR = ROOT / "runs"
DEFAULT_MODEL = None
DEFAULT_REASONING_EFFORT = None
BOARD_RETURNING_TOOLS = {"show", "deploy", "clear", "next", "restart"}
AUTOPLAY_PROMPT = (
    "Beat the current tower defense level autonomously. "
    "This is a gameplay evaluation, not a coding task. "
    "Use only the provided gameplay tools to inspect state and act. "
    "Do not edit files, do not modify configuration, and do not use shell commands unless absolutely necessary. "
    "You get exactly one attempt. There is no restart tool. "
    "Use instructions and guide as needed, keep playing until the level ends in either Win or Loss, "
    "and then give a concise summary of the result and the key decisions."
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def toml_basic_string(value: str) -> str:
    return json.dumps(value)


def build_temp_codex_home(
    temp_home: Path,
    *,
    seed: int,
    level_id: int,
    mcp_event_log_path: Path,
):
    temp_home.mkdir(parents=True, exist_ok=True)

    auth_src = REAL_CODEX_HOME / "auth.json"
    if not auth_src.exists():
        raise SystemExit(
            f"Could not find Codex auth at {auth_src}. Run `codex login` first."
        )
    os.symlink(auth_src, temp_home / "auth.json")

    mcp_server_path = ROOT / "td_mcp_server.py"
    command = sys.executable
    args = [
        str(mcp_server_path),
        "--seed",
        str(seed),
        "--level",
        str(level_id),
        "--agent-mode",
        "--event-log",
        str(mcp_event_log_path),
    ]
    config_lines = [
        'personality = "pragmatic"',
        "tool_output_token_limit = 10000",
        "",
        f'[projects.{toml_basic_string(str(ROOT))}]',
        'trust_level = "trusted"',
        "",
        '[mcp_servers."td-cli-agent"]',
        f"command = {toml_basic_string(command)}",
        f"args = {json.dumps(args)}",
        "",
    ]
    config_text = "\n".join(config_lines)

    (temp_home / "config.toml").write_text(config_text, encoding="utf-8")


def codex_env(temp_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(temp_home)
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_BASE_URL", None)
    env.pop("OPENAI_MODEL", None)
    return env


def ensure_codex_login(env: dict[str, str]):
    result = subprocess.run(
        ["codex", "login", "status"],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "unknown login error").strip()
        raise SystemExit(f"Codex login check failed: {message}")


def build_codex_command(
    *,
    cwd: Path,
    prompt: str,
    final_message_path: Path,
    model: str | None,
    reasoning_effort: str | None,
) -> list[str]:
    command = [
        "codex",
        "-a",
        "never",
        "exec",
        prompt,
        "-C",
        str(cwd),
        "-s",
        "danger-full-access",
        "--skip-git-repo-check",
        "-o",
        str(final_message_path),
    ]
    if model:
        command.extend(["-m", model])
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    return command


def format_cli_command(name: str, arguments: dict) -> str:
    if name == "guide":
        return f"guide {arguments['entry']}"
    if name == "deploy":
        return f"deploy {arguments['name']} {arguments['row']} {arguments['col']}"
    if name == "clear":
        return f"clear {arguments['row']} {arguments['col']}"
    if name == "inspect":
        return f"inspect {arguments['row']} {arguments['col']}"
    return name


def should_skip_codex_stdout_line(line: str) -> bool:
    if not line.startswith("mcp: td-cli-agent/"):
        return False
    stripped = line.rstrip("\n")
    return stripped.endswith(" started") or stripped.endswith(" (completed)")


def score_summary_from_records(records: list[dict]) -> dict:
    for record in reversed(records):
        if record.get("event") != "board_snapshot":
            continue
        snapshot = record.get("snapshot")
        if isinstance(snapshot, dict):
            return score_summary_from_snapshot(snapshot)
    return {
        "score": None,
        "outcome": None,
        "reached_waves": 0,
        "total_waves": 0,
        "completed": False,
    }


def format_score_line(score_info: dict) -> str:
    if score_info["score"] is None:
        return "Score: unavailable (level not finished)."
    return (
        f"Score: {score_info['score']:.6f} "
        f"({score_info['outcome'].lower()}, wave {score_info['reached_waves']}/{score_info['total_waves']})"
    )


class StreamMirror:
    def __init__(self, transcript_handle):
        self.transcript_handle = transcript_handle
        self._lock = threading.Lock()

    def write(self, text: str):
        if not text:
            return
        with self._lock:
            print(text, end="")
            self.transcript_handle.write(text)
            self.transcript_handle.flush()


class McpEventEcho:
    def __init__(self, event_log_path: Path, mirror: StreamMirror):
        self.event_log_path = event_log_path
        self.mirror = mirror
        self.latest_board = ""
        self.pending_tool_call: tuple[str, dict] | None = None
        self._position = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="td-mcp-event-echo", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._drain()

    def _run(self):
        while not self._stop.is_set():
            self._drain()
            time.sleep(0.05)

    def _drain(self):
        if not self.event_log_path.exists():
            return
        with self.event_log_path.open("r", encoding="utf-8") as handle:
            handle.seek(self._position)
            while True:
                line = handle.readline()
                if not line:
                    break
                self._position = handle.tell()
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._handle_record(record)

    def _handle_record(self, record: dict):
        event_type = record.get("event")
        if event_type == "board_snapshot":
            board_text = record.get("result")
            if isinstance(board_text, str) and board_text.strip():
                self.latest_board = board_text
            return
        if event_type == "tool_call":
            tool_name = record.get("tool")
            arguments = record.get("arguments") or {}
            if isinstance(tool_name, str):
                self.pending_tool_call = (tool_name, arguments)
            return
        if event_type != "tool_output":
            return

        tool_name = record.get("tool")
        if not isinstance(tool_name, str):
            return
        arguments = {}
        if self.pending_tool_call is not None and self.pending_tool_call[0] == tool_name:
            arguments = self.pending_tool_call[1]
            self.pending_tool_call = None
        output = record.get("output")
        if not isinstance(output, str):
            output = str(output or "")
        self._echo_tool_activity(tool_name, arguments, output)

    def _echo_tool_activity(self, name: str, arguments: dict, output: str):
        command_text = format_cli_command(name, arguments)
        output_text = output.strip()
        board_text = self.latest_board.strip()
        parts = [f"td> {command_text}\n"]
        if output_text:
            parts.append(output.rstrip("\n") + "\n")
        if name not in BOARD_RETURNING_TOOLS and board_text and board_text not in output_text:
            parts.append(self.latest_board.rstrip("\n") + "\n")
        parts.append("\n")
        self.mirror.write("".join(parts))


def run_codex(command: list[str], env: dict[str, str], transcript_path: Path, mcp_event_log_path: Path) -> int:
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with transcript_path.open("w", encoding="utf-8") as transcript:
        mirror = StreamMirror(transcript)
        event_echo = McpEventEcho(mcp_event_log_path, mirror)
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        event_echo.start()
        try:
            for line in process.stdout:
                if should_skip_codex_stdout_line(line):
                    continue
                mirror.write(line)
            return process.wait()
        finally:
            event_echo.stop()


def assemble_run_log(
    *,
    final_log_path: Path,
    started_at: str,
    command_logged_at: str,
    model: str | None,
    reasoning_effort: str | None,
    seed: int,
    level_id: int,
    prompt: str,
    codex_command: list[str],
    exit_code: int,
    final_message: str,
    transcript_path: Path,
    mcp_event_log_path: Path,
):
    mcp_records = read_jsonl(mcp_event_log_path)
    score_info = score_summary_from_records(mcp_records)
    records = [
        {
            "timestamp": started_at,
            "event": "run_started",
            "runner": "codex",
            "seed": seed,
            "level_id": level_id,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "prompt": prompt,
        },
        {
            "timestamp": command_logged_at,
            "event": "codex_command",
            "argv": codex_command,
            "transcript_path": str(transcript_path),
        },
    ]
    records.extend(mcp_records)
    if final_message:
        records.append(
            {
                "timestamp": now_iso(),
                "event": "assistant_text",
                "text": final_message,
            }
        )
    if score_info["completed"]:
        records.append(
            {
                "timestamp": now_iso(),
                "event": "run_finished",
                "summary": final_message,
                **score_info,
            }
        )
    records.append(
        {
            "timestamp": now_iso(),
            "event": "run_closed",
            "exit_code": exit_code,
            "transcript_path": str(transcript_path),
            **score_info,
        }
    )

    records.sort(key=lambda record: record.get("timestamp", ""))
    write_jsonl(final_log_path, records)
    return score_info


def main():
    parser = argparse.ArgumentParser(description="Run the tower defense benchmark through Codex CLI instead of the Responses API.")
    parser.add_argument("--seed", type=int, default=7, help="Random seed for the level.")
    parser.add_argument("--level", type=int, default=1, help="Level number to evaluate.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Optional Codex model override.")
    parser.add_argument("--reasoning-effort", type=str, default=DEFAULT_REASONING_EFFORT, help="Optional Codex reasoning effort override.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="Directory for JSONL run logs and stdout transcripts.")
    parser.add_argument("--dry-run", action="store_true", help="Build the isolated Codex config and print the command without executing the model.")
    args = parser.parse_args()

    args.log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    final_log_path = args.log_dir / f"td-codex-run-{timestamp}.jsonl"
    transcript_path = args.log_dir / f"td-codex-run-{timestamp}.txt"

    with tempfile.TemporaryDirectory(prefix="td-codex-home-") as temp_dir:
        temp_home = Path(temp_dir)
        mcp_event_log_path = temp_home / "td-mcp-events.jsonl"
        final_message_path = temp_home / "last-message.txt"
        build_temp_codex_home(
            temp_home,
            seed=args.seed,
            level_id=args.level,
            mcp_event_log_path=mcp_event_log_path,
        )
        env = codex_env(temp_home)
        ensure_codex_login(env)

        codex_command = build_codex_command(
            cwd=ROOT,
            prompt=AUTOPLAY_PROMPT,
            final_message_path=final_message_path,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
        )
        started_at = now_iso()
        command_logged_at = now_iso()

        print(f"[run log] {final_log_path}")
        print(f"[stdout] {transcript_path}")

        if args.dry_run:
            print("[dry run] temp CODEX_HOME prepared")
            print("[dry run] command:")
            print(" ".join(json.dumps(part) if " " in part else part for part in codex_command))
            return

        exit_code = run_codex(codex_command, env, transcript_path, mcp_event_log_path)
        final_message = final_message_path.read_text(encoding="utf-8").strip() if final_message_path.exists() else ""
        score_info = assemble_run_log(
            final_log_path=final_log_path,
            started_at=started_at,
            command_logged_at=command_logged_at,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            seed=args.seed,
            level_id=args.level,
            prompt=AUTOPLAY_PROMPT,
            codex_command=codex_command,
            exit_code=exit_code,
            final_message=final_message,
            transcript_path=transcript_path,
            mcp_event_log_path=mcp_event_log_path,
        )

        if final_message:
            print("\n[final summary]")
            print(final_message)
        print(f"[score] {format_score_line(score_info)}")

        if exit_code != 0:
            raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
