from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Literal

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from pydantic import BaseModel, ConfigDict, RootModel

from cli_client import CliGame, DEFENSE_DESCRIPTIONS, MONSTER_DESCRIPTIONS, RESOURCE_LABEL, TOKEN_BY_NAME


EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

CLI_BOARD_FOOTER = "deploy <name> <row> <col> | clear <row> <col> | inspect <row> <col> | next | level <n> | help | instructions | quit"
AGENT_BOARD_FOOTER = "deploy <name> <row> <col> | clear <row> <col> | inspect <row> <col> | guide <entry> | next | help | instructions"


def install_cancelled_notification_compat() -> None:
    if hasattr(types, "CancelledNotification"):
        return

    class CancelledNotificationParams(BaseModel):
        requestId: str | int
        reason: str | None = None
        model_config = ConfigDict(extra="allow")

    class CancelledNotification(types.Notification):
        method: Literal["notifications/cancelled"]
        params: CancelledNotificationParams

    class ClientNotificationCompat(
        RootModel[
            types.ProgressNotification
            | types.InitializedNotification
            | types.RootsListChangedNotification
            | CancelledNotification
        ]
    ):
        pass

    types.CancelledNotificationParams = CancelledNotificationParams
    types.CancelledNotification = CancelledNotification
    types.ClientNotification = ClientNotificationCompat


install_cancelled_notification_compat()


class EventLogger:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def log(self, event_type: str, **data):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


