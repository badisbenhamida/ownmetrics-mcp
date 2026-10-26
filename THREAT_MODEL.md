# Threat model

Scope: ownmetrics-mcp running locally as a stdio MCP server, launched by the user's AI app,
reading the user's own data through Garmin's Personal API. Requirement IDs refer to SPEC.md.

## Assets

- The user's Garmin Personal API key and the bearer tokens it produces.
- The user's health and activity data.

## Trust boundaries

1. User's AI app ⇄ this server (stdio, same machine).
2. This server ⇄ Garmin's Personal API (HTTPS, via Garmin's official client).
3. User's AI app ⇄ its LLM provider. Tool results go to whichever LLM the user configured;
   this project does not control that hop, and PRIVACY.md says so plainly.

## Threats and controls

| Threat | Control | Verified by |
| --- | --- | --- |
| Key leaks through config files, shell history, logs or error messages | Key lives in Garmin's standard key file (owner-only), or an env var; never a tool argument or CLI flag; registered secrets, `ApiKey`/`Bearer` headers and JWTs are scrubbed from every log line and error; Garmin's raw HTTP error bodies are never forwarded | C5, AC5, R7 (`test_secrets.py`, `test_cli.py`) |
| Key entered in the Claude Desktop bundle | The bundle's key setting is marked sensitive, so Claude Desktop masks it and stores it itself; it reaches the server only as an environment variable, gets the same redaction as any key, and a blank value never becomes an empty key | B2, C5, AC5 (`test_bundle.py`) |
| Prompt injection inside Garmin data (activity names, notes) tells the LLM to act | All data is returned as data; the server has no write, file or network tools an injected instruction could use | C1, R6 (`test_server.py`) |
| Health data retained on disk | No database, cache or files written; only Garmin's own token cache exists | C3 (`test_constitution.py`) |
| Data sent somewhere other than Garmin | The package makes no network calls of its own; Garmin's client is the only path | C2 (`test_constitution.py`) |
| LLM presents numbers as medical advice | Every tool description and result carries the not-medical-advice note | C7 (`test_server.py`) |
| LLM treats missing data as zero and draws wrong conclusions | Missing values are the text "not recorded"; unsupported areas say "not provided by Garmin's Personal API" | C4, AC3 (`test_missing_data.py`) |
| Excessive load on Garmin, or the user's key being throttled | Client-side throttling, request windows within Garmin's limits, backoff on 429 | R2, R3 (`test_garmin.py`) |
| Supply-chain compromise | Minimal dependencies (MCP SDK, Garmin's official client); Dependabot; gitleaks secret scanning in CI; trusted publishing for releases; the Claude Desktop bundle is built and validated in CI with the official `mcpb` tool, unsigned for now | CI configuration |
| Expired or revoked key leaves the user stuck | Clear fix-it message naming the exact steps | AC6 (`test_garmin.py`, `test_server.py`) |

## Out of scope

- A compromised user machine (malware can read any local file, including the key).
- What the user's chosen LLM provider does with data the user sends it.
