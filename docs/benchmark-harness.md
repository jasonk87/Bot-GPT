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
- per-task answer output for manual review

## Why this matters

This gives a concrete scorecard for big-ticket improvements (reliability, verification, and quality) so releases can be compared objectively.
