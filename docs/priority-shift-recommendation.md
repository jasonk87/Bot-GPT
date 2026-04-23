# Priority Shift Recommendation: Depth Routing vs Bigger Wins

Short answer: **we should not keep investing heavily in depth routing right now**.

Depth routing is useful, but it is a multiplier on baseline quality. If baseline reliability or execution quality is uneven, routing improvements have diminishing returns.

## Recommendation

Adopt this split for the next milestone:

- **20%** effort: stabilize and lightly tune depth routing (keep what we built, avoid major expansion)
- **80%** effort: focus on high-impact platform wins that improve every response

## What to do instead (higher ROI)

### 1) Reliability hardening (top priority)

- Improve dependency resilience (graceful startup when optional packages are missing).
- Add robust error taxonomy and user-facing recovery messages.
- Ensure test environment reproducibility (pin and verify dev/test dependencies).

**Why:** Reliability failures are trust killers and block all higher-level UX improvements.

### 2) Execution quality loop

- Add post-answer verification pass for factual/code-risk checks.
- Add tool result validation before final response emission.
- Add clear "unable to verify" behavior when evidence is weak.

**Why:** Better correctness beats better style selection.

### 3) End-to-end benchmarks and scorecard

- Define 20–30 representative tasks (Q&A, coding edits, tool workflows).
- Track: first-answer acceptance, completion rate, retries, tool errors, time-to-useful-output.
- Gate releases on measurable improvement.

**Why:** Prevents feature drift and gives objective direction.

### 4) Memory and personalization quality

- Improve relevance filtering for recalled memory.
- Prevent stale memory injection.
- Add preference confidence and decay.

**Why:** Better context quality improves both standard and deep answers.

## Keep from current depth work (do not discard)

Retain:
- standard/deep modes,
- auto router with fallback,
- preference persistence,
- routing metrics.

But treat this as **stable infrastructure**, not the main roadmap thread.

## Decision rule (when to return to depth-routing work)

Only resume major routing investment if:

1. Core reliability metrics are healthy for 2 consecutive releases,
2. First-answer acceptance is still flat,
3. Benchmarks show routing is now the dominant bottleneck.

## 2-week practical plan

### Week 1
- Dependency and test-environment stabilization.
- Error taxonomy and recovery UX.
- Baseline benchmark harness.

### Week 2
- Verification pass + tool output validation.
- Scorecard dashboards and release gate.
- Minor depth-router tune only if benchmark data supports it.

## Bottom line

Depth routing was a good build. Now the highest-value move is to focus on reliability + correctness + benchmark-driven improvement.
