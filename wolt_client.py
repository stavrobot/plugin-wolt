"""Shared authentication and formatting helpers for Wolt plugin tools."""

import fcntl
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from woltapi import HTTPStatusError, RefreshTokenCredentials, WoltClient

CONFIG_PATH = Path("../config.json")
STATE_PATH = Path("../state.json")
STATE_LOCK_PATH = Path("../state.lock")


def _load_config() -> dict[str, object]:
    """Read the plugin configuration from the tool working directory."""
    return json.loads(CONFIG_PATH.read_text())


def _source_hash(refresh_token: str) -> str:
    """Return the stable identifier used to bind rotated tokens to their source."""
    return hashlib.sha256(refresh_token.encode()).hexdigest()


def _resolve_refresh_token(config_token: str) -> str:
    """Choose the current rotated token when it belongs to the configured source."""
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
        # A newly pasted browser token must supersede stale rotated state.
        if state["source_hash"] == _source_hash(config_token):
            return state["refresh_token"]
    return config_token


def _persist_refresh_token(config_token: str, refresh_token: str) -> None:
    """Atomically retain a rotated refresh token for subsequent tool runs."""
    temporary_path: Path | None = None
    try:
        # The prefix keeps the temporary file inside the gitignored state.json.*
        # pattern, so a kill between the write and the replace cannot strand the
        # live token in a file that git would offer to commit.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=STATE_PATH.parent,
            prefix=f"{STATE_PATH.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(
                {
                    "source_hash": _source_hash(config_token),
                    "refresh_token": refresh_token,
                },
                temporary_file,
            )
        os.replace(temporary_path, STATE_PATH)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink()


def make_client() -> WoltClient:
    """Create a Wolt client backed by the configured refresh token."""
    with STATE_LOCK_PATH.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        # Refresh before API work so separate tool processes cannot exchange one token
        # concurrently, while releasing the lock before a slow API call uses its budget.
        config = _load_config()
        config_token = config["refresh_token"]
        refresh_token = _resolve_refresh_token(config_token)

        def on_refresh(new_token: str) -> None:
            """Persist the server-rotated token against this configured source."""
            _persist_refresh_token(config_token, new_token)

        credentials = RefreshTokenCredentials(
            refresh_token,
            on_refresh=on_refresh,
        )
        credentials.refresh()
        return WoltClient(credentials)


def default_location(params: dict[str, object]) -> tuple[float, float]:
    """Return tool-supplied coordinates or the plugin's configured defaults."""
    config = _load_config()
    latitude = params["latitude"] if "latitude" in params else config["latitude"]
    longitude = params["longitude"] if "longitude" in params else config["longitude"]
    return float(latitude), float(longitude)


def text(value: object) -> str | None:
    """Return a compact English label from Wolt's supported text shapes."""
    if isinstance(value, str):
        return " ".join(value.split())
    if not isinstance(value, list):
        return None

    records = [record for record in value if isinstance(record, dict)]
    for record in records:
        if record.get("lang") == "en" and isinstance(record.get("value"), str):
            return " ".join(record["value"].split())
    for record in records:
        if isinstance(record.get("value"), str):
            return " ".join(record["value"].split())
    return None


def format_price(amount: object, currency: str | None = None) -> str | None:
    """Format an integer-cent price without using floating-point arithmetic."""
    if type(amount) is not int:
        return None
    sign = "-" if amount < 0 else ""
    absolute_amount = abs(amount)
    formatted_amount = f"{sign}{absolute_amount // 100}.{absolute_amount % 100:02d}"
    return (
        f"{formatted_amount} {currency}" if currency is not None else formatted_amount
    )


def without_nulls(mapping: dict[str, object]) -> dict[str, object]:
    """Return a mapping without fields whose values are null."""
    return {key: value for key, value in mapping.items() if value is not None}


def main(handler: Callable[[dict[str, object], WoltClient], dict[str, object]]) -> None:
    """Run a tool handler with parsed parameters and an authenticated client."""
    params = json.load(sys.stdin)
    try:
        result = handler(params, make_client())
    except HTTPStatusError as error:
        # stderr is shown to the user, so a 401 needs guidance instead of a traceback.
        if error.service == "authentication" and error.status_code == 401:
            print(
                "Wolt refresh token is expired or revoked; replace refresh_token in the plugin settings.",
                file=sys.stderr,
            )
            raise SystemExit(1) from None
        raise
    json.dump(result, sys.stdout)
