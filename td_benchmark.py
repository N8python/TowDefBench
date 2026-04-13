from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from statistics import fmean
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_BENCHMARK_LOG_DIR = ROOT / "runs" / "benchmarks"
RESPONSES_HARNESS = ROOT / "td_responses_agent.py"
CODEX_HARNESS = ROOT / "td_codex_agent.py"
SEED_UPPER_BOUND = 2**31 - 1
WAVE_PROGRESS_RE = re.compile(r"\bWaves (\d+)/(\d+)\b")
TURN_PROGRESS_RE = re.compile(r"\bTurn (\d+)\b")
CONSOLE_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def console_print(message: str):
    with CONSOLE_LOCK:
        print(message, flush=True)


def benchmark_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def write_report(path: Path, report: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


class TrialStdoutMonitor:
    def __init__(self, *, backend: str, trial_index: int, trials_requested: int, stdout_path: Path):
        self.backend = backend
        self.trial_index = trial_index
        self.trials_requested = trials_requested
        self._last_wave = 0
        self._last_reasoning_line = ""
        self._in_tool_block = False

    def handle_line(self, line: str):
        self._maybe_log_wave(line)
        if self.backend != "codex":
            return

        stripped = line.strip()
        if stripped.startswith("td> "):
            self._in_tool_block = True
            return
        if self._in_tool_block:
            if not stripped:
                self._in_tool_block = False
            return
        if not self._looks_like_codex_summary(stripped):
            return
        if stripped == self._last_reasoning_line:
            return
        self._last_reasoning_line = stripped
        console_print(f"[codex {self.trial_index}/{self.trials_requested}] {stripped}")

    def _maybe_log_wave(self, line: str):
        match = WAVE_PROGRESS_RE.search(line)
        if match is None:
            return
        reached_waves = int(match.group(1))
        total_waves = int(match.group(2))
        if reached_waves <= self._last_wave:
            return
        self._last_wave = reached_waves
        turn_match = TURN_PROGRESS_RE.search(line)
        if turn_match is None:
            console_print(f"[wave] trial {self.trial_index}/{self.trials_requested} reached wave {reached_waves}/{total_waves}")
            return
        console_print(
            f"[wave] trial {self.trial_index}/{self.trials_requested} reached wave {reached_waves}/{total_waves} on turn {turn_match.group(1)}"
        )

    @staticmethod
    def _looks_like_codex_summary(stripped: str) -> bool:
        if not stripped:
            return False
        if stripped.startswith(("[run log]", "[stdout]", "[score]", "[final summary]", "[dry run]")):
            return False
        if stripped.startswith(("[benchmark]", "[report]", "[start]", "[done]", "[queue]", "[parallel]", "[final]")):
            return False
        if stripped.startswith(("Level ", "Roster:", "Commands:", "Board legend:", "Roster legend:", "Examples:", "Instructions:")):
            return False
        if stripped.startswith(("deploy ", "clear ", "inspect ", "next", "level ", "help", "instructions", "guide ")):
            return False
        if stripped.startswith(("Type:", "Abbrev:", "Behavior:", "Use:", "Threat:", "Role:", "Energy", "Waves")):
            return False
        if set(stripped) <= set("+-|. :0123456789/"):
            return False
        return True


def build_trial_command(args: argparse.Namespace, *, seed: int, trial_dir: Path) -> list[str]:
    if args.backend == "responses":
        harness_path = RESPONSES_HARNESS
    else:
        harness_path = CODEX_HARNESS

    command = [
        sys.executable,
        str(harness_path),
        "--level",
        str(args.level),
        "--seed",
        str(seed),
        "--log-dir",
        str(trial_dir),
    ]
    if args.model:
        command.extend(["--model", args.model])
    if args.reasoning_effort:
        command.extend(["--reasoning-effort", args.reasoning_effort])
    if args.backend == "responses":
        if args.base_url:
            command.extend(["--base-url", args.base_url])
        if args.api_key_file:
            command.extend(["--api-key-file", args.api_key_file])
        if args.max_rounds is not None:
            command.extend(["--max-rounds", str(args.max_rounds)])
    return command


def find_trial_run_log(trial_dir: Path) -> Path | None:
    run_logs = sorted(trial_dir.glob("*.jsonl"))
    if not run_logs:
        return None
    if len(run_logs) == 1:
        return run_logs[0]
    preferred_prefix = "td-run-" if any(path.name.startswith("td-run-") for path in run_logs) else "td-codex-run-"
    preferred = [path for path in run_logs if path.name.startswith(preferred_prefix)]
    if len(preferred) == 1:
        return preferred[0]
    return run_logs[-1]


def extract_trial_score(run_log_path: Path | None) -> dict[str, Any]:
    if run_log_path is None or not run_log_path.exists():
        return {
            "score": None,
            "outcome": None,
            "reached_waves": None,
            "total_waves": None,
            "transcript_path": None,
            "run_closed_present": False,
        }

    records = read_jsonl(run_log_path)
    for record in reversed(records):
        if record.get("event") != "run_closed":
            continue
        score = record.get("score")
        return {
            "score": float(score) if isinstance(score, (int, float)) else None,
            "outcome": record.get("outcome"),
            "reached_waves": record.get("reached_waves"),
            "total_waves": record.get("total_waves"),
            "transcript_path": record.get("transcript_path"),
            "run_closed_present": True,
        }
    return {
        "score": None,
        "outcome": None,
        "reached_waves": None,
        "total_waves": None,
        "transcript_path": None,
        "run_closed_present": False,
    }


def summarize_trial(trial: dict[str, Any]) -> str:
    if trial.get("status") == "error":
        return (
            f"trial {trial['trial_index']}/{trial['trials_requested']} | seed {trial['seed']} | "
            f"error: {trial['error']}"
        )
    score = trial["score"]
    if score is None:
        return (
            f"trial {trial['trial_index']}/{trial['trials_requested']} | seed {trial['seed']} | "
            f"score missing | exit {trial['returncode']}"
        )
    return (
        f"trial {trial['trial_index']}/{trial['trials_requested']} | seed {trial['seed']} | "
        f"score {score:.6f} ({trial['outcome'].lower()}, wave {trial['reached_waves']}/{trial['total_waves']})"
    )


def sorted_trial_results(trial_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(trial_results, key=lambda trial: trial["trial_index"])


def build_report(
    args: argparse.Namespace,
    *,
    benchmark_dir: Path,
    report_path: Path,
    started_at: str,
    completed_at: str | None,
    trial_results: list[dict[str, Any]],
) -> dict[str, Any]:
    scored_trials = [trial for trial in trial_results if trial["score"] is not None]
    all_trials_scored = len(scored_trials) == len(trial_results) == args.trials
    average_score = fmean(trial["score"] for trial in scored_trials) if all_trials_scored else None
    trial_scores = [trial["score"] for trial in trial_results]
    return {
        "status": "complete" if all_trials_scored else "incomplete",
        "started_at": started_at,
        "completed_at": completed_at,
        "backend": args.backend,
        "level_id": args.level,
        "trials_requested": args.trials,
        "trials_completed": len(trial_results),
        "parallelism": args.parallelism,
        "benchmark_seed": args.benchmark_seed,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "base_url": args.base_url if args.backend == "responses" else None,
        "max_rounds": args.max_rounds if args.backend == "responses" else None,
        "benchmark_dir": str(benchmark_dir),
        "report_path": str(report_path),
        "average_score": average_score,
        "trial_scores": trial_scores,
        "trial_results": trial_results,
    }


def run_trial(args: argparse.Namespace, *, benchmark_dir: Path, trial_index: int, seed: int) -> dict[str, Any]:
    trial_dir = benchmark_dir / f"trial-{trial_index:02d}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "benchmark_stdout.txt"
    stderr_path = trial_dir / "benchmark_stderr.txt"
    command = build_trial_command(args, seed=seed, trial_dir=trial_dir)
    started_at = now_iso()
    start_time = time.monotonic()
    monitor = TrialStdoutMonitor(backend=args.backend, trial_index=trial_index, trials_requested=args.trials, stdout_path=stdout_path)
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            stdout_handle.write(line)
            stdout_handle.flush()
            monitor.handle_line(line)
        returncode = process.wait()
    duration_seconds = time.monotonic() - start_time
    completed_at = now_iso()
    run_log_path = find_trial_run_log(trial_dir)
    score_info = extract_trial_score(run_log_path)
    return {
        "trial_index": trial_index,
        "trials_requested": args.trials,
        "status": "scored" if score_info["score"] is not None else "missing_score",
        "seed": seed,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "command": command,
        "returncode": returncode,
        "trial_dir": str(trial_dir),
        "run_log_path": str(run_log_path) if run_log_path else None,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        **score_info,
    }


def error_trial_result(
    args: argparse.Namespace,
    *,
    benchmark_dir: Path,
    trial_index: int,
    seed: int,
    error: str,
) -> dict[str, Any]:
    trial_dir = benchmark_dir / f"trial-{trial_index:02d}"
    stdout_path = trial_dir / "benchmark_stdout.txt"
    stderr_path = trial_dir / "benchmark_stderr.txt"
    return {
        "trial_index": trial_index,
        "trials_requested": args.trials,
        "status": "error",
        "seed": seed,
        "started_at": None,
        "completed_at": now_iso(),
        "duration_seconds": None,
        "command": None,
        "returncode": None,
        "trial_dir": str(trial_dir),
        "run_log_path": None,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "score": None,
        "outcome": None,
        "reached_waves": None,
        "total_waves": None,
        "transcript_path": None,
        "run_closed_present": False,
        "error": error,
    }


def write_progress_report(
    args: argparse.Namespace,
    *,
    benchmark_dir: Path,
    report_path: Path,
    started_at: str,
    completed_at: str | None,
    trial_results: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_results = sorted_trial_results(trial_results)
    report = build_report(
        args,
        benchmark_dir=benchmark_dir,
        report_path=report_path,
        started_at=started_at,
        completed_at=completed_at,
        trial_results=ordered_results,
    )
    write_report(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multiple seeded tower defense benchmark trials through either the Responses or Codex harness and aggregate the scores."
    )
    parser.add_argument("--backend", choices=["responses", "codex"], default="responses", help="Which agent harness to use.")
    parser.add_argument("--level", type=int, default=1, help="Level number to evaluate.")
    parser.add_argument("--trials", type=int, default=5, help="Number of randomized trials to run.")
    parser.add_argument("--benchmark-seed", type=int, default=None, help="Optional seed for reproducible per-trial seed generation.")
    parser.add_argument("--model", default=None, help="Optional model override passed through to the selected harness.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default=None,
        help="Optional reasoning effort passed through to the selected harness.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_BENCHMARK_LOG_DIR,
        help="Directory where the benchmark report and per-trial rollout folders will be written.",
    )
    parser.add_argument("--parallelism", type=int, default=1, help="Maximum number of trials to run concurrently.")
    parser.add_argument("--base-url", default=None, help="Responses-only override for the OpenAI-compatible base URL.")
    parser.add_argument("--api-key-file", default=None, help="Responses-only path to a file containing the API key.")
    parser.add_argument("--max-rounds", type=int, default=None, help="Responses-only response-round cap.")
    args = parser.parse_args()
    if args.trials <= 0:
        raise SystemExit("--trials must be greater than 0")
    if args.parallelism <= 0:
        raise SystemExit("--parallelism must be greater than 0")
    return args


def run_benchmark(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    benchmark_dir = args.log_dir / f"td-benchmark-{benchmark_slug()}"
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    report_path = benchmark_dir / "benchmark_report.json"
    started_at = now_iso()
    trial_results: list[dict[str, Any]] = []

    if args.benchmark_seed is None:
        seed_rng: random.Random | random.SystemRandom = random.SystemRandom()
    else:
        seed_rng = random.Random(args.benchmark_seed)

    trial_seeds = [seed_rng.randrange(1, SEED_UPPER_BOUND + 1) for _ in range(args.trials)]

    console_print(f"[benchmark] {benchmark_dir}")
    console_print(f"[report] {report_path}")

    if args.parallelism == 1:
        for trial_index, seed in enumerate(trial_seeds, start=1):
            console_print(f"[start] trial {trial_index}/{args.trials} seed={seed}")
            try:
                trial_result = run_trial(args, benchmark_dir=benchmark_dir, trial_index=trial_index, seed=seed)
            except Exception as exc:  # pragma: no cover - defensive path
                trial_result = error_trial_result(
                    args,
                    benchmark_dir=benchmark_dir,
                    trial_index=trial_index,
                    seed=seed,
                    error=str(exc),
                )
            trial_results.append(trial_result)
            console_print(f"[done] {summarize_trial(trial_result)}")
            write_progress_report(
                args,
                benchmark_dir=benchmark_dir,
                report_path=report_path,
                started_at=started_at,
                completed_at=None,
                trial_results=trial_results,
            )
    else:
        worker_count = min(args.parallelism, args.trials)
        console_print(f"[parallel] running up to {worker_count} trials at once")
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_trial = {}
            for trial_index, seed in enumerate(trial_seeds, start=1):
                console_print(f"[queue] trial {trial_index}/{args.trials} seed={seed}")
                future = executor.submit(run_trial, args, benchmark_dir=benchmark_dir, trial_index=trial_index, seed=seed)
                future_to_trial[future] = (trial_index, seed)

            for future in as_completed(future_to_trial):
                trial_index, seed = future_to_trial[future]
                try:
                    trial_result = future.result()
                except Exception as exc:  # pragma: no cover - defensive path
                    trial_result = error_trial_result(
                        args,
                        benchmark_dir=benchmark_dir,
                        trial_index=trial_index,
                        seed=seed,
                        error=str(exc),
                    )
                trial_results.append(trial_result)
                console_print(f"[done] {summarize_trial(trial_result)}")
                write_progress_report(
                    args,
                    benchmark_dir=benchmark_dir,
                    report_path=report_path,
                    started_at=started_at,
                    completed_at=None,
                    trial_results=trial_results,
                )

    completed_at = now_iso()
    report = write_progress_report(
        args,
        benchmark_dir=benchmark_dir,
        report_path=report_path,
        started_at=started_at,
        completed_at=completed_at,
        trial_results=trial_results,
    )

    if report["average_score"] is None:
        console_print("[final] benchmark incomplete; one or more trials did not produce a score")
        return report_path, report

    console_print(f"[final] average score {report['average_score']:.6f} over {args.trials} trials")
    return report_path, report


def main():
    args = parse_args()
    _report_path, report = run_benchmark(args)
    if report["average_score"] is None:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
