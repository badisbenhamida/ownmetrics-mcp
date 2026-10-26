# ownmetrics-mcp — Specification

Status: v0.2.0 released (Milestone 3 closed Oct 26, 2026). Owner: Badis Ben Hamida.
This file is the source of truth. Code and tests trace back to the requirement IDs below;
`scripts/traceability.py` checks the link in CI and writes `TRACEABILITY.md`.

## 1. Purpose

A local, read-only MCP server that lets Claude and other AI apps answer questions about the
user's **own** Garmin data, using Garmin's official Personal API. Unofficial: not affiliated
with or endorsed by Garmin.

**Goals (v1)**

1. A non-developer Garmin owner is set up in under 10 minutes.
2. Works in any MCP client (Claude Desktop, Claude Code, ChatGPT desktop, Cursor and similar).
3. Every tool has a requirement, a test and a documented example prompt.

**Non-goals (v1):** no hosted version (it runs on the user's machine); no writing to Garmin
(the Personal API is read-only); no medical advice; no Garmin branding or logo.

## 2. Constitution (non-negotiable rules)

| ID | Rule | Milestone | Verify |
| --- | --- | --- | --- |
| C1 | Read-only. No tool writes to Garmin or to the user's files. | M2 | auto |
| C2 | Local-only. The server talks to Garmin's Personal API and nothing else. No telemetry. | M2 | auto |
| C3 | No stored health data. No database or cache of Garmin data; only Garmin's own token cache. | M2 | auto |
| C4 | Missing is never zero. Absent data is reported as "not recorded" or "not provided by Garmin". | M2 | auto |
| C5 | The Personal API key never appears in tool input, output, logs or errors. | M2 | auto |
| C6 | Garmin's name appears only descriptively, with the trademark disclaimer; no logo. | M2 | manual |
| C7 | Results are informational, not medical advice, and every tool description says so. | M2 | auto |

## 3. Garmin Personal API facts this design relies on (verified Oct 2026)

- Key created by the user in Garmin Connect web settings; lifetime 30/90/180/365 days, chosen by the user.
- Key exchanged for a bearer token valid 24 h, or until the key expires; no refresh tokens.
- The token does not expose the key's expiry date; it is detectable only in the key's final 24 h.
- 26 GET-only endpoints. Everything else (training readiness, training status, VO2 max,
  workouts, devices, gear) returns 404.
- Per-request range limits: 31 days for daily summaries, sleep, hydration and Body Battery;
  28 days for stress and steps; 365 days for HRV; about a year for weight; about 45 activities per page.
- History reaches back to at least 2010 (activities, daily summaries).
- With a personal key, activity FIT files are the complete original files.

## 4. Requirements

`Verify`: **auto** = covered by automated tests; **manual** = checked by a person at the gate.

### 4.1 Data tools (Milestone 2)

| ID | Tool | Requirement | Milestone | Verify |
| --- | --- | --- | --- | --- |
| T1 | `get_daily_overview` | One day: steps, distance, resting/min/max HR, stress, Body Battery, calories, intensity minutes, sleep score. | M2 | auto |
| T2 | `get_sleep` | Per night in a range: duration, stages, score, Garmin's feedback, avg HR/respiration/stress. Each night is labelled `woke_up_on`, because Garmin dates a night by the morning it ends. | M2 | auto |
| T3 | `get_hrv` | Per night in a range: last-night average, weekly average, 5-min high, status, baseline. Each night is labelled `woke_up_on`, as in T2. | M2 | auto |
| T4 | `get_stress_and_body_battery` | Per day in a range: stress level and time per stress band; Body Battery high/low/charged/drained. | M2 | auto |
| T5 | `get_heart_rate` | One day: resting, min, max, 7-day resting average; the user's HR zones. | M2 | auto |
| T6 | `list_activities` | Activities in a range, optional type filter, up to 100: id, name, type, start, duration, distance, avg HR, calories, training effect. | M2 | auto |
| T7 | `get_activity` | One activity: summary, pace/speed, power, cadence, training effect and load, splits, structured workout names and step counts. An unknown id says "no activity with that id", not "not provided". | M2 | auto |
| T8 | `get_body_metrics` | Range: weight entries (kg), BMI, body fat, hydration; SpO2 and fitness age as of the end date. | M2 | auto |
| T9 | `get_account_status` | Connected or not (false whenever Garmin rejects the key, at sign-in or on data calls), granted scopes, a final-day key warning (read from a freshly issued token's lifetime, since Garmin does not expose the key's expiry), whether each data area used by T1–T8 responds, and what Garmin does not provide. Also available as the `ownmetrics-mcp status` command, which exits non-zero when not connected. | M2 | auto |

### 4.2 Insight tools (Milestone 3)

Insight tools do the fetching and the arithmetic inside the server, so one call answers a
question that would otherwise take many data-tool calls plus manual math. They accept ranges
of up to 366 days (R12). Every average reports how many days or nights it is based on.

Metrics shared by I2 and I4: `sleep_score`, `sleep_hours`, `deep_sleep_minutes`,
`hrv_ms` (last-night average), `resting_hr_bpm`, `stress_avg`, `body_battery_high`,
`steps`, `training_hours`, `training_sessions`.

| ID | Tool | Requirement | Milestone | Verify |
| --- | --- | --- | --- | --- |
| I1 | `training_summary` | Training totals for a range, grouped by `week` (Monday start) or `month`: sessions, hours, hours per week, evening sessions (starting 18:00 or later, local time), average aerobic training effect, and a per-sport breakdown (sessions, hours, distance where the sport has one). Periods cut by the range are marked partial with their day count. | M3 | auto |
| I2 | `compare_periods` | Two date ranges side by side for the shared metrics (all, or a chosen subset): average for each period, change and % change, and the number of days with data on each side. A metric with no data on one side is "not recorded", never zero. | M3 | auto |
| I3 | `recovery_correlations` | Night-by-night link between each day's training (hours, summed aerobic training effect, evening session yes/no) and what follows: that night's sleep score and hours (the record whose `woke_up_on` is the next day) and the next morning's HRV. Reports the correlation (Pearson r), sample size and a plain strength label (none < 0.1, weak < 0.3, moderate < 0.5, strong), plus averages for training days vs rest days and evening vs earlier sessions. Needs at least 14 paired days, otherwise says "not enough data". Always states that correlation does not show cause. Optional sport filter (a Garmin activity type, matched by name, e.g. `tennis` matches `tennis_v2`): only that sport counts as training, its days are compared with rest days, and days with only other training are left out and counted. | M3 | auto |
| I4 | `trend` | One shared metric over a range, grouped by `day`, `week` or `month`: the series (with a 7-day rolling average for daily grouping), the change per 30 days from a least-squares fit, and a direction of up, down or flat (flat when the fitted change over the whole range is under 2% of the average). | M3 | auto |
| I5 | `analyze_fit_file` | From the complete FIT file by activity ID: laps, HR zones over time, splits, training effect, running dynamics (documented fields only). Deferred to a later release; needs a FIT-reading dependency. | v0.3 | auto |

### 4.3 Cross-cutting rules

| ID | Requirement | Milestone | Verify |
| --- | --- | --- | --- |
| R1 | Dates are exactly `YYYY-MM-DD`; ranges are inclusive, end ≥ start, at most 90 days per data-tool call (insight tools: R12). | M2 | auto |
| R2 | Requests are split into windows within Garmin's per-endpoint range limits (section 3). | M2 | auto |
| R3 | Requests are throttled; HTTP 429 gets backoff, then a clear "Garmin is limiting requests" error. | M2 | auto |
| R4 | A 401 on a data call triggers one token refresh and retry before failing. | M2 | auto |
| R5 | Every field name carries its unit (e.g. `resting_hr_bpm`, `distance_km`). | M2 | auto |
| R6 | Every tool is annotated read-only and its description carries the not-medical-advice note. | M2 | auto |
| R7 | `ownmetrics-mcp auth` stores the key in Garmin's standard key file, after verifying it with Garmin; on macOS and Linux the file is owner-only from the first byte written. It warns when the `GARMIN_PERSONAL_API_KEY` environment variable would override the saved file. | M2 | auto |
| R8 | A 403 on a data call means the key lacks permission for that data area: it is reported as "not allowed by your key's permissions" for that area, and the tool's other data is still returned. Only a sign-in rejection or a repeated 401 means the key is expired or deleted. | M2 | auto |
| R9 | Tool calls may run concurrently; token handling and throttling are thread-safe. | M2 | auto |
| R10 | Duplicate records for one day are resolved deterministically (the most complete record wins); activities are de-duplicated by id and listed newest first. | M2 | auto |
| R11 | Activity figures fit the sport: pace (`pace_min_per_km`) only for running, walking and hiking types, speed (`avg_speed_kmh`) for other moving sports, neither for racket sports (tennis, pickleball and similar), which still report distance; sports without distance (e.g. strength, pilates, breathwork) report distance as "not applicable", never 0. | M3 | auto |
| R12 | Insight tools accept ranges of up to 366 days, fetched within Garmin's per-endpoint limits (R2). | M3 | auto |

### 4.4 Acceptance criteria

| ID | Criterion | Milestone | Verify |
| --- | --- | --- | --- |
| AC1 | A new user goes from zero to first answer in under 10 minutes. | M3 | manual |
| AC2 | Every in-scope requirement maps to at least one test (generated traceability check). | M2 | auto |
| AC3 | Missing or unsupported data never appears as zero or blank. | M2 | auto |
| AC4 | Insight math is correct on hand-calculated fixtures. | M3 | auto |
| AC5 | The API key never appears in output, logs or errors (canary-key test). | M2 | auto |
| AC6 | An expired or revoked key gives a clear fix-it message. | M2 | auto |
| AC7 | FIT analysis reads only the requested activity's file, never local paths. | v0.3 | auto |
| AC8 | Works in at least three MCP clients. | M3 | manual |
| AC9 | Every known limitation has a test proving the documented behavior. | M3 | auto |

## 5. Known limitations (from the Personal API)

| ID | Limitation | Behavior |
| --- | --- | --- |
| L1 | Read-only, pull-only. | No write tools exist. |
| L2 | No training readiness, training status, acute/chronic load, VO2 max (404). | Reported as "not provided by Garmin's Personal API". |
| L3 | No gear, devices or workouts endpoints. | Out of scope. |
| L4 | No Golf, Courses or Training APIs (business tiers only). | Out of scope. |
| L5 | Rate limits are unpublished. | R3. |
| L6 | Key expiry date not exposed. | T9 warns once a freshly issued token is shorter than 23 h (the key ends within about a day); Garmin also emails a reminder about a week before expiry. |
| L7 | Some endpoints fail with HTTP 500 beyond their range limits. | R2. |

## 6. Milestones and gates

| Milestone | Scope | Gate |
| --- | --- | --- |
| M0 | Spec | Approved by Badis (Oct 25, 2026). |
| M1 | API verification | Limitations verified with live checks (Oct 25, 2026). |
| M2 | Auth, data tools T1–T9, CI, governance docs | AC2, AC3, AC5, AC6 pass; Badis reviews the repo. Passed Oct 25, 2026. |
| M3 | Fixes from real use (T2 `woke_up_on`, R11), insight tools I1–I4, docs set, release (PyPI, MCP Registry) | All M3 acceptance criteria pass; Badis tests on his own data. **Closed Oct 26, 2026 by Badis, with a waiver:** automated criteria pass; tested on Badis's data (insight results matched a hand calculation exactly); v0.2.0 on PyPI and the MCP Registry. AC8 partly verified (Claude Desktop, Claude Code; a third client not yet tested). AC1 and a re-check of Garmin's current Terms of Use waived, to revisit if users report setup problems. |
| v0.2.1 | One-click Claude Desktop bundle (.mcpb), moved out of M3 | Spec reviewed and approved before work starts. |
| v0.3 | FIT-file analysis (I5, AC7) | Spec reviewed again before work starts. |
| M4 | Launch content | Badis approves each piece before publication. Substack article and LinkedIn post published Oct 2026; Facebook post drafted, not yet posted. |
