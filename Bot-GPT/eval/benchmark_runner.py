#!/usr/bin/env python3
"""Lightweight benchmark harness for Bot-GPT model quality checks.

Usage:
  python eval/benchmark_runner.py --model llama3 --tasks eval/tasks.sample.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import requests
from verification import verify_answer

FAIL_SAFE_MARKERS = (
    "maximum iterations",
    "agent run stopped",
    "unable to verify",
    "couldn't generate a usable model response",
)

TOOL_ERROR_MARKERS = (
    "tool error",
    "[runtime_mismatch]",
    "[chat_runtime_error]",
    "failed:",
)

TOOL_CALL_MARKERS = (
    '"tool"',
    "run_shell_command",
    "execute_python",
    "write_file",
    "create_and_open_canvas",
)


def _is_useful_chunk(chunk: str) -> bool:
    text = (chunk or "").strip()
    if not text:
        return False
    alnum_count = sum(1 for ch in text if ch.isalnum())
    return alnum_count >= 6


def stream_chat(ollama_host: str, model: str, messages: list[dict], system_prompt: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
    }
    started = time.time()
    response = requests.post(f"{ollama_host.rstrip('/')}/api/chat", json=payload, stream=True, timeout=600)
    response.raise_for_status()

    output_chunks = []
    first_token_s = None
    first_useful_output_s = None

    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue

        chunk = (item.get("message") or {}).get("content")
        if chunk:
            output_chunks.append(chunk)
            if first_token_s is None:
                first_token_s = time.time() - started
            if first_useful_output_s is None and _is_useful_chunk(chunk):
                first_useful_output_s = time.time() - started
        if item.get("done"):
            break

    if first_useful_output_s is None:
        first_useful_output_s = first_token_s

    return {
        "answer": "".join(output_chunks),
        "time_to_first_token_s": round(first_token_s or 0.0, 3),
        "time_to_first_useful_output_s": round(first_useful_output_s or 0.0, 3),
    }


def _estimate_tool_usage(answer: str) -> tuple[int, int]:
    lower = answer.lower()
    tool_error_count = sum(lower.count(marker) for marker in TOOL_ERROR_MARKERS)
    tool_call_count = sum(lower.count(marker) for marker in TOOL_CALL_MARKERS)

    if tool_error_count > tool_call_count:
        tool_call_count = tool_error_count
    return tool_call_count, tool_error_count


def score_task(answer: str, expected_keywords: list[str], task: dict | None = None) -> dict:
    lower = answer.lower()
    matched = [kw for kw in expected_keywords if kw.lower() in lower]
    keyword_recall = (len(matched) / len(expected_keywords)) if expected_keywords else 1.0
    has_next_step = "next step:" in lower
    verification = verify_answer(answer, task or {})
    tool_call_count, tool_error_count = _estimate_tool_usage(answer)
    completion = bool(answer.strip()) and not any(marker in lower for marker in FAIL_SAFE_MARKERS)

    return {
        "keyword_recall": keyword_recall,
        "has_next_step": has_next_step,
        "matched_keywords": matched,
        "response_chars": len(answer),
        "verification": verification,
        "tool_call_count": tool_call_count,
        "tool_error_count": tool_error_count,
        "completion": completion,
    }


def _print_scorecard(summary: dict) -> None:
    lines = [
        "\n=== Benchmark Scorecard ===",
        f"Tasks run                  : {summary['total_tasks']}",
        f"Average duration (s)       : {summary['avg_duration_s']}",
        f"P95 duration (s)           : {summary['p95_duration_s']}",
        f"Avg first token (s)        : {summary['avg_time_to_first_token_s']}",
        f"Avg first useful output (s): {summary['avg_time_to_first_useful_output_s']}",
        f"Average keyword recall     : {summary['avg_keyword_recall']}",
        f"Next-step rate             : {summary['next_step_rate']}",
        f"Verification pass rate     : {summary['verification_pass_rate']}",
        f"Completion rate            : {summary['completion_rate']}",
        f"Tool error rate            : {summary['tool_error_rate']}",
        "",
        "By category:",
    ]

    for category, metrics in sorted(summary.get("by_category", {}).items()):
        lines.append(
            "  - "
            f"{category}: tasks={metrics['tasks']}, "
            f"verification_pass_rate={metrics['verification_pass_rate']}, "
            f"completion_rate={metrics['completion_rate']}, "
            f"tool_error_rate={metrics['tool_error_rate']}"
        )

    print("\n".join(lines))


def run(tasks: list[dict], ollama_host: str, model: str, system_prompt: str) -> dict:
    results = []

    for task in tasks:
        prompt = task["prompt"]
        expected = task.get("expected_keywords", [])

        start = time.time()
        chat_out = stream_chat(ollama_host, model, [{"role": "user", "content": prompt}], system_prompt)
        duration = time.time() - start
        answer = chat_out["answer"]

        score = score_task(answer, expected, task)
        results.append({
            "id": task.get("id", prompt[:24]),
            "category": task.get("category", "Uncategorized"),
            "prompt": prompt,
            "duration_s": round(duration, 3),
            "time_to_first_token_s": chat_out["time_to_first_token_s"],
            "time_to_first_useful_output_s": chat_out["time_to_first_useful_output_s"],
            "answer": answer,
            **score,
        })

    durations = [r["duration_s"] for r in results]
    recalls = [r["keyword_recall"] for r in results]
    first_token = [r["time_to_first_token_s"] for r in results]
    first_useful = [r["time_to_first_useful_output_s"] for r in results]
    next_step_rate = sum(1 for r in results if r["has_next_step"]) / len(results) if results else 0.0
    verification_pass_rate = (
        sum(1 for r in results if r.get("verification", {}).get("passed")) / len(results)
        if results
        else 0.0
    )
    completion_rate = sum(1 for r in results if r.get("completion")) / len(results) if results else 0.0

    total_tool_calls = sum(r.get("tool_call_count", 0) for r in results)
    total_tool_errors = sum(r.get("tool_error_count", 0) for r in results)
    tool_error_rate = (total_tool_errors / total_tool_calls) if total_tool_calls else 0.0

    by_category: dict[str, dict] = {}
    for row in results:
        category = row.get("category", "Uncategorized")
        bucket = by_category.setdefault(
            category,
            {
                "tasks": 0,
                "verification_passed": 0,
                "completion_count": 0,
                "tool_calls": 0,
                "tool_errors": 0,
            },
        )
        bucket["tasks"] += 1
        bucket["verification_passed"] += 1 if row.get("verification", {}).get("passed") else 0
        bucket["completion_count"] += 1 if row.get("completion") else 0
        bucket["tool_calls"] += row.get("tool_call_count", 0)
        bucket["tool_errors"] += row.get("tool_error_count", 0)

    for category, bucket in by_category.items():
        tasks_count = bucket["tasks"] or 1
        bucket["verification_pass_rate"] = round(bucket["verification_passed"] / tasks_count, 3)
        bucket["completion_rate"] = round(bucket["completion_count"] / tasks_count, 3)
        bucket["tool_error_rate"] = round(
            (bucket["tool_errors"] / bucket["tool_calls"]) if bucket["tool_calls"] else 0.0,
            3,
        )
        bucket.pop("verification_passed", None)
        bucket.pop("completion_count", None)

    summary = {
        "total_tasks": len(results),
        "avg_duration_s": round(statistics.mean(durations), 3) if durations else 0.0,
        "p95_duration_s": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 3) if durations else 0.0,
        "avg_time_to_first_token_s": round(statistics.mean(first_token), 3) if first_token else 0.0,
        "avg_time_to_first_useful_output_s": round(statistics.mean(first_useful), 3) if first_useful else 0.0,
        "avg_keyword_recall": round(statistics.mean(recalls), 3) if recalls else 0.0,
        "next_step_rate": round(next_step_rate, 3),
        "verification_pass_rate": round(verification_pass_rate, 3),
        "completion_rate": round(completion_rate, 3),
        "tool_error_rate": round(tool_error_rate, 3),
        "tool_call_count": total_tool_calls,
        "tool_error_count": total_tool_errors,
        "by_category": by_category,
        "results": results,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simple benchmark harness against local Ollama chat API.")
    parser.add_argument("--tasks", required=True, help="Path to tasks JSON file")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--ollama-host", default="http://localhost:11434", help="Ollama host URL")
    parser.add_argument("--system-prompt", default="You are a helpful assistant.", help="System prompt")
    parser.add_argument("--out", default="eval/benchmark_report.json", help="Output report path")
    parser.add_argument("--min-verification-pass-rate", type=float, default=None, help="Fail if verification_pass_rate is below this value")
    parser.add_argument("--min-next-step-rate", type=float, default=None, help="Fail if next_step_rate is below this value")
    parser.add_argument("--min-keyword-recall", type=float, default=None, help="Fail if avg_keyword_recall is below this value")
    parser.add_argument("--min-completion-rate", type=float, default=None, help="Fail if completion_rate is below this value")
    parser.add_argument("--max-tool-error-rate", type=float, default=None, help="Fail if tool_error_rate is above this value")
    parser.add_argument("--max-time-to-first-useful-output", type=float, default=None, help="Fail if avg_time_to_first_useful_output_s is above this value")
    args = parser.parse_args()

    tasks_path = Path(args.tasks)
    tasks = json.loads(tasks_path.read_text())

    summary = run(tasks, args.ollama_host, args.model, args.system_prompt)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    _print_scorecard(summary)

    payload = {
        "total_tasks": summary["total_tasks"],
        "avg_duration_s": summary["avg_duration_s"],
        "avg_time_to_first_useful_output_s": summary["avg_time_to_first_useful_output_s"],
        "avg_keyword_recall": summary["avg_keyword_recall"],
        "next_step_rate": summary["next_step_rate"],
        "verification_pass_rate": summary["verification_pass_rate"],
        "completion_rate": summary["completion_rate"],
        "tool_error_rate": summary["tool_error_rate"],
        "report": str(out_path),
    }

    gate_failures = []
    if args.min_verification_pass_rate is not None and summary["verification_pass_rate"] < args.min_verification_pass_rate:
        gate_failures.append(
            f"verification_pass_rate {summary['verification_pass_rate']} < {args.min_verification_pass_rate}"
        )
    if args.min_next_step_rate is not None and summary["next_step_rate"] < args.min_next_step_rate:
        gate_failures.append(
            f"next_step_rate {summary['next_step_rate']} < {args.min_next_step_rate}"
        )
    if args.min_keyword_recall is not None and summary["avg_keyword_recall"] < args.min_keyword_recall:
        gate_failures.append(
            f"avg_keyword_recall {summary['avg_keyword_recall']} < {args.min_keyword_recall}"
        )
    if args.min_completion_rate is not None and summary["completion_rate"] < args.min_completion_rate:
        gate_failures.append(
            f"completion_rate {summary['completion_rate']} < {args.min_completion_rate}"
        )
    if args.max_tool_error_rate is not None and summary["tool_error_rate"] > args.max_tool_error_rate:
        gate_failures.append(
            f"tool_error_rate {summary['tool_error_rate']} > {args.max_tool_error_rate}"
        )
    if (
        args.max_time_to_first_useful_output is not None
        and summary["avg_time_to_first_useful_output_s"] > args.max_time_to_first_useful_output
    ):
        gate_failures.append(
            "avg_time_to_first_useful_output_s "
            f"{summary['avg_time_to_first_useful_output_s']} > {args.max_time_to_first_useful_output}"
        )

    payload["gate_passed"] = not gate_failures
    payload["gate_failures"] = gate_failures
    print(json.dumps(payload, indent=2))
    if gate_failures:
        sys.exit(2)


if __name__ == "__main__":
    main()
