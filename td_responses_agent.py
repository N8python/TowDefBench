from __future__ import annotations

import argparse
import atexit
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from cli_client import CLI_PROMPT, DEFENSE_DESCRIPTIONS, MONSTER_DESCRIPTIONS, RESOURCE_LABEL, TOKEN_BY_NAME
from game_server import score_summary_from_level
from td_mcp_server import TowerDefenseMcpSession

DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "n8programs/qwen3.5-27b-dwq")
DEFAULT_LOG_DIR = Path(__file__).resolve().parent / "runs"
DEFAULT_KEY_FILES = (
    Path(__file__).resolve().parent / "secret.txt",
    Path(__file__).resolve().parent / "openai_api_key.txt",
)
AUTOPLAY_KICKOFF = (
    "Beat the current level autonomously. Start by inspecting the board state if needed, then make whatever moves you think maximize the chance of winning. "
    "Do not ask the user what to do, do not ask for confirmation, and do not stop early. "
    "Keep playing until the level ends in either Win or Loss."
)
AUTOPLAY_CONTINUE = (
    "Continue playing. The level has not ended yet. "
    "Do not summarize yet and do not ask the user for input."
)
AUTOPLAY_SUMMARY = (
    "The level has ended. Give a concise summary of the outcome, whether it was a win or loss, and the most important decisions you made."
)

SYSTEM_PROMPT = (
    "You are an autonomous agent trying to beat a turn-based tower defense benchmark. "
    "You get exactly one attempt at the level. "
    "Use the provided tools whenever you need game state or want to act. "
    "Do not invent board state, defense cooldowns, or monster positions. "
    "Do not ask the user what to do, do not ask for confirmation, and do not stop until the level ends unless the run limit is reached."
)
CLI_BOARD_FOOTER = "deploy <name> <row> <col> | clear <row> <col> | inspect <row> <col> | next | level <n> | help | instructions | quit"
AGENT_BOARD_FOOTER = "deploy <name> <row> <col> | clear <row> <col> | inspect <row> <col> | guide <entry> | next | help | instructions"


def function_tool(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
        "strict": True,
    }


def _mask_secret(secret: str) -> str:
    secret = secret.strip()
    if not secret:
        return "<empty>"
    if len(secret) <= 10:
        return "*" * len(secret)
    return f"{secret[:12]}...{secret[-6:]}"


def _read_api_key_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def resolve_api_key(cli_api_key_file: str | None, base_url: str) -> tuple[str, str]:
    if cli_api_key_file:
        path = Path(cli_api_key_file).expanduser().resolve()
        value = _read_api_key_file(path)
        if not value:
            raise SystemExit(f"API key file is missing or empty: {path}")
        return value, f"file:{path}"

    env_api_key = os.getenv("OPENAI_API_KEY")
    if env_api_key:
        return env_api_key, "env:OPENAI_API_KEY"

    for path in DEFAULT_KEY_FILES:
        value = _read_api_key_file(path)
        if value:
            return value, f"file:{path}"

    if base_url.startswith("http://127.0.0.1:1234") or base_url.startswith("http://localhost:1234"):
        return "lm-studio", "builtin:lm-studio"

    searched = ", ".join(str(path) for path in DEFAULT_KEY_FILES)
    raise SystemExit(
        "OPENAI_API_KEY is required for non-local endpoints. "
        f"Set OPENAI_API_KEY, pass --api-key-file, or place a key in one of: {searched}"
    )


class RunLogger:
    def __init__(self, log_dir: Path, model: str, seed: int, level_id: int, base_url: str, system_prompt: str):
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.path = log_dir / f"td-run-{timestamp}.jsonl"
        self._handle = self.path.open("a", encoding="utf-8")
        atexit.register(self.close)
        self.log(
            "run_started",
            model=model,
            seed=seed,
            level_id=level_id,
            base_url=base_url,
            system_prompt=system_prompt,
        )

    def log(self, event_type: str, **data: Any):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }
        self._handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        self._handle.flush()

    def close(self):
        handle = getattr(self, "_handle", None)
        if handle is not None and not handle.closed:
            handle.close()


