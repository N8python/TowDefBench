## Full Eval Summary

- status: `complete`
- backend: `codex`
- model: `gpt-5.6-sol`
- reasoning effort: `max`
- trials per level: `10`
- parallelism: `10`

Per-level scores are `mean (95% bootstrap CI)`.

| Level | Score | Wins | Benchmark Report |
| --- | --- | --- | --- |
| Level 1 | 1.000 (1.000, 1.000) | 10/10 | /Users/natebreslow/Documents/pvzEval/runs/full-evals-gpt56sol-max/td-full-eval-20260709-175442/benchmarks-gpt56sol-max/td-benchmark-20260709-175442/benchmark_report.json |
| Level 2 | 0.574 (0.310, 0.831) | 5/10 | /Users/natebreslow/Documents/pvzEval/runs/full-evals-gpt56sol-max/td-full-eval-20260709-175442/benchmarks-gpt56sol-max/td-benchmark-20260709-180422/benchmark_report.json |
| Level 3 | 1.000 (1.000, 1.000) | 10/10 | /Users/natebreslow/Documents/pvzEval/runs/full-evals-gpt56sol-max/td-full-eval-20260709-175442/benchmarks-gpt56sol-max/td-benchmark-20260709-182825/benchmark_report.json |
| Level 4 | 0.640 (0.406, 0.867) | 5/10 | /Users/natebreslow/Documents/pvzEval/runs/full-evals-gpt56sol-max/td-full-eval-20260709-211057-corrected/benchmarks-gpt56sol-max/td-benchmark-20260709-211057-corrected/benchmark_report.json |

Aggregate formula: `(s1 + 2*s2 + 3*s3 + 4*s4) / 10`

- aggregate score: `0.7709`
- 95% bootstrap CI: `(0.6639, 0.8766)`

## Capacity-error correction

Original Level 4 trials 4, 8, and 10 ended on model-capacity errors without terminal scores. The corrected metrics replace only those attempts with reruns using the same seeds at parallelism 3; original reports remain unchanged.

| Trial | Seed | Outcome | Score |
| --- | --- | --- | --- |
| 4 | 1436198080 | Win | 1.0000 |
| 8 | 537483461 | Loss | 0.3756 |
| 10 | 1511463369 | Win | 1.0000 |
