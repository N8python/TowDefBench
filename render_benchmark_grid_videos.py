from __future__ import annotations

import argparse
import glob
import json
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from pygame_client import GameApp, SCREEN_HEIGHT, SCREEN_WIDTH, load_replay_frames


ROOT = Path(__file__).resolve().parent
DEFAULT_BENCHMARK_ROOTS = [
    ROOT / "runs" / "benchmarks",
]
DEFAULT_OUT_DIR = ROOT / "output" / "videos"
DEFAULT_LEVELS = [1, 2, 3, 4]
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_REASONING_EFFORT = "xhigh"
GRID_COLS = 5
GRID_ROWS = 4
FPS = 4
VIDEO_WIDTH = 2560
MARGIN = 16
GAP = 16
HEADER_HEIGHT = 60
CELL_WIDTH = (VIDEO_WIDTH - MARGIN * 2 - GAP * (GRID_COLS - 1)) // GRID_COLS
CELL_HEIGHT = round(CELL_WIDTH * SCREEN_HEIGHT / SCREEN_WIDTH)
VIDEO_HEIGHT = HEADER_HEIGHT + MARGIN * 2 + CELL_HEIGHT * GRID_ROWS + GAP * (GRID_ROWS - 1)
BG_COLOR = (18, 20, 24)
HEADER_COLOR = (245, 241, 232)
SUBHEADER_COLOR = (192, 199, 208)
LABEL_BG = (10, 12, 16, 210)
LABEL_FG = (245, 241, 232)


@dataclass
class TrialVideo:
    trial_index: int
    seed: int
    score: float
    outcome: str
    reached_waves: int
    total_waves: int
    replay_frames: list
    app: GameApp