class TowerDefenseMcpSession:
    def __init__(self, seed: int = 7, level_id: int = 1, event_log_path: Path | None = None, agent_mode: bool = False):
        self.seed = seed
        self.level_id = level_id
        self.agent_mode = agent_mode
        self.game = CliGame(seed=seed, no_color=True, level_id=level_id)
        self.event_logger = EventLogger(event_log_path) if event_log_path is not None else None
        self._log_board_snapshot(trigger="initial", command=None, result=self._sanitize_board(self.game.current_view_text()))

    def _log(self, event_type: str, **data):
        if self.event_logger is not None:
            self.event_logger.log(event_type, **data)

    def _log_board_snapshot(self, trigger: str, command: str | None, result: str):
        if self.event_logger is None:
            return
        self.event_logger.log(
            "board_snapshot",
            trigger=trigger,
            command=command,
            result=result,
            snapshot=self.game.level.replay_snapshot(),
        )

    def _sanitize_board(self, text: str) -> str:
        if not self.agent_mode:
            return text
        return text.replace(CLI_BOARD_FOOTER, AGENT_BOARD_FOOTER)

    def _agent_help_text(self) -> str:
        level = self.game.level
        defense_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(defense_cls.__name__, defense_cls.__name__[:3])}:{defense_cls().hp}"
            for defense_cls in level.definition.defense_roster
        )
        monster_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(monster_cls.__name__, monster_cls.__name__[:3])}:{monster_cls().hp}"
            for monster_cls in self.game.instruction_monster_classes()
        )
        return "\n".join([
            "Commands:",
            "  show",
            "  deploy <name> <row> <col>  Example: deploy powerplant 2 4",
            "  clear <row> <col>          Example: clear 2 4",
            f"  inspect <row> <col>        Example: inspect 1 {level.board.entry_col + 1}",
            "  guide <entry>              Detailed field guide entry",
            "  next                       Advance exactly one turn",
            "  status",
            "  instructions               Full gameplay guide",
            "Defense names ignore case, spaces, hyphens, and underscores.",
            f"Columns 1-{level.definition.deployable_cols} are deployable. Column {level.board.entry_col + 1} is monster-entry only.",
            "",
            "Board legend:",
            "  Tokens are <abbr>:<hp>.",
            f"  Defenses in this level: {defense_tokens}",
            f"  Monsters in this level: {monster_tokens}",
            "  . means an empty tile.",
            "",
            "Examples:",
            "  deploy pwr 2 4",
            "  clear 2 4",
            f"  inspect 1 {level.board.entry_col + 1}",
            "  guide lea",
            "  next",
        ])

    def _agent_instructions_text(self) -> str:
        level = self.game.level
        return "\n".join([
            "Instructions:",
            "  This is a turn-based tower defense benchmark.",
            "  Goal: survive the monster waves.",
            "  Loss: if a monster reaches the left edge of the grid, you lose.",
            "  Turn flow: deploy, clear, or inspect as needed, then type `next` to resolve one turn.",
            f"  Energy: defenses cost {RESOURCE_LABEL}. You start with 2 {RESOURCE_LABEL}, gain 1 ambient {RESOURCE_LABEL} every 2 turns, and power plants make extra {RESOURCE_LABEL}.",
            "  Monsters: monsters enter from the right side and move left over time.",
            f"  Board shape: columns 1-{level.definition.deployable_cols} are deployable; column {level.board.entry_col + 1} is monster-entry only.",
            "  Recommendation: before acting, use `guide` on every defense and monster in this level.",
            "  This MCP harness gives you one attempt only; there is no restart tool.",
            "",
            "Defenses in this level:",
            *[f"  {DEFENSE_DESCRIPTIONS.get(defense_cls.__name__, defense_cls.__name__)}" for defense_cls in level.definition.defense_roster],
            "",
            "Monsters in this level:",
            *[f"  {MONSTER_DESCRIPTIONS.get(monster_cls.__name__, monster_cls.__name__)}" for monster_cls in self.game.instruction_monster_classes()],
            "",
            "Mechanics:",
            "  Most monsters hit the defense directly in front of them for 1 damage.",
            "  Some special monsters break that rule; use `guide` to check exact behavior.",
            "  If no defense is in front of a monster, it moves forward.",
            f"  Defenses attack or generate {RESOURCE_LABEL} before monsters move each turn.",
            "  You cannot place a defense on an occupied tile.",
            "  A tile cannot have more than one occupant: defense or monster.",
            "",
            "Type `help` for the agent command reference and board legend.",
        ])

    def _record_tool(self, tool_name: str, arguments: dict, result: str, command: str | None = None, snapshot: bool = False) -> str:
        self._log("tool_call", tool=tool_name, arguments=arguments)
        self._log("tool_output", tool=tool_name, output=result)
        if snapshot:
            self._log_board_snapshot(trigger=tool_name, command=command, result=result)
        return result

    def show(self) -> str:
        result = self._sanitize_board(self.game.current_view_text())
        return self._record_tool("show", {}, result, command="show", snapshot=True)

    def help(self) -> str:
        if self.agent_mode:
            result = self._agent_help_text()
        else:
            result, _ = self.game.execute_command("help")
        return self._record_tool("help", {}, result)

    def instructions(self) -> str:
        if self.agent_mode:
            result = self._agent_instructions_text()
        else:
            result, _ = self.game.execute_command("instructions")
        return self._record_tool("instructions", {}, result)

    def status(self) -> str:
        result, _ = self.game.execute_command("status")
        return self._record_tool("status", {}, result)

    def guide(self, entry: str) -> str:
        result, _ = self.game.execute_command(f"guide {entry}")
        return self._record_tool("guide", {"entry": entry}, result)

    def deploy(self, name: str, row: int, col: int) -> str:
        result, _ = self.game.execute_command(f"deploy {name} {row} {col}")
        result = self._sanitize_board(result)
        return self._record_tool("deploy", {"name": name, "row": row, "col": col}, result, command=f"deploy {name} {row} {col}", snapshot=True)

    def clear(self, row: int, col: int) -> str:
        result, _ = self.game.execute_command(f"clear {row} {col}")
        result = self._sanitize_board(result)
        return self._record_tool("clear", {"row": row, "col": col}, result, command=f"clear {row} {col}", snapshot=True)

    def inspect(self, row: int, col: int) -> str:
        result, _ = self.game.execute_command(f"inspect {row} {col}")
        return self._record_tool("inspect", {"row": row, "col": col}, result)

    def next(self) -> str:
        result, _ = self.game.execute_command("next")
        result = self._sanitize_board(result)
        return self._record_tool("next", {}, result, command="next", snapshot=True)

    def restart(self, seed: int | None = None) -> str:
        if seed is not None:
            self.seed = seed
            self.level_id = self.game.level_id
            self.game = CliGame(seed=seed, no_color=True, level_id=self.level_id)
            result = "Level restarted with new seed.\n" + self._sanitize_board(self.game.current_view_text())
            return self._record_tool("restart", {"seed": seed}, result, command="restart", snapshot=True)
        output, _ = self.game.execute_command("restart")
        self.level_id = self.game.level_id
        output = self._sanitize_board(output)
        return self._record_tool("restart", {"seed": None}, output, command="restart", snapshot=True)

    def cli_command(self, command: str) -> str:
        stripped = command.strip()
        if not stripped:
            return "Command is empty."

        keyword = stripped.split()[0].lower()
        if keyword in {"quit", "q", "exit"}:
            return "The MCP server keeps the game session alive. Use `restart` to reset or close the server process to stop it."

        output, _ = self.game.execute_command(stripped)
        self.level_id = self.game.level_id
        output = self._sanitize_board(output or "(no output)")
        snapshot_keywords = {"show", "board", "deploy", "d", "clear", "c", "next", "end", "restart", "r", "level"}
        return self._record_tool("cli_command", {"command": stripped}, output, command=stripped, snapshot=keyword in snapshot_keywords)


