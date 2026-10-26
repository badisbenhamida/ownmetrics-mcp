# Changelog

## 0.1.0 — unreleased (Milestone 2)

- Data tools T1–T9: daily overview, sleep, HRV, stress and Body Battery, heart rate and
  zones, activity list and detail, body metrics, account status.
- `ownmetrics-mcp auth` verifies and stores your Personal API key; `ownmetrics-mcp status`
  checks the connection.
- Requests split to Garmin's per-endpoint range limits, throttled, with 429 backoff and one
  token refresh on 401.
- Governance: SPEC.md with numbered requirements, THREAT_MODEL.md, generated
  TRACEABILITY.md checked in CI.
