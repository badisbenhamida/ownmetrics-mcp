# ownmetrics-mcp

Ask Claude, ChatGPT or any MCP-capable AI app about **your own Garmin data**: sleep, HRV,
stress, Body Battery, heart rate, activities and more. It uses Garmin's official
**Personal API**, runs on your own computer, and is read-only.

> **Unofficial project.** Not affiliated with, endorsed by or supported by Garmin.
> "Garmin" and "Garmin Connect" are trademarks of Garmin Ltd. or its subsidiaries.
> Results are informational, not medical advice.

**Status: v0.1 (preview).** The nine data tools below work today. Insight tools (weekly
training summary, period comparisons, trends, FIT analysis) are next.

## What you can ask

- "How did I sleep this week? Which night was worst, and why?"
- "Show my HRV for the last 30 days. Is it trending down?"
- "What were my stress and Body Battery like yesterday?"
- "List my runs this month with distance and average pace."
- "Break down my last long ride: power, heart rate, training effect."
- "How has my resting heart rate changed since September?"
- "Which month did I sleep best this year, and how much did I train that month?"
- "Compare my sleep and training this October with last October."
- "Do my evening tennis sessions go with worse sleep?"
- "Is my Garmin connection working?"

## Set up in about 10 minutes

You need a Garmin Connect account and an AI app that supports MCP servers (Claude Desktop,
Claude Code, ChatGPT desktop, Cursor and others).

### 1. Install uv (one time)

uv runs Python tools without any manual setup.

- **macOS / Linux:** open Terminal and run
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows:** open PowerShell and run
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

### 2. Create your Garmin Personal API key

1. Sign in to Garmin Connect on the web and open
   [Settings → Personal API](https://connect.garmin.com/app/settings/personalApiToken).
2. Select **Create Key**, read and accept Garmin's terms, and choose how long the key
   lasts (30 days to a year; your choice).
3. Copy the key. Garmin shows it only once.

### 3. Save the key

```bash
uvx --from git+https://github.com/badisbenhamida/ownmetrics-mcp ownmetrics-mcp auth
```

Paste the key when asked (it stays hidden). It is checked with Garmin, then saved to
`~/.config/garmin/connect-personal-api-key` in your home folder. On macOS and Linux the file
is readable only by you; on Windows it sits in your user profile folder, protected by your
Windows account.

### 4. Add it to your AI app

**Claude Desktop:** Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "ownmetrics": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/badisbenhamida/ownmetrics-mcp", "ownmetrics-mcp"]
    }
  }
}
```

Restart Claude Desktop.

**Claude Code:**

```bash
claude mcp add ownmetrics -- uvx --from git+https://github.com/badisbenhamida/ownmetrics-mcp ownmetrics-mcp
```

**Other apps:** use command `uvx` with the same arguments as above.

Then ask: *"Check my Garmin connection, then summarize my sleep and HRV for the last week."*

## Tools

| Tool | What it returns |
| --- | --- |
| `get_daily_overview` | One day: steps, distance, floors, heart rate, stress, Body Battery, calories, intensity minutes, sleep |
| `get_sleep` | Per night: hours, deep/light/REM/awake, score, Garmin's feedback, heart rate, respiration |
| `get_hrv` | Per night: HRV last-night and weekly average, 5-minute high, status, baseline |
| `get_stress_and_body_battery` | Per day: stress level, time in each stress band, Body Battery high/low/charged/drained |
| `get_heart_rate` | One day: resting, min, max, 7-day resting average; your heart rate zones |
| `list_activities` | Activities in a date range, optionally by type, with duration, distance, heart rate |
| `get_activity` | One activity: pace, speed, power, cadence, training effect and load, splits |
| `get_body_metrics` | Weigh-ins, BMI, body fat, hydration; Pulse Ox and fitness age |
| `get_account_status` | Whether your key works, a warning in its final day, which of the data areas above respond |

**Insight tools** do the fetching and the math in one call, over up to a year:

| Tool | What it answers |
| --- | --- |
| `training_summary` | Training by week or month: sessions, hours, hours per week, evening sessions, per-sport breakdown |
| `compare_periods` | Two periods side by side: sleep, HRV, resting heart rate, stress, Body Battery, steps, training, with change and % change |
| `recovery_correlations` | Whether training goes with better or worse sleep and HRV the night after, with sample size and strength. Correlation, not cause. |
| `trend` | One metric by day, week or month, with direction (up, down or flat) and change per 30 days |

Sleep and HRV are dated by the morning the night ended (`woke_up_on`), as Garmin does.
Pace is shown for running, walking and hiking; speed for other sports; distance says
"not applicable" for sports like strength training or pilates.

Every field name carries its unit (`resting_hr_bpm`, `distance_km`, `sleep_score_0_100`).
Where Garmin has no value, the field says **"not recorded"**, never zero.

## What Garmin's Personal API does not provide

- **Read-only:** nothing can be sent to your watch or written to Garmin Connect.
- **Not available:** training readiness, training status, acute/chronic load, VO2 max,
  gear and devices. The tools say "not provided by Garmin's Personal API" rather than guessing.
- Data tools cover up to **90 days** per question and insight tools up to **366 days**; the
  server splits requests to stay within Garmin's own limits.

## Privacy and security

- Runs on your computer. Talks only to Garmin. No database, no telemetry.
- Your AI app sends tool results to its AI model, under that provider's terms.
- Your key never appears in tool results, logs or errors.
- Delete the key in Garmin Connect at any time to cut off access instantly.

Details: [PRIVACY.md](PRIVACY.md) · [THREAT_MODEL.md](THREAT_MODEL.md) ·
Report vulnerabilities: [SECURITY.md](SECURITY.md)

Use of Garmin's API is subject to Garmin's terms: your key is personal to you and must not
be shared.

## Troubleshooting

- **"Garmin rejected your Personal API key":** it expired or was deleted. Create a new one
  and run step 3 again. Garmin emails a reminder about a week before a key expires.
- **The AI app doesn't see the tools:** restart the app fully. On macOS, if `uvx` isn't
  found, use its full path (run `which uvx` in Terminal) as the `command`.
- **Check the connection yourself:**
  `uvx --from git+https://github.com/badisbenhamida/ownmetrics-mcp ownmetrics-mcp status`

## How it's built

This project is built with spec-driven development. [SPEC.md](SPEC.md) holds numbered
requirements and the non-negotiable rules; every requirement traces to tests in
[TRACEABILITY.md](TRACEABILITY.md), which CI regenerates and checks on every change.
Contributions follow the same path: see [CONTRIBUTING.md](CONTRIBUTING.md).

Built on Garmin's official
[connect-personal-api-python](https://github.com/garmin/connect-personal-api-python) client
and the [Model Context Protocol](https://modelcontextprotocol.io) Python SDK.

## License

[MIT](LICENSE)