TOOL_SCHEMAS = [
    function_tool(
        "show",
        "Show the current board-first CLI view for the active tower defense session.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    function_tool(
        "help",
        "Show the quick-reference command and legend help for the tower defense CLI.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    function_tool(
        "instructions",
        "Show the gameplay instructions for this turn-based tower defense benchmark.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    function_tool(
        "status",
        "Show a detailed status readout for the current game session.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
    function_tool(
        "guide",
        "Show a detailed field guide entry using an alias, token, or full unit name such as pwr, lea, or powerplant.",
        {
            "type": "object",
            "properties": {
                "entry": {
                    "type": "string",
                    "description": "Defense or monster alias, token, or full name such as tur, lea, powerplant, or leaper.",
                },
            },
            "required": ["entry"],
            "additionalProperties": False,
        },
    ),
    function_tool(
        "deploy",
        "Deploy a defense at a 1-based row and column using the same defense names as the CLI.",
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Defense name or alias such as pwr, tur, ice, dbl, cru, bar, gre, or mne.",
                },
                "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
            },
            "required": ["name", "row", "col"],
            "additionalProperties": False,
        },
    ),
    function_tool(
        "clear",
        "Clear a defense from a 1-based row and column.",
        {
            "type": "object",
            "properties": {
                "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
            },
            "required": ["row", "col"],
            "additionalProperties": False,
        },
    ),
    function_tool(
        "inspect",
        "Inspect one tile at a 1-based row and column.",
        {
            "type": "object",
            "properties": {
                "row": {"type": "integer", "minimum": 1, "description": "1-based row number."},
                "col": {"type": "integer", "minimum": 1, "description": "1-based column number."},
            },
            "required": ["row", "col"],
            "additionalProperties": False,
        },
    ),
    function_tool(
        "next",
        "Advance the game by exactly one turn and return the updated board view.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    ),
]


