from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from statistics import fmean
from typing import Any

from td_benchmark import run_benchmark


ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "runs"
DEFAULT_LEVELS = [1, 2, 3, 4]
LEVEL_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4}


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def compact_model_slug(model: str) -> str:
    return "".join(ch for ch in model.lower() if ch.isalnum())


def reasoning_slug(reasoning_effort: str | None) -> str:
    return (reasoning_effort or "default").lower()


def default_log_dir_for(model: str, reasoning_effort: str | None) -> Path:
    return RUNS_ROOT / f"full-evals-{compact_model_slug(model)}-{reasoning_slug(reasoning_effort)}"


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = q * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    blend = index - lower
    return sorted_values[lower] * (1.0 - blend) + sorted_values[upper] * blend


def bootstrap_ci(
    values: list[float],
    *,
    resamples: int,
    confidence: float,
    rng: random.Random,
) -> tuple[float, float]:
    if not values:
        raise ValueError("bootstrap_ci requires at least one value")
    sample_size = len(values)
    estimates: list[float] = []
    for _ in range(resamples):
        sample = [values[rng.randrange(sample_size)] for _ in range(sample_size)]
        estimates.append(fmean(sample))
    estimates.sort()
    alpha = (1.0 - confidence) / 2.0
    return percentile(estimates, alpha), percentile(estimates, 1.0 - alpha)


def weighted_aggregate(level_means: dict[int, float]) -> float:
    missing = [level for level in DEFAULT_LEVELS if level not in level_means]
    if missing:
        raise ValueError(f"weighted aggregate requires levels 1-4; missing {missing}")
    numerator = sum(LEVEL_WEIGHTS[level] * level_means[level] for level in DEFAULT_LEVELS)
    denominator = sum(LEVEL_WEIGHTS.values())
    return numerator / denominator


def bootstrap_aggregate_ci(
    trial_scores_by_level: dict[int, list[float]],
    *,
    resamples: int,
    confidence: float,
    rng: random.Random,
) -> tuple[float, float]:
    missing = [level for level in DEFAULT_LEVELS if level not in trial_scores_by_level]
    if missing:
        raise ValueError(f"aggregate bootstrap requires levels 1-4; missing {missing}")
    estimates: list[float] = []
    alpha = (1.0 - confidence) / 2.0
    for _ in range(resamples):
        level_means: dict[int, float] = {}
        for level in DEFAULT_LEVELS:
            values = trial_scores_by_level[level]
            sample = [values[rng.randrange(len(values))] for _ in range(len(values))]
            level_means[level] = fmean(sample)
        estimates.append(weighted_aggregate(level_means))
    estimates.sort()
    return percentile(estimates, alpha), percentile(estimates, 1.0 - alpha)


def wins_count(report: dict[str, Any]) -> int:
    return sum(1 for trial in report["trial_results"] if trial.get("outcome") == "Win")


def numeric_trial_scores(report: dict[str, Any]) -> list[float]:
    scores: list[float] = []
    for score in report.get("trial_scores", []):
        if score is None:
            scores.append(0.0)
        else:
            scores.append(float(score))
    return scores


