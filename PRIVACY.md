# Privacy

In plain words:

- **Your data stays between you, Garmin and the AI app you choose.** ownmetrics-mcp runs on
  your own computer. It asks Garmin for your data only when your AI app calls one of its
  tools, and passes the answer straight back to that app.
- **Your AI app then sends the answer to its AI model** (for example Claude or ChatGPT). That
  part is governed by your AI provider's privacy terms, not by this project.
- **Nothing is stored.** No database, no copies of your data, no analytics, no telemetry.
  The only file written is your key (when you run `ownmetrics-mcp auth`) and Garmin's own
  short-lived sign-in token, both in your home folder (readable only by you on macOS
  and Linux).
- **No password.** It uses a Personal API key you create in Garmin Connect. You can delete
  that key at any time, which immediately cuts off access.
- **Read-only.** It cannot change anything in your Garmin account.

The developers of this project never see your key or your data.
