# Benchmark Harness

Use `eval/benchmark_runner.py` to run repeatable, task-based checks against the local Ollama chat API.

## Quick start

```bash
python Bot-GPT/eval/benchmark_runner.py \
  --tasks Bot-GPT/eval/tasks.sample.json \
  --model llama3 \
  --ollama-host http://localhost:11434 \
  --out Bot-GPT/eval/benchmark_report.json
```

## What it reports

- average and p95 latency
- keyword recall against expected task keywords
- `Next step:` compliance rate
- verification pass-rate
- per-task answer output for manual review

## Why this matters

This gives a concrete scorecard for big-ticket improvements (reliability, verification, and quality) so releases can be compared objectively.

## What the verification loop accomplishes

A verification loop means we don't stop at \"the model produced an answer.\" We add a second pass that checks whether the answer is:

- supported by evidence/tool outputs,
- internally consistent,
- and actionable without obvious risk.

In benchmarking, this accomplishes four things:

1. **Separates style from correctness**
   A response can sound good but still be wrong. Verification loop metrics catch this.

2. **Improves trust in first answers**
   By validating claims before final output, we reduce avoidable follow-up corrections.

3. **Makes regressions visible early**
   If a model update hurts factual stability, verification failure rates increase immediately in benchmark runs.

4. **Creates a release gate tied to quality**
   We can require minimum thresholds (for example: verification pass-rate, keyword recall, and `Next step:` compliance) before shipping.

In short: benchmarking tells us *how often* we answer; verification tells us *how often we are right and safe to act on*.

## Task schema (verification fields)

Each task can include optional verification rules:

- `min_keyword_recall` (float, default `0.5` when keywords provided)
- `require_next_step` (bool, default `true`)
- `forbidden_patterns` (list of substrings that must not appear)

## Release-gate mode

You can make benchmark runs fail (non-zero exit) when quality drops below thresholds:

```bash
python Bot-GPT/eval/benchmark_runner.py \
  --tasks Bot-GPT/eval/tasks.sample.json \
  --model llama3 \
  --min-verification-pass-rate 0.85 \
  --min-next-step-rate 0.95 \
  --min-keyword-recall 0.70
```

If any threshold is missed, the runner exits with code `2` and prints `gate_failures`.

## CI integration helper

Use `Bot-GPT/eval/ci_benchmark_gate.sh` in CI pipelines.

Required env var:
- `BENCHMARK_MODEL`

Optional env vars:
- `OLLAMA_HOST` (default `http://localhost:11434`)
- `BENCHMARK_TASKS` (default `Bot-GPT/eval/tasks.sample.json`)
- `BENCHMARK_OUT` (default `Bot-GPT/eval/benchmark_report.json`)
- `MIN_VERIFICATION_PASS_RATE` (default `0.85`)
- `MIN_NEXT_STEP_RATE` (default `0.95`)
- `MIN_KEYWORD_RECALL` (default `0.70`)

## GitHub Actions

A starter workflow is included at `.github/workflows/benchmark-gate.yml`.

- It runs on pull requests and manual dispatch.
- It executes the benchmark gate only when `BENCHMARK_MODEL` secret is configured.
- Optionally set `OLLAMA_HOST` secret for non-default Ollama endpoint.
