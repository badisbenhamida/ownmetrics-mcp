# Changelog

## 0.3.0 — unreleased (Milestone 6)

- New insight tool `weekly_review` (I5): the same review every time. This week so far
  against the same days last week and the previous 28 days: training by sport, sleep, HRV,
  resting heart rate, stress and Body Battery; best and worst nights; highlights from fixed
  rules (HRV ±10%, sleep score ±5 points, resting heart rate ±3 bpm, training ±30%, 2 or
  more nights without data).
- FIT-file analysis is now I6, planned for a later release.

## 0.2.1 — unreleased (Milestone 5)

- One-click install for Claude Desktop: each release now includes
  `ownmetrics-mcp-<version>.mcpb`. Double-click it and paste your key (B1–B5).
- A blank `GARMIN_PERSONAL_API_KEY` now counts as not set, so the key saved by
  `ownmetrics-mcp auth` is used instead of failing on an empty key.

## 0.2.0 — unreleased (Milestone 3)

- Install from PyPI: `uvx ownmetrics-mcp` (README updated). Releases publish to PyPI and the
  MCP Registry from GitHub Actions, with no stored tokens.
- Insight tools: `training_summary` (I1, by week or month), `compare_periods` (I2),
  `recovery_correlations` (I3), `trend` (I4). Ranges up to 366 days (R12).
- `recovery_correlations` can focus on one sport (e.g. `tennis`); days with only other
  training are left out. Clearer labels: `next_sleep_hours`, "lower HRV".
- Sleep and HRV nights are labelled `woke_up_on` instead of `night_of`, because Garmin dates
  a night by the morning it ends. **Breaking** for anyone reading the old field name.
- Activity figures fit the sport (R11): pace for running, walking and hiking; speed for other
  moving sports; neither for racket sports; distance "not applicable" for strength, pilates
  and similar instead of 0.
- Tests: a deterministic throttle test (the old one could fail on slow Windows runners);
  the no-cache rule checks imports, not words; every known limitation has a test (AC9).

## 0.1.0 — unreleased (Milestone 2)

- Data tools T1–T9: daily overview, sleep, HRV, stress and Body Battery, heart rate and
  zones, activity list and detail, body metrics, account status.
- `ownmetrics-mcp auth` verifies and stores your Personal API key; `ownmetrics-mcp status`
  checks the connection.
- Requests split to Garmin's per-endpoint range limits, throttled, with 429 backoff and one
  token refresh on 401.
- Governance: SPEC.md with numbered requirements, THREAT_MODEL.md, generated
  TRACEABILITY.md checked in CI.
- Independent review fixes: fresh token for the key-expiry warning; "not connected" when
  data calls reject the key; HTTP 403 reported as a permission gap per data area (R8);
  unknown activity ids say "not found"; thread-safe token handling and throttling (R9);
  deterministic duplicates, de-duplicated newest-first activities (R10); strict
  `YYYY-MM-DD` dates; 0 h sleep and empty lists never shown as data; key file owner-only
  from the first byte; warning when an environment variable overrides the saved key.