def text_result(text: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=text)]


def build_server(session: TowerDefenseMcpSession) -> Server:
    server = Server("td-cli")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = [
            types.Tool(
                name="show",
                description="Show the current board-first CLI view for the active tower defense session.",
                inputSchema=EMPTY_SCHEMA,
            ),
            types.Tool(
                name="help",
                description="Show the quick-reference command and legend help for the CLI.",
                inputSchema=EMPTY_SCHEMA,
            ),
            types.Tool(
                name="instructions",
                description="Show the gameplay instructions for this turn-based tower defense benchmark.",
                inputSchema=EMPTY_SCHEMA,
            ),
            types.Tool(
                name="status",
                description="Show a detailed status readout for the current game session.",
                inputSchema=EMPTY_SCHEMA,
            ),
            types.Tool(
                name="guide",
                description="Show a detailed field guide entry using an alias, token, or full unit name such as pwr, lea, or powerplant.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entry": {"type": "string", "description": "Defense or monster alias, token, or full name such as tur, lea, powerplant, or leaper."},
                    },
                    "required": ["entry"],
                    "additionalProperties": False,
                },
            ),
            types.Tool(
                name="deploy",
                description="Deploy a defense at a 1-based row and column using the same defense names as the CLI.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Defense name or alias such as pwr, tur, ice, dbl, cru, bar, gre, or mne."},
                        "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                        "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
                    },
                    "required": ["name", "row", "col"],
                    "additionalProperties": False,
                },
            ),
            types.Tool(
                name="clear",
                description="Clear a defense from a 1-based row and column.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                        "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
                    },
                    "required": ["row", "col"],
                    "additionalProperties": False,
                },
            ),
            types.Tool(
                name="inspect",
                description="Inspect one tile at a 1-based row and column.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                        "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
                    },
                    "required": ["row", "col"],
                    "additionalProperties": False,
                },
            ),
            types.Tool(
                name="next",
                description="Advance the game by exactly one turn and return the updated board view.",
                inputSchema=EMPTY_SCHEMA,
            ),
        ]
        if not session.agent_mode:
            tools.extend([
                types.Tool(
                    name="restart",
                    description="Restart the session. Optionally provide a new seed for a fresh deterministic run.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "seed": {"type": "integer", "description": "Optional replacement random seed for the restarted game."},
                        },
                        "additionalProperties": False,
                    },
                ),
                types.Tool(
                    name="cli_command",
                    description="Run a raw CLI command string against the active session and return the CLI text output. Use this for command parity with the interactive shell.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "CLI command such as `show`, `deploy pwr 2 4`, `next`, or `instructions`."},
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                ),
            ])
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "show":
            return text_result(session.show())
        if name == "help":
            return text_result(session.help())
        if name == "instructions":
            return text_result(session.instructions())
        if name == "status":
            return text_result(session.status())
        if name == "guide":
            return text_result(session.guide(str(arguments["entry"])))
        if name == "deploy":
            return text_result(session.deploy(str(arguments["name"]), int(arguments["row"]), int(arguments["col"])))
        if name == "clear":
            return text_result(session.clear(int(arguments["row"]), int(arguments["col"])))
        if name == "inspect":
            return text_result(session.inspect(int(arguments["row"]), int(arguments["col"])))
        if name == "next":
            return text_result(session.next())
        if name == "restart":
            seed = arguments.get("seed")
            return text_result(session.restart(None if seed is None else int(seed)))
        if name == "cli_command":
            return text_result(session.cli_command(str(arguments["command"])))
        raise ValueError(f"Unknown tool: {name}")

    return server


