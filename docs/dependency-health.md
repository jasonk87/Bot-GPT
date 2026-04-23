# Dependency Health and Degraded Mode

The app now computes dependency health at startup and exposes two endpoints:

- `GET /health`
  - returns `status: ok|degraded`
  - returns `degraded_mode: true|false`
- `GET /health/dependencies`
  - returns required/optional module availability
  - returns missing module lists
  - returns recovery recommendations

## Why this matters

This gives operators immediate visibility into whether the runtime is degraded and what to do next.

## Recommended operator flow

1. Check `/health` for top-level status.
2. If degraded, check `/health/dependencies`.
3. Install missing required packages from `requirements.txt` first.
4. Install optional packages to restore non-critical features.