def build_summary(
    *,
    model: str,
    reasoning_effort: str | None,
    backend: str,
    trials: int,
    parallelism: int,
    resamples: int,
    confidence: float,
    benchmark_results: list[tuple[Path, dict[str, Any]]],
    bootstrap_seed: int,
) -> dict[str, Any]:
    level_summaries: list[dict[str, Any]] = []
    trial_scores_by_level: dict[int, list[float]] = {}
    mean_by_level: dict[int, float] = {}
    for report_path, report in sorted(benchmark_results, key=lambda item: item[1]["level_id"]):
        level_id = int(report["level_id"])
        trial_scores = numeric_trial_scores(report)
        level_summary: dict[str, Any] = {
            "level_id": level_id,
            "status": "complete",
            "average_score": 0.0,
            "confidence_interval": None,
            "wins": wins_count(report),
            "trials": len(trial_scores),
            "trials_requested": int(report.get("trials_requested", len(report.get("trial_results", [])))),
            "null_trial_indices": [
                int(trial["trial_index"])
                for trial in report.get("trial_results", [])
                if trial.get("score") is None
            ],
            "benchmark_report_path": str(report_path),
            "benchmark_dir": report["benchmark_dir"],
        }
        mean_score = fmean(trial_scores)
        ci_rng = random.Random(bootstrap_seed + level_id)
        ci_low, ci_high = bootstrap_ci(
            trial_scores,
            resamples=resamples,
            confidence=confidence,
            rng=ci_rng,
        )
        trial_scores_by_level[level_id] = trial_scores
        mean_by_level[level_id] = mean_score
        level_summary["average_score"] = mean_score
        level_summary["confidence_interval"] = {
            "low": ci_low,
            "high": ci_high,
            "confidence": confidence,
            "method": "bootstrap_percentile",
            "resamples": resamples,
        }
        level_summaries.append(level_summary)

    aggregate_mean = weighted_aggregate(mean_by_level)
    aggregate_low, aggregate_high = bootstrap_aggregate_ci(
        trial_scores_by_level,
        resamples=resamples,
        confidence=confidence,
        rng=random.Random(bootstrap_seed + 10_000),
    )

    aggregate_score: dict[str, Any] = {
        "formula": "(s1 + 2*s2 + 3*s3 + 4*s4) / 10",
        "value": aggregate_mean,
        "confidence_interval": {
            "low": aggregate_low,
            "high": aggregate_high,
            "confidence": confidence,
            "method": "bootstrap_percentile",
            "resamples": resamples,
        },
    }

    return {
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "levels": level_summaries,
        "aggregate_score": aggregate_score,
        "run_config": {
            "trials": trials,
            "parallelism": parallelism,
        },
    }


def format_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"## Full Eval Summary",
        "",
        f"- status: `{summary['status']}`",
        f"- backend: `{summary['backend']}`",
        f"- model: `{summary['model']}`",
        f"- reasoning effort: `{summary['reasoning_effort']}`",
        f"- trials per level: `{summary['run_config']['trials']}`",
        f"- parallelism: `{summary['run_config']['parallelism']}`",
        "",
        "Per-level scores are `mean (95% bootstrap CI)`.",
        "",
        "| Level | Score | Wins | Benchmark Report |",
        "| --- | --- | --- | --- |",
    ]
    for level_summary in summary["levels"]:
        ci = level_summary["confidence_interval"]
        score_text = f"{level_summary['average_score']:.3f} ({ci['low']:.3f}, {ci['high']:.3f})"
        wins_text = f"{level_summary['wins']}/{level_summary['trials_requested']}"
        lines.append(
            "| "
            f"Level {level_summary['level_id']} | "
            f"{score_text} | "
            f"{wins_text} | "
            f"{level_summary['benchmark_report_path']} |"
        )
    aggregate = summary["aggregate_score"]
    lines.extend(
        [
            "",
            f"Aggregate formula: `{aggregate['formula']}`",
            "",
        ]
    )
    aggregate_ci = aggregate["confidence_interval"]
    lines.append(f"- aggregate score: `{aggregate['value']:.4f}`")
    lines.append(f"- 95% bootstrap CI: `({aggregate_ci['low']:.4f}, {aggregate_ci['high']:.4f})`")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full 4-level TowDef evaluation for one model/reasoning setting and write summary reports."
    )
    parser.add_argument("--backend", choices=["codex", "responses"], default="codex")
    parser.add_argument("--model", default="gpt-5.4", help="Model name passed through to the benchmark harness.")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "minimal", "low", "medium", "high", "xhigh"],
        default="xhigh",
        help="Reasoning effort passed through to the benchmark harness.",
    )
    parser.add_argument("--levels", type=int, nargs="+", default=DEFAULT_LEVELS, help="Levels to evaluate. Full aggregate requires levels 1 2 3 4.")
    parser.add_argument("--trials", type=int, default=20, help="Trials per level.")
    parser.add_argument("--parallelism", type=int, default=5, help="Parallel trial count per level.")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory where the full-eval bundle will be written. Defaults to runs/full-evals-<model>-<reasoning>.",
    )
    parser.add_argument("--benchmark-seed", type=int, default=None, help="Optional seed for reproducible per-level trial-seed generation.")
    parser.add_argument("--bootstrap-resamples", type=int, default=20_000, help="Bootstrap resamples for confidence intervals.")
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level for bootstrap intervals.")
    parser.add_argument("--base-url", default=None, help="Responses-only base URL override.")
    parser.add_argument("--api-key-file", default=None, help="Responses-only API key file.")
    parser.add_argument("--max-rounds", type=int, default=None, help="Responses-only max rounds override.")
    args = parser.parse_args()
    if args.trials <= 0:
        raise SystemExit("--trials must be greater than 0")
    if args.parallelism <= 0:
        raise SystemExit("--parallelism must be greater than 0")
    if args.bootstrap_resamples <= 0:
        raise SystemExit("--bootstrap-resamples must be greater than 0")
    if not (0.0 < args.confidence < 1.0):
        raise SystemExit("--confidence must be between 0 and 1")
    return args