class TowerDefenseResponsesAgent:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        seed: int = 7,
        level_id: int = 1,
        base_url: str = DEFAULT_BASE_URL,
        system_prompt: str = SYSTEM_PROMPT,
        log_dir: Path = DEFAULT_LOG_DIR,
        reasoning_effort: str | None = None,
        echo_actions: bool = True,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.system_prompt = system_prompt
        self.reasoning_effort = reasoning_effort
        self.echo_actions = echo_actions
        self.level_id = level_id
        self.session = TowerDefenseMcpSession(seed=seed, level_id=level_id)
        self.logger = RunLogger(
            log_dir=log_dir,
            model=model,
            seed=seed,
            level_id=level_id,
            base_url=base_url,
            system_prompt=system_prompt,
        )
        self.previous_response_id: str | None = None
        self.http = requests.Session()
        self.http.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )
        if self.reasoning_effort is not None:
            self.logger.log("reasoning_config", effort=self.reasoning_effort)
        self.logger.log("initial_board", board_view=self.session.show())
        self._log_board_snapshot(trigger="initial", command=None, result=self._agent_board_view())

    def score_summary(self) -> dict[str, Any]:
        return score_summary_from_level(self.session.game.level)

    def format_score_line(self) -> str:
        score_info = self.score_summary()
        if score_info["score"] is None:
            return "Score: unavailable (level not finished)."
        return (
            f"Score: {score_info['score']:.6f} "
            f"({score_info['outcome'].lower()}, wave {score_info['reached_waves']}/{score_info['total_waves']})"
        )

    def _agent_board_view(self) -> str:
        return self.session.show().replace(CLI_BOARD_FOOTER, AGENT_BOARD_FOOTER)

    def _agent_help_text(self) -> str:
        level = self.session.game.level
        defense_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(defense_cls.__name__, defense_cls.__name__[:3])}:{defense_cls().hp}"
            for defense_cls in level.definition.defense_roster
        )
        monster_tokens = " ".join(
            f"{TOKEN_BY_NAME.get(monster_cls.__name__, monster_cls.__name__[:3])}:{monster_cls().hp}"
            for monster_cls in self.session.game.instruction_monster_classes()
        )
        help_lines = [
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
        ]
        return "\n".join(help_lines)

    def _agent_instructions_text(self) -> str:
        level = self.session.game.level
        instruction_lines = [
            "Instructions:",
            "  This is a turn-based tower defense benchmark.",
            "  Goal: survive the monster waves.",
            "  Loss: if a monster reaches the left edge of the grid, you lose.",
            "  Turn flow: deploy, clear, or inspect as needed, then type `next` to resolve one turn.",
            f"  Energy: defenses cost {RESOURCE_LABEL}. You start with 2 {RESOURCE_LABEL}, gain 1 ambient {RESOURCE_LABEL} every 2 turns, and power plants make extra {RESOURCE_LABEL}.",
            "  Monsters: monsters enter from the right side and move left over time.",
            f"  Board shape: columns 1-{level.definition.deployable_cols} are deployable; column {level.board.entry_col + 1} is monster-entry only.",
            "  Recommendation: before acting, use `guide` on every defense and monster in this level.",
            "  This agent harness gives you one attempt only; there is no restart tool.",
            "",
            "Defenses in this level:",
            *[f"  {DEFENSE_DESCRIPTIONS.get(defense_cls.__name__, defense_cls.__name__)}" for defense_cls in level.definition.defense_roster],
            "",
            "Monsters in this level:",
            *[f"  {MONSTER_DESCRIPTIONS.get(monster_cls.__name__, monster_cls.__name__)}" for monster_cls in self.session.game.instruction_monster_classes()],
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
        ]
        return "\n".join(instruction_lines)

    def _format_response_error(self, response: requests.Response) -> tuple[str, str, str | None]:
        body = response.text
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        error_message = ""
        try:
            response_json = response.json()
        except ValueError:
            response_json = None
        if isinstance(response_json, dict):
            error = response_json.get("error")
            if isinstance(error, dict):
                error_message = str(error.get("message") or "")

        prefix = f"Responses API error {response.status_code}"
        if request_id:
            prefix = f"{prefix} (request id: {request_id})"

        if response.status_code == 401 and "api.responses.write" in error_message:
            details = [
                prefix,
                "OpenAI rejected this key for /v1/responses writes.",
                "Check that the caller is in the right project and role, and that a restricted key grants Write access to /v1/responses.",
                f"base_url={self.base_url}",
                f"model={self.model}",
                body,
            ]
            return "\n".join(details), body, request_id

        return f"{prefix}: {body}", body, request_id

    def _post_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.logger.log("responses_request", payload=payload)
        response = self.http.post(f"{self.base_url}/responses", json=payload, timeout=120)
        if response.status_code >= 400:
            error_text, body, request_id = self._format_response_error(response)
            self.logger.log(
                "responses_error",
                status_code=response.status_code,
                request_id=request_id,
                response_body=body,
            )
            raise RuntimeError(error_text)
        response_json = response.json()
        self.logger.log("responses_response", response=response_json)
        return response_json

    def _make_user_input(self, text: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]

    def _format_cli_command(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "guide":
            return f"guide {arguments['entry']}"
        if name == "deploy":
            return f"deploy {arguments['name']} {arguments['row']} {arguments['col']}"
        if name == "clear":
            return f"clear {arguments['row']} {arguments['col']}"
        if name == "inspect":
            return f"inspect {arguments['row']} {arguments['col']}"
        return name

    def _echo_tool_activity(self, name: str, arguments: dict[str, Any], output: str):
        if not self.echo_actions:
            return
        command_text = self._format_cli_command(name, arguments)
        board_view = self._agent_board_view()
        output_text = output.strip()
        board_text = board_view.strip()
        print(f"{CLI_PROMPT}{command_text}")
        if output_text:
            print(output)
        if not output_text or board_text not in output_text:
            print(board_view)
        print()

    def _log_board_snapshot(self, trigger: str, command: str | None, result: str):
        self.logger.log(
            "board_snapshot",
            trigger=trigger,
            command=command,
            result=result,
            snapshot=self.session.game.level.replay_snapshot(),
        )

    def _dispatch_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.logger.log("tool_call", name=name, arguments=arguments)
        command_text = self._format_cli_command(name, arguments)
        if name == "show":
            output = self._agent_board_view()
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "help":
            output = self._agent_help_text()
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "instructions":
            output = self._agent_instructions_text()
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "status":
            output = self.session.status()
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "guide":
            output = self.session.guide(str(arguments["entry"]))
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "deploy":
            output = self.session.deploy(str(arguments["name"]), int(arguments["row"]), int(arguments["col"]))
            output = output.replace(CLI_BOARD_FOOTER, AGENT_BOARD_FOOTER)
            self.logger.log("tool_output", name=name, output=output)
            self._log_board_snapshot(trigger=name, command=command_text, result=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "clear":
            output = self.session.clear(int(arguments["row"]), int(arguments["col"]))
            output = output.replace(CLI_BOARD_FOOTER, AGENT_BOARD_FOOTER)
            self.logger.log("tool_output", name=name, output=output)
            self._log_board_snapshot(trigger=name, command=command_text, result=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "inspect":
            output = self.session.inspect(int(arguments["row"]), int(arguments["col"]))
            self.logger.log("tool_output", name=name, output=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        if name == "next":
            output = self.session.next()
            output = output.replace(CLI_BOARD_FOOTER, AGENT_BOARD_FOOTER)
            self.logger.log("tool_output", name=name, output=output)
            self.logger.log("board_after_next", board_view=self._agent_board_view())
            self._log_board_snapshot(trigger=name, command=command_text, result=output)
            self._echo_tool_activity(name, arguments, output)
            return output
        raise ValueError(f"Unknown tool: {name}")

    def _extract_function_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in response.get("output", []) if item.get("type") == "function_call"]

    def _extract_text(self, response: dict[str, Any]) -> str:
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        chunks: list[str] = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def _create_initial_payload(self, user_text: str) -> dict[str, Any]:
        request_options: dict[str, Any] = {
            "model": self.model,
            "tools": TOOL_SCHEMAS,
        }
        if self.reasoning_effort is not None:
            request_options["reasoning"] = {"effort": self.reasoning_effort}

        if self.previous_response_id is None:
            return {
                **request_options,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": self.system_prompt}]},
                    *self._make_user_input(user_text),
                ],
            }
        return {
            **request_options,
            "previous_response_id": self.previous_response_id,
            "input": self._make_user_input(user_text),
        }

    def respond(self, user_text: str) -> str:
        self.logger.log("agent_prompt", prompt=user_text)
        response = self._post_response(self._create_initial_payload(user_text))

        while True:
            tool_calls = self._extract_function_calls(response)
            if not tool_calls:
                self.previous_response_id = response["id"]
                text = self._extract_text(response)
                self.logger.log("assistant_text", response_id=response["id"], text=text)
                return text

            tool_outputs = []
            for call in tool_calls:
                arguments = json.loads(call.get("arguments") or "{}")
                output = self._dispatch_tool(call["name"], arguments)
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": output,
                    }
                )

            response = self._post_response(
                {
                    "model": self.model,
                    "previous_response_id": response["id"],
                    "input": tool_outputs,
                    "tools": TOOL_SCHEMAS,
                    **({"reasoning": {"effort": self.reasoning_effort}} if self.reasoning_effort is not None else {}),
                }
            )

    def repl(self):
        print("OpenAI Responses tower defense agent")
        print("Type `quit` to exit.")
        print(f"[run log] {self.logger.path}")
        print(self._agent_board_view())
        while True:
            try:
                user_text = input("you> ").strip()
            except EOFError:
                print()
                break
            if not user_text:
                continue
            if user_text.lower() in {"quit", "q", "exit"}:
                break
            reply = self.respond(user_text)
            if reply:
                print(f"assistant> {reply}")

    def autoplay(
        self,
        max_rounds: int | None = None,
        verbose: bool = True,
    ) -> str:
        round_index = 0
        while True:
            if max_rounds is not None and round_index >= max_rounds:
                raise RuntimeError(f"Autoplay did not finish within {max_rounds} response rounds.")
            prompt = AUTOPLAY_KICKOFF if round_index == 0 else AUTOPLAY_CONTINUE
            if verbose:
                if max_rounds is None:
                    print(f"[autoplay] response round {round_index + 1}...")
                else:
                    print(f"[autoplay] response round {round_index + 1}/{max_rounds}...")
                print(f"[run log] {self.logger.path}")
            reply = self.respond(prompt)
            if verbose:
                header = self.session.game.header_line(self.session.game.level.snapshot())
                print(f"[autoplay] {header}")
                if reply:
                    print(f"[assistant] {reply}")
            if self.session.game.level.end_state:
                if verbose:
                    print("[autoplay] level ended; asking for final summary...")
                summary = self.respond(AUTOPLAY_SUMMARY)
                score_info = self.score_summary()
                self.logger.log(
                    "run_finished",
                    end_state=self.session.game.level.end_state,
                    summary=summary,
                    **score_info,
                )
                return summary
            round_index += 1

    def close(self):
        self.logger.log("run_closed", end_state=self.session.game.level.end_state, **self.score_summary())
        self.logger.close()


