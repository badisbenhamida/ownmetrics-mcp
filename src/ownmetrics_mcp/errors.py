"""User-facing errors. Every message is safe to show: no keys, tokens or raw responses (C5)."""

from __future__ import annotations

KEY_PAGE = "https://connect.garmin.com/app/settings/personalApiToken"


class OwnMetricsError(Exception):
    """Base class. `str(err)` is a complete, user-facing explanation."""


class NoKeyError(OwnMetricsError):
    def __init__(self) -> None:
        super().__init__(
            "No Garmin Personal API key is set up. Create one in Garmin Connect "
            f"({KEY_PAGE}), then run `ownmetrics-mcp auth` and restart your AI app."
        )


class AuthError(OwnMetricsError):
    """Key rejected (expired, deleted or mistyped). AC6."""

    def __init__(self) -> None:
        super().__init__(
            "Garmin rejected your Personal API key. It has probably expired or been deleted. "
            f"Create a new key in Garmin Connect ({KEY_PAGE}), run `ownmetrics-mcp auth`, "
            "then restart your AI app."
        )


class RateLimitedError(OwnMetricsError):
    def __init__(self) -> None:
        super().__init__(
            "Garmin is limiting requests right now. Wait a few minutes and try again, "
            "or ask about a shorter date range."
        )


class GarminUnavailableError(OwnMetricsError):
    def __init__(self, detail: str = "") -> None:
        msg = "Garmin's Personal API did not respond normally. Try again in a few minutes."
        super().__init__(f"{msg} ({detail})" if detail else msg)


class NotProvidedError(OwnMetricsError):
    """The Personal API has no endpoint for this data (HTTP 404). L2."""

    def __init__(self, what: str) -> None:
        self.what = what
        super().__init__(f"{what} is not provided by Garmin's Personal API.")


class InvalidInputError(OwnMetricsError):
    pass
