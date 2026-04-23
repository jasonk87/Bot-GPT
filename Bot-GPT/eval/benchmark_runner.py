#!/usr/bin/env python3
"""Lightweight benchmark harness for Bot-GPT model quality checks.

Usage:
  python eval/benchmark_runner.py --model llama3 --tasks eval/tasks.sample.json
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import requests
from verification import verify_answer


def stream_chat(ollama_host: str, model: str, messages: list[dict], system_prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
    }
    response = requests.post(f"{ollama_host.rstrip('/')}/api/chat", json=payload, stream=True, timeout=600)
    response.raise_for_status()

    output = []
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
            output.append(chunk)
        if item.get("done"):
            break
    return "".join(output)


def score_task(answer: str, expected_keywords: list[str], task: dict | None = None) -> dict:
    lower = answer.lower()
    matched = [kw for kw in expected_keywords if kw.lower() in lower]
    keyword_recall = (len(matched) / len(expected_keywords)) if expected_keywords else 1.0
    has_next_step = "next step:" in lower
    verification = verify_answer(answer, task or {})
    return {
        "keyword_recall": keyword_recall,
        "has_next_step": has_next_step,
        "matched_keywords": matched,
        "response_chars": len(answer),
        "verification": verification,
    }


def run(tasks: list[dict], ollama_host: str, model: str, system_prompt: str) -> dict:
    results = []

    for task in tasks:
        prompt = task["prompt"]
        expected = task.get("expected_keywords", [])

        start = time.time()
        answer = stream_chat(ollama_host, model, [{"role": "user", "content": prompt}], system_prompt)
        duration = time.time() - start

        score = score_task(answer, expected, task)
        results.append({
            "id": task.get("id", prompt[:24]),
            "prompt": prompt,
            "duration_s": round(duration, 3),
            "answer": answer,
            **score,
        })

    durations = [r["duration_s"] for r in results]
    recalls = [r["keyword_recall"] for r in results]
    next_step_rate = sum(1 for r in results if r["has_next_step"]) / len(results) if results else 0.0
    verification_pass_rate = (
        sum(1 for r in results if r.get("verification", {}).get("passed")) / len(results)
        if results
        else 0.0
    )

    summary = {
        "total_tasks": len(results),
        "avg_duration_s": round(statistics.mean(durations), 3) if durations else 0.0,
        "p95_duration_s": round(sorted(durations)[max(0, int(len(durations) * 0.95) - 1)], 3) if durations else 0.0,
        "avg_keyword_recall": round(statistics.mean(recalls), 3) if recalls else 0.0,
        "next_step_rate": round(next_step_rate, 3),
        "verification_pass_rate": round(verification_pass_rate, 3),
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
    args = parser.parse_args()

    tasks_path = Path(args.tasks)
    tasks = json.loads(tasks_path.read_text())

    summary = run(tasks, args.ollama_host, args.model, args.system_prompt)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    payload = {
        "total_tasks": summary["total_tasks"],
        "avg_duration_s": summary["avg_duration_s"],
        "avg_keyword_recall": summary["avg_keyword_recall"],
        "next_step_rate": summary["next_step_rate"],
        "verification_pass_rate": summary["verification_pass_rate"],
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

    payload["gate_passed"] = not gate_failures
    payload["gate_failures"] = gate_failures
    print(json.dumps(payload, indent=2))
    if gate_failures:
        sys.exit(2)


if __name__ == "__main__":
    main()