def main():
    args = parse_args()
    if args.log_dir is None:
        args.log_dir = default_log_dir_for(args.model, args.reasoning_effort)
    eval_dir = args.log_dir / f"td-full-eval-{now_slug()}"
    benchmark_root = eval_dir / f"benchmarks-{compact_model_slug(args.model)}-{reasoning_slug(args.reasoning_effort)}"
    eval_dir.mkdir(parents=True, exist_ok=True)
    benchmark_root.mkdir(parents=True, exist_ok=True)

    print(
        f"[config] backend={args.backend} model={args.model} reasoning={args.reasoning_effort} "
        f"trials={args.trials} parallelism={args.parallelism}"
    )
    print(f"[bundle] {eval_dir}")

    benchmark_seed_rng = random.Random(args.benchmark_seed) if args.benchmark_seed is not None else None
    benchmark_results: list[tuple[Path, dict[str, Any]]] = []

    for level_id in args.levels:
        print()
        print(f"[run] level {level_id}")
        benchmark_args = argparse.Namespace(
            backend=args.backend,
            level=level_id,
            trials=args.trials,
            benchmark_seed=None if benchmark_seed_rng is None else benchmark_seed_rng.randrange(1, 2**31),
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            log_dir=benchmark_root,
            parallelism=args.parallelism,
            base_url=args.base_url,
            api_key_file=args.api_key_file,
            max_rounds=args.max_rounds,
        )
        report_path, report = run_benchmark(benchmark_args)
        benchmark_results.append((report_path, report))

    summary = build_summary(
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        backend=args.backend,
        trials=args.trials,
        parallelism=args.parallelism,
        resamples=args.bootstrap_resamples,
        confidence=args.confidence,
        benchmark_results=benchmark_results,
        bootstrap_seed=args.benchmark_seed or 0,
    )

    summary_json_path = eval_dir / "full_eval_report.json"
    summary_md_path = eval_dir / "full_eval_report.md"
    summary_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    summary_md_path.write_text(format_summary_markdown(summary) + "\n", encoding="utf-8")

    aggregate = summary["aggregate_score"]
    aggregate_ci = aggregate["confidence_interval"]
    print()
    print(f"[summary.json] {summary_json_path}")
    print(f"[summary.md] {summary_md_path}")
    print(f"[aggregate] {aggregate['value']:.4f} (95% bootstrap CI {aggregate_ci['low']:.4f}, {aggregate_ci['high']:.4f})")


if __name__ == "__main__":
    main()