def default_gui_mirror_log_path(seed: int, level_id: int) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / f"td-mcp-mirror-level{level_id}-seed{seed}-{timestamp}.jsonl"


def gui_mirror_lock_path(event_log_path: Path) -> Path:
    return event_log_path.with_name(event_log_path.name + ".mirror.pid")


def process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def spawn_gui_mirror(event_log_path: Path, replay_delay: float) -> subprocess.Popen | None:
    lock_path = gui_mirror_lock_path(event_log_path)
    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = None
        if existing_pid and process_is_alive(existing_pid):
            print(
                f"[gui mirror] reusing pid={existing_pid} log={event_log_path}",
                file=sys.stderr,
                flush=True,
            )
            return None
        lock_path.unlink(missing_ok=True)

    cmd = [
        sys.executable,
        str(Path(__file__).with_name("pygame_client.py")),
        "--replay-log",
        str(event_log_path),
        "--follow-replay-log",
        "--replay-delay",
        str(replay_delay),
    ]
    process = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent),
        stdout=subprocess.DEVNULL,
        start_new_session=True,
    )
    lock_path.write_text(str(process.pid), encoding="utf-8")
    print(
        f"[gui mirror] pid={process.pid} log={event_log_path}",
        file=sys.stderr,
        flush=True,
    )
    return process


async def async_main(
    seed: int,
    level_id: int,
    event_log_path: Path | None,
    agent_mode: bool,
    gui_mirror: bool,
    gui_mirror_delay: float,
):
    if gui_mirror and event_log_path is None:
        event_log_path = default_gui_mirror_log_path(seed, level_id)
    session = TowerDefenseMcpSession(seed=seed, level_id=level_id, event_log_path=event_log_path, agent_mode=agent_mode)
    if gui_mirror and event_log_path is not None:
        spawn_gui_mirror(event_log_path, gui_mirror_delay)
    server = build_server(session)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    parser = argparse.ArgumentParser(description="MCP server for the turn-based tower defense CLI.")
    parser.add_argument("--seed", type=int, default=7, help="Initial random seed for the game session.")
    parser.add_argument("--level", type=int, default=1, help="Initial level number for the game session.")
    parser.add_argument("--event-log", type=Path, default=None, help="Optional JSONL event log path for tool calls and board snapshots.")
    parser.add_argument("--agent-mode", action="store_true", help="Expose only the one-attempt agent tool surface and sanitize help text.")
    parser.add_argument("--gui-mirror", action="store_true", help="Spawn a pygame window that follows the event log and mirrors the current board state.")
    parser.add_argument("--gui-mirror-delay", type=float, default=0.5, help="Seconds to display each mirrored board state before advancing.")
    args = parser.parse_args()
    anyio.run(
        async_main,
        args.seed,
        args.level,
        args.event_log,
        args.agent_mode,
        args.gui_mirror,
        args.gui_mirror_delay,
    )


if __name__ == "__main__":
    main()