def main():
    parser = argparse.ArgumentParser(description="Drive the tower defense benchmark through the standard OpenAI Responses endpoint.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Responses model name.")
    parser.add_argument("--seed", type=int, default=7, help="Initial game seed.")
    parser.add_argument("--level", type=int, default=1, help="Initial level number to evaluate.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL for the OpenAI-compatible API.")
    parser.add_argument("--prompt", default=None, help="Optional one-shot user prompt.")
    parser.add_argument("--interactive", action="store_true", help="Open a manual chat loop instead of autoplay.")
    parser.add_argument("--max-rounds", type=int, default=None, help="Optional autonomous response-round limit.")
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR), help="Directory for timestamped run logs.")
    parser.add_argument("--api-key-file", default=None, help="Optional path to a file containing the OpenAI API key.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=None,
        help="Optional Responses reasoning effort, sent as reasoning.effort.",
    )
    args = parser.parse_args()

    api_key, api_key_source = resolve_api_key(args.api_key_file, args.base_url)

    agent = TowerDefenseResponsesAgent(
        api_key=api_key,
        model=args.model,
        seed=args.seed,
        level_id=args.level,
        base_url=args.base_url,
        log_dir=Path(args.log_dir),
        reasoning_effort=args.reasoning_effort,
    )
    agent.logger.log("auth_config", api_key_source=api_key_source, api_key_masked=_mask_secret(api_key))

    try:
        if args.prompt:
            print(f"[run log] {agent.logger.path}")
            reply = agent.respond(args.prompt)
            if reply:
                print(reply)
            return

        if args.interactive:
            agent.repl()
            return

        print(f"[run log] {agent.logger.path}")
        print(agent._agent_board_view())
        print()
        summary = agent.autoplay(max_rounds=args.max_rounds, verbose=True)
        print(summary)
        print(agent.format_score_line())
    finally:
        agent.close()


if __name__ == "__main__":
    main()
