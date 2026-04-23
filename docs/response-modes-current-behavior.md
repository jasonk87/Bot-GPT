# Response Modes: Current Behavior (As Implemented)

This is the current, code-accurate behavior for `standard` and `deep`.

## How mode is selected

Mode selection supports both manual preference and automatic routing:

- If preference is set to `standard` or `deep`, that explicit choice is used.
- If preference is `auto` (default), routing first tries a lightweight model-based classifier (mode + confidence) and falls back to keyword + complexity heuristics if confidence is low or parsing fails.

- `deep` if the message contains explicit deep signals like: `deep dive`, `in detail`, `detailed`, `step-by-step`, `thorough`, `comprehensive`, `think this out`, `pro mode`, etc.
- `deep` can also auto-trigger when complexity signals are present (for example: `tradeoff`, `options`, `architecture`, `strategy`, `design`, `roadmap`, `compare`, `implementation`) and the prompt is sufficiently substantive.
- `standard` otherwise.

There is no separate `quick` mode anymore.

## What each mode changes right now

The runtime difference between modes is the instruction appended to the system prompt:

- `standard`: asks for a direct, well-reasoned answer with concise rationale and minimal filler.
- `deep`: asks for thorough, structured breakdowns with tradeoffs/steps/examples.

Important: this is guidance-level behavior (prompting), not a hard length/token limiter.

## What is shared across both modes

All modes currently still apply:

- The required `Next step:` line at the end of final user-facing content.
- The emitted `response_mode` event for the frontend.
- The frontend badge text `Response mode: <Mode>` on the assistant bubble.

## Practical interpretation

Right now, think of the two modes as **style profiles** (lightweight steering), not strict output constraints.

## Telemetry

- Runtime counters are tracked in-memory by mode and routing source.
- Metrics can be queried via `GET /api/depth_metrics`.
