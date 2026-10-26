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
- Independent review fixes: fresh token for the key-expiry warning; "not connected" when
  data calls reject the key; HTTP 403 reported as a permission gap per data area (R8);
  unknown activity ids say "not found"; thread-safe token handling and throttling (R9);
  deterministic duplicates, de-duplicated newest-first activities (R10); strict
  `YYYY-MM-DD` dates; 0 h sleep and empty lists never shown as data; key file owner-only
  from the first byte; warning when an environment variable overrides the saved key.
