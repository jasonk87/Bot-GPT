# Agent Mode + Canvas Roadmap (Phone + Desktop First)

This roadmap intentionally shifts away from small tuning loops and focuses on the biggest product wins:

1. visible streaming thought/progress,
2. stronger agent execution loop,
3. runnable/testable canvas outputs from any device.

## Product outcomes we want

- Users can **see what the agent is doing in real time**.
- Agent mode can **plan, execute, verify, and recover** without stalling.
- Canvas artifacts are **not just text**: they can be run/tested and results are visible.
- The same workflow works on **phone and desktop**.

## Stream A — Streaming thoughts/progress (highest UX impact)

### Goal
Make long-running work feel alive and trustworthy.

### Build
- Standardize streamed stages: `planning`, `executing`, `verifying`, `finalizing`.
- Emit structured progress events with timestamps and step labels.
- Add expandable timeline in UI (collapsed by default on mobile).
- Add "last completed step" and "currently running" indicators.

### Done when
- Users can always answer: "What is it doing right now?"

## Stream B — Better Agent Mode core loop

### Goal
Increase task completion and reduce dead-end runs.

### Build
- Introduce explicit loop phases per turn:
  1) Plan
  2) Act (tool calls)
  3) Verify (checks/tests)
  4) Decide next action
- Add retry policy for transient tool failures.
- Add fail-safe stop conditions with useful recovery prompts.
- Persist intermediate state so runs survive reconnects.

### Done when
- Agent can recover from common tool failures without user intervention.

## Stream C — Canvas as executable workspace

### Goal
Allow users to run and test what agent built directly in product.

### Build
- Add per-canvas run/test actions (language-aware command presets).
- Stream command output logs into canvas panel.
- Keep execution history (command, exit code, duration, output).
- Provide "share run output" action for collaboration/debug.

### Done when
- User can build + run + test without leaving app.

## Stream D — Phone + desktop parity

### Goal
Ensure full workflow works on mobile and desktop.

### Build
- Mobile-first layout for plan/progress/canvas panels.
- Sticky action bar on phone for Run/Test/Approve/Stop.
- Reconnect-safe live streams over unstable networks.

### Done when
- A full agent + canvas cycle is usable from phone.

## 2-Week execution plan

### Week 1
- Implement Stream A events + timeline UI.
- Refactor agent loop into Plan/Act/Verify/Decide phases.

### Week 2
- Ship canvas Run/Test with streaming logs.
- Add mobile action bar and reconnect resilience.

## Metrics to track

- Agent completion rate
- Time-to-first-visible-progress
- Run/test success rate in canvas
- Mobile session completion rate
- User follow-up: "what are you doing?" frequency

## Explicit deprioritization

Until these streams are delivered, avoid deep investment in:
- further depth-mode tuning,
- additional small preference toggles,
- low-impact UI polish not tied to run/test/progress visibility.
