#!/usr/bin/env bash
set -euo pipefail

# CI-friendly wrapper for benchmark release gates.
# Expected env vars (with defaults):
#   BENCHMARK_MODEL (required)
#   OLLAMA_HOST (default: http://localhost:11434)
#   BENCHMARK_TASKS (default: Bot-GPT/eval/tasks.sample.json)
#   BENCHMARK_OUT (default: Bot-GPT/eval/benchmark_report.json)
#   MIN_VERIFICATION_PASS_RATE (default: 0.85)
#   MIN_NEXT_STEP_RATE (default: 0.95)
#   MIN_KEYWORD_RECALL (default: 0.70)

: "${BENCHMARK_MODEL:?BENCHMARK_MODEL is required}"

OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
BENCHMARK_TASKS="${BENCHMARK_TASKS:-Bot-GPT/eval/tasks.sample.json}"
BENCHMARK_OUT="${BENCHMARK_OUT:-Bot-GPT/eval/benchmark_report.json}"
MIN_VERIFICATION_PASS_RATE="${MIN_VERIFICATION_PASS_RATE:-0.85}"
MIN_NEXT_STEP_RATE="${MIN_NEXT_STEP_RATE:-0.95}"
MIN_KEYWORD_RECALL="${MIN_KEYWORD_RECALL:-0.70}"

python Bot-GPT/eval/benchmark_runner.py \
  --tasks "${BENCHMARK_TASKS}" \
  --model "${BENCHMARK_MODEL}" \
  --ollama-host "${OLLAMA_HOST}" \
  --out "${BENCHMARK_OUT}" \
  --min-verification-pass-rate "${MIN_VERIFICATION_PASS_RATE}" \
  --min-next-step-rate "${MIN_NEXT_STEP_RATE}" \
  --min-keyword-recall "${MIN_KEYWORD_RECALL}"