def discover_report(level_id: int, model: str, reasoning_effort: str, benchmark_roots: list[Path]) -> Path:
    candidates: list[tuple[str, Path]] = []
    for root in benchmark_roots:
        pattern = str(root / "td-benchmark-*" / "benchmark_report.json")
        for path_str in glob.glob(pattern):
            path = Path(path_str)
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if report.get("backend") != "codex":
                continue
            if report.get("model") != model:
                continue
            if report.get("reasoning_effort") != reasoning_effort:
                continue
            if report.get("level_id") != level_id:
                continue
            candidates.append((report.get("started_at") or "", path))
    if not candidates:
        raise SystemExit(
            f"Could not find a benchmark report for model={model}, reasoning={reasoning_effort}, level={level_id}."
        )
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def build_trial_videos(report_path: Path) -> tuple[dict, list[TrialVideo]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    trial_results = sorted(report["trial_results"], key=lambda result: result["trial_index"])
    if len(trial_results) != GRID_COLS * GRID_ROWS:
        raise SystemExit(
            f"{report_path} has {len(trial_results)} trials; expected exactly {GRID_COLS * GRID_ROWS} for a 5x4 grid."
        )

    trials: list[TrialVideo] = []
    for result in trial_results:
        run_log_path = Path(result["run_log_path"])
        replay_frames = load_replay_frames(run_log_path)
        app = GameApp(replay_frames=replay_frames, replay_delay=1.0)
        app.screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        app.message_until = 0
        app.banner_until = 0
        trials.append(
            TrialVideo(
                trial_index=result["trial_index"],
                seed=result["seed"],
                score=float(result["score"]),
                outcome=str(result["outcome"]),
                reached_waves=int(result["reached_waves"]),
                total_waves=int(result["total_waves"]),
                replay_frames=replay_frames,
                app=app,
            )
        )
    return report, trials


def fit_text(text: str, font: pygame.font.Font, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    trimmed = text
    while trimmed and font.size(trimmed + "...")[0] > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "...") if trimmed else "..."


def draw_trial_label(surface: pygame.Surface, font: pygame.font.Font, x: int, y: int, width: int, trial: TrialVideo, frame_index: int):
    label_rect = pygame.Rect(x, y, width, 26)
    panel = pygame.Surface(label_rect.size, pygame.SRCALPHA)
    panel.fill(LABEL_BG)
    surface.blit(panel, label_rect.topleft)
    frame_number = min(frame_index + 1, len(trial.replay_frames))
    summary = (
        f"T{trial.trial_index:02d}  {trial.outcome}  "
        f"{trial.score:.3f}  W{trial.reached_waves}/{trial.total_waves}  "
        f"S{trial.seed}  F{frame_number}/{len(trial.replay_frames)}"
    )
    clipped = fit_text(summary, font, width - 12)
    text = font.render(clipped, True, LABEL_FG)
    surface.blit(text, (x + 6, y + 4))


def render_level_video(
    *,
    report_path: Path,
    out_path: Path,
    fps: int,
    max_states: int | None = None,
):
    report, trials = build_trial_videos(report_path)
    max_frame_count = max(len(trial.replay_frames) for trial in trials)
    if max_states is not None:
        max_frame_count = min(max_frame_count, max_states)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(out_path),
    ]

    process = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)
    assert process.stdin is not None

    composite = pygame.Surface((VIDEO_WIDTH, VIDEO_HEIGHT))
    header_font = pygame.font.SysFont("georgia", 34, bold=True)
    subheader_font = pygame.font.SysFont("trebuchetms", 18)
    label_font = pygame.font.SysFont("trebuchetms", 18, bold=True)

    title = f"{report['model']} / {report['reasoning_effort']} / Level {report['level_id']} / 20 trials"
    subtitle = f"Latest codex benchmark report: {report_path.parent.name}"

    try:
        for frame_index in range(max_frame_count):
            composite.fill(BG_COLOR)
            title_surface = header_font.render(title, True, HEADER_COLOR)
            subtitle_surface = subheader_font.render(subtitle, True, SUBHEADER_COLOR)
            composite.blit(title_surface, (MARGIN, 10))
            composite.blit(subtitle_surface, (MARGIN, 42))

            for grid_index, trial in enumerate(trials):
                replay_index = min(frame_index, len(trial.replay_frames) - 1)
                if trial.app.replay_index != replay_index:
                    trial.app.apply_replay_frame(replay_index, reset_timing=False)
                trial.app.message_until = 0
                trial.app.banner_until = 0
                trial.app.draw()
                scaled = pygame.transform.smoothscale(trial.app.screen, (CELL_WIDTH, CELL_HEIGHT))

                row = grid_index // GRID_COLS
                col = grid_index % GRID_COLS
                x = MARGIN + col * (CELL_WIDTH + GAP)
                y = HEADER_HEIGHT + MARGIN + row * (CELL_HEIGHT + GAP)
                composite.blit(scaled, (x, y))
                draw_trial_label(composite, label_font, x, y, CELL_WIDTH, trial, replay_index)

            process.stdin.write(pygame.image.tostring(composite, "RGB"))
            if frame_index == 0 or (frame_index + 1) % 25 == 0 or frame_index + 1 == max_frame_count:
                print(
                    f"[render] level {report['level_id']} frame {frame_index + 1}/{max_frame_count} -> {out_path.name}",
                    flush=True,
                )
    finally:
        process.stdin.close()
        return_code = process.wait()
        if return_code != 0:
            raise SystemExit(f"ffmpeg failed for {out_path} with exit code {return_code}")


def main():
    parser = argparse.ArgumentParser(description="Render 5x4 grid replay videos for benchmark trial sets.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Benchmark model to render.")
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, help="Reasoning effort to render.")
    parser.add_argument("--levels", type=int, nargs="+", default=DEFAULT_LEVELS, help="Levels to render.")
    parser.add_argument("--benchmark-root", type=Path, action="append", default=None, help="Benchmark root directory. Can be provided multiple times.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for MP4 videos.")
    parser.add_argument("--fps", type=int, default=FPS, help="Frames per second in the output video. One replay state becomes one video frame.")
    parser.add_argument("--max-states", type=int, default=None, help="Optional cap for smoke testing.")
    args = parser.parse_args()

    benchmark_roots = args.benchmark_root or DEFAULT_BENCHMARK_ROOTS
    pygame.display.init()
    pygame.font.init()

    try:
        for level_id in args.levels:
            report_path = discover_report(level_id, args.model, args.reasoning_effort, benchmark_roots)
            out_name = f"{args.model.replace('.', '_')}-{args.reasoning_effort}-level-{level_id}-grid.mp4"
            out_path = args.out_dir / out_name
            print(f"[report] {report_path}")
            print(f"[video] {out_path}")
            render_level_video(
                report_path=report_path,
                out_path=out_path,
                fps=args.fps,
                max_states=args.max_states,
            )
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
