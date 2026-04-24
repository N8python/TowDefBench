from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt


RUNS_ROOT = Path("/Users/natebreslow/Documents/pvzEval/runs")
DEFAULT_LEVELS = (1, 2, 3, 4)
DEFAULT_SERIES = (
    ("gpt-5.5", "xhigh"),
    ("gpt-5.4", "xhigh"),
    ("gpt-5.4-mini", "xhigh"),
)
REASONING_ORDER = ("none", "low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class SeriesSpec:
    model: str
    reasoning_effort: str

    @property
    def label(self) -> str:
        return f"{self.model} / {self.reasoning_effort}"


@dataclass
class BenchmarkResult:
    level_id: int
    model: str
    reasoning_effort: str
    average_score: float
    trial_scores: tuple[float, ...]
    confidence_interval: tuple[float, float] | None
    report_path: Path
    completed_at: datetime


@dataclass
class FullEvalResult:
    model: str
    reasoning_effort: str
    aggregate_score: float
    ci_low: float
    ci_high: float
    report_path: Path
    created_at: datetime


def parse_series(raw_values: list[str] | None) -> tuple[SeriesSpec, ...]:
    if not raw_values:
        return tuple(SeriesSpec(model, effort) for model, effort in DEFAULT_SERIES)

    parsed: list[SeriesSpec] = []
    for raw in raw_values:
        if ":" not in raw:
            raise SystemExit(f"Invalid --series value '{raw}'. Expected model:reasoning.")
        model, effort = raw.split(":", 1)
        parsed.append(SeriesSpec(model=model.strip(), reasoning_effort=effort.strip()))
    return tuple(parsed)


def parse_reference_series(raw_values: list[str] | None) -> tuple[SeriesSpec, ...]:
    return parse_series(raw_values)


def compact_model_slug(model: str) -> str:
    return "".join(ch for ch in model.lower() if ch.isalnum())


def coerce_trial_scores(raw_scores: list[float | int | str | None]) -> tuple[float, ...]:
    scores: list[float] = []
    for score in raw_scores:
        if score is None:
            scores.append(0.0)
        else:
            scores.append(float(score))
    return tuple(scores)


def parse_iso_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.min
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def bootstrap_ci95_bounds(scores: tuple[float, ...], samples: int = 5000) -> tuple[float, float]:
    if not scores:
        return (0.0, 0.0)
    if len(scores) == 1:
        return (scores[0], scores[0])

    seed_material = ",".join(f"{score:.12f}" for score in scores).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = random.Random(seed)

    resampled_means: list[float] = []
    score_list = list(scores)
    count = len(score_list)
    for _ in range(samples):
        total = 0.0
        for _ in range(count):
            total += score_list[rng.randrange(count)]
        resampled_means.append(total / count)

    resampled_means.sort()
    lower_index = int(0.025 * (samples - 1))
    upper_index = int(0.975 * (samples - 1))
    return (resampled_means[lower_index], resampled_means[upper_index])


def load_latest_benchmark_reports(
    runs_root: Path,
    backend: str,
    levels: tuple[int, ...],
    series_specs: tuple[SeriesSpec, ...],
) -> dict[tuple[str, str, int], BenchmarkResult]:
    wanted = {(spec.model, spec.reasoning_effort) for spec in series_specs}
    latest: dict[tuple[str, str, int], BenchmarkResult] = {}

    for report_path in runs_root.rglob("benchmark_report.json"):
        with report_path.open() as handle:
            report = json.load(handle)
        if report.get("backend") != backend:
            continue

        model = report.get("model")
        effort = report.get("reasoning_effort")
        if (model, effort) not in wanted:
            continue

        level_id = int(report["level_id"])
        if level_id not in levels:
            continue
        if report.get("average_score") is None:
            continue

        completed_at = parse_iso_datetime(report.get("completed_at"))
        result = BenchmarkResult(
            level_id=level_id,
            model=model,
            reasoning_effort=effort,
            average_score=float(report["average_score"]),
            trial_scores=coerce_trial_scores(report.get("trial_scores", [])),
            confidence_interval=None,
            report_path=report_path,
            completed_at=completed_at,
        )
        key = (model, effort, level_id)
        previous = latest.get(key)
        if previous is None or completed_at > previous.completed_at:
            latest[key] = result

    for report_path in runs_root.rglob("full_eval_report.json"):
        with report_path.open() as handle:
            report = json.load(handle)
        if report.get("backend") != backend:
            continue

        model = report.get("model")
        effort = report.get("reasoning_effort")
        if (model, effort) not in wanted:
            continue

        created_at = parse_iso_datetime(report.get("created_at"))
        for level_summary in report.get("levels", []):
            level_id = int(level_summary["level_id"])
            if level_id not in levels:
                continue
            average_score = level_summary.get("average_score")
            if average_score is None:
                continue
            ci = level_summary.get("confidence_interval") or {}
            result = BenchmarkResult(
                level_id=level_id,
                model=model,
                reasoning_effort=effort,
                average_score=float(average_score),
                trial_scores=(),
                confidence_interval=(float(ci["low"]), float(ci["high"])) if "low" in ci and "high" in ci else None,
                report_path=Path(level_summary.get("benchmark_report_path") or report_path),
                completed_at=created_at,
            )
            key = (model, effort, level_id)
            previous = latest.get(key)
            if previous is None or created_at > previous.completed_at:
                latest[key] = result

    return latest


def load_latest_full_eval_reports(
    runs_root: Path,
    backend: str,
    model: str,
) -> dict[str, FullEvalResult]:
    latest: dict[str, FullEvalResult] = {}

    for report_path in runs_root.rglob("full_eval_report.json"):
        with report_path.open() as handle:
            report = json.load(handle)
        if report.get("backend") != backend:
            continue
        if report.get("model") != model:
            continue

        effort = str(report.get("reasoning_effort"))
        aggregate = report.get("aggregate_score") or {}
        ci = aggregate.get("confidence_interval") or {}
        created_at = parse_iso_datetime(report.get("created_at"))
        result = FullEvalResult(
            model=model,
            reasoning_effort=effort,
            aggregate_score=float(aggregate["value"]),
            ci_low=float(ci["low"]),
            ci_high=float(ci["high"]),
            report_path=report_path,
            created_at=created_at,
        )
        previous = latest.get(effort)
        if previous is None or created_at > previous.created_at:
            latest[effort] = result

    return latest


def style_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    colors = {
        "gpt-5.5": "#047857",
        "gpt-5.4": "#B45309",
        "gpt-5.4-mini": "#2563EB",
    }
    linestyles = {
        "none": ":",
        "low": (0, (4, 2)),
        "medium": "--",
        "high": "-.",
        "xhigh": "-",
    }
    markers = {
        "none": "o",
        "low": "o",
        "medium": "o",
        "high": "s",
        "xhigh": "D",
    }
    return colors, linestyles, markers


def make_plot_by_level(
    results: dict[tuple[str, str, int], BenchmarkResult],
    levels: tuple[int, ...],
    series_specs: tuple[SeriesSpec, ...],
    output_path: Path,
    title: str,
) -> None:
    colors, linestyles, markers = style_maps()

    fig, ax = plt.subplots(figsize=(10, 6), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    x_positions = list(levels)
    series_scores: dict[SeriesSpec, list[float]] = {}
    series_ci_bounds: dict[SeriesSpec, list[tuple[float, float]]] = {}
    for spec in series_specs:
        benchmark_results = [results[(spec.model, spec.reasoning_effort, level)] for level in levels]
        scores = [result.average_score for result in benchmark_results]
        ci_bounds = [
            result.confidence_interval if result.confidence_interval is not None else bootstrap_ci95_bounds(result.trial_scores)
            for result in benchmark_results
        ]
        lower_errs = [max(0.0, score - lower) for score, (lower, _) in zip(scores, ci_bounds)]
        upper_errs = [max(0.0, upper - score) for score, (_, upper) in zip(scores, ci_bounds)]
        series_scores[spec] = scores
        series_ci_bounds[spec] = ci_bounds
        line = ax.plot(
            x_positions,
            scores,
            label=spec.label,
            color=colors.get(spec.model, "#374151"),
            linestyle=linestyles.get(spec.reasoning_effort, "-"),
            marker=markers.get(spec.reasoning_effort, "o"),
            linewidth=2.4,
            markersize=7,
        )[0]
        ax.errorbar(
            x_positions,
            scores,
            yerr=[lower_errs, upper_errs],
            fmt="none",
            ecolor=line.get_color(),
            elinewidth=1.2,
            capsize=4,
            capthick=1.2,
            alpha=0.4,
            zorder=1,
        )

    label_min_gap = 0.045
    label_base_offset = 0.022
    x_offsets = (-0.06, -0.02, 0.02, 0.06, -0.09, 0.09)
    for level_index, x in enumerate(x_positions):
        level_labels: list[tuple[float, SeriesSpec]] = []
        for spec in series_specs:
            level_labels.append((series_scores[spec][level_index], spec))

        level_labels.sort(key=lambda item: item[0])
        label_positions: list[tuple[float, float, SeriesSpec]] = []
        for score, spec in level_labels:
            label_y = score + label_base_offset
            if label_positions:
                label_y = max(label_y, label_positions[-1][1] + label_min_gap)
            label_positions.append((score, label_y, spec))

        overflow = label_positions[-1][1] - 1.055
        if overflow > 0:
            label_positions = [(score, label_y - overflow, spec) for score, label_y, spec in label_positions]

        for idx, (score, label_y, spec) in enumerate(label_positions):
            ax.text(
                x + x_offsets[idx],
                label_y,
                f"{score:.3f}".rstrip("0").rstrip("."),
                ha="center",
                va="bottom",
                fontsize=8.5,
                color=colors.get(spec.model, "#374151"),
                fontweight="bold",
            )

    max_top = max(
        series_ci_bounds[spec][level_index][1]
        for spec in series_specs
        for level_index in range(len(levels))
    )
    ax.set_xlim(min(levels) - 0.15, max(levels) + 0.15)
    ax.set_ylim(0, max(1.08, max_top + 0.12))
    ax.set_xticks(levels, [f"Level {level}" for level in levels])
    ax.set_ylabel("Average Score")
    ax.set_title(title, pad=14, fontsize=15, fontweight="bold")
    ax.grid(axis="y", color="#D7D0C1", linestyle="--", linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=2, loc="upper right")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.11, right=0.97, top=0.88, bottom=0.13)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def make_plot_aggregate_by_reasoning(
    results: dict[str, FullEvalResult],
    backend: str,
    model: str,
    reference_points: tuple[SeriesSpec, ...],
    output_path: Path,
    title: str,
) -> None:
    colors, _, _ = style_maps()
    efforts = [effort for effort in REASONING_ORDER if effort in results]
    if not efforts:
        raise SystemExit(f"No full eval reports found for model={model!r}.")

    x_positions = list(range(len(efforts)))
    scores = [results[effort].aggregate_score for effort in efforts]
    lower_errs = [max(0.0, result.aggregate_score - result.ci_low) for result in (results[e] for e in efforts)]
    upper_errs = [max(0.0, result.ci_high - result.aggregate_score) for result in (results[e] for e in efforts)]

    fig, ax = plt.subplots(figsize=(8.5, 5.6), dpi=180)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    color = colors.get(model, "#374151")
    ax.plot(
        x_positions,
        scores,
        color=color,
        marker="o",
        linewidth=2.6,
        markersize=7,
    )
    ax.errorbar(
        x_positions,
        scores,
        yerr=[lower_errs, upper_errs],
        fmt="none",
        ecolor=color,
        elinewidth=1.25,
        capsize=4,
        capthick=1.25,
        alpha=0.45,
        zorder=1,
    )

    for x, score in zip(x_positions, scores):
        ax.text(
            x,
            score + 0.012,
            f"{score:.3f}".rstrip("0").rstrip("."),
            ha="center",
            va="bottom",
            fontsize=9,
            color=color,
            fontweight="bold",
        )

    reference_tops: list[float] = []
    if reference_points:
        reference_results: dict[SeriesSpec, FullEvalResult] = {}
        for spec in reference_points:
            ref_map = load_latest_full_eval_reports(RUNS_ROOT, backend, spec.model)
            if spec.reasoning_effort not in ref_map:
                raise SystemExit(f"Missing full eval report for reference series {spec.label}.")
            reference_results[spec] = ref_map[spec.reasoning_effort]

        for spec in reference_points:
            result = reference_results[spec]
            reference_tops.append(result.ci_high)
            if spec.reasoning_effort not in efforts:
                continue
            x = efforts.index(spec.reasoning_effort)
            color = colors.get(spec.model, "#374151")
            ax.errorbar(
                [x],
                [result.aggregate_score],
                yerr=[
                    [max(0.0, result.aggregate_score - result.ci_low)],
                    [max(0.0, result.ci_high - result.aggregate_score)],
                ],
                fmt="none",
                ecolor=color,
                elinewidth=1.25,
                capsize=4,
                capthick=1.25,
                alpha=0.45,
                zorder=2,
            )
            ax.scatter(
                [x],
                [result.aggregate_score],
                s=68,
                color=color,
                marker="s",
                edgecolors="white",
                linewidths=0.8,
                zorder=3,
                label=spec.label,
            )
            ax.text(
                x + 0.05,
                result.aggregate_score + 0.012,
                f"{result.aggregate_score:.3f}".rstrip("0").rstrip("."),
                ha="left",
                va="bottom",
                fontsize=8.5,
                color=color,
                fontweight="bold",
            )

    max_top = max([results[effort].ci_high for effort in efforts] + reference_tops)
    right_padding = 0.3 if reference_points else 0.15
    ax.set_xlim(-0.25, len(efforts) - 1 + right_padding if len(efforts) > 1 else 0.25 + right_padding)
    ax.set_ylim(0, max(0.25, max_top + 0.1))
    ax.set_xticks(x_positions, [effort for effort in efforts])
    ax.set_xlabel("Reasoning Effort")
    ax.set_ylabel("Aggregate Score")
    ax.set_title(title, pad=14, fontsize=15, fontweight="bold")
    ax.grid(axis="y", color="#D7D0C1", linestyle="--", linewidth=0.8, alpha=0.9)
    ax.set_axisbelow(True)
    if reference_points:
        ax.legend(frameon=False, loc="upper left")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.87, bottom=0.15)
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def default_output_path(plot_type: str, backend: str, model: str | None) -> Path:
    if plot_type == "aggregate-by-reasoning":
        if model is None:
            raise SystemExit("--model is required for aggregate-by-reasoning plots.")
        return Path(f"/Users/natebreslow/Documents/pvzEval/output/{compact_model_slug(model)}_{backend}_reasoning_curve.png")
    return Path("/Users/natebreslow/Documents/pvzEval/output/benchmark_scores_codex_lines.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reusable benchmark plotting utility.")
    parser.add_argument("--backend", default="codex")
    parser.add_argument(
        "--plot-type",
        choices=("by-level", "aggregate-by-reasoning"),
        default="by-level",
        help="Which benchmark plot to render.",
    )
    parser.add_argument(
        "--series",
        action="append",
        default=None,
        help="For by-level plots: series in the form model:reasoning_effort. Repeat to add multiple lines.",
    )
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=list(DEFAULT_LEVELS),
        help="For by-level plots: levels to include.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="For aggregate-by-reasoning plots: model to plot across reasoning efforts.",
    )
    parser.add_argument(
        "--reference-series",
        action="append",
        default=None,
        help="For aggregate-by-reasoning plots: standalone comparison point(s) in the form model:reasoning_effort.",
    )
    parser.add_argument("--title", default=None, help="Optional plot title override.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else default_output_path(args.plot_type, args.backend, args.model)

    if args.plot_type == "by-level":
        series_specs = parse_series(args.series)
        levels = tuple(args.levels)
        results = load_latest_benchmark_reports(RUNS_ROOT, args.backend, levels, series_specs)
        missing = [
            f"{spec.label} / level {level}"
            for spec in series_specs
            for level in levels
            if (spec.model, spec.reasoning_effort, level) not in results
        ]
        if missing:
            raise SystemExit("Missing benchmark reports for: " + ", ".join(missing))

        title = args.title or f"{args.backend.capitalize()} benchmark scores by level"
        make_plot_by_level(results, levels, series_specs, output_path, title)
    else:
        if not args.model:
            raise SystemExit("--model is required for aggregate-by-reasoning plots.")
        results = load_latest_full_eval_reports(RUNS_ROOT, args.backend, args.model)
        reference_points = parse_reference_series(args.reference_series)
        missing_efforts = [effort for effort in REASONING_ORDER if effort not in results]
        if missing_efforts:
            print(f"[plot] missing reasoning efforts for {args.model}: {', '.join(missing_efforts)}")
        title = args.title or f"{args.model} aggregate score by reasoning effort"
        make_plot_aggregate_by_reasoning(results, args.backend, args.model, reference_points, output_path, title)

    print(output_path)


if __name__ == "__main__":
    main()
