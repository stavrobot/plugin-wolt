import json
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
from woltapi.credentials import SessionCredentials

import wolt_client


class RotatingCredentials(SessionCredentials):
    """Record refresh inputs while exercising the plugin's persistence callback."""

    refresh_tokens: ClassVar[list[str]] = []
    refresh_calls: ClassVar[int] = 0

    def __init__(
        self, refresh_token: str, *, on_refresh: Callable[[str], None]
    ) -> None:
        super().__init__()
        self.refresh_token = refresh_token
        self.on_refresh = on_refresh
        type(self).refresh_tokens.append(refresh_token)

    def refresh(self) -> None:
        """Simulate the public exchange method rotating a refresh token."""
        type(self).refresh_calls += 1
        self.on_refresh(f"rotated-{self.refresh_token}")


@pytest.fixture(autouse=True)
def reset_rotating_credentials() -> None:
    """Keep recorded credential inputs isolated across token-state tests."""
    RotatingCredentials.refresh_tokens = []
    RotatingCredentials.refresh_calls = 0


def configure_paths(monkeypatch: pytest.MonkeyPatch, temporary_path: Path) -> Path:
    """Direct plugin state files to the isolated test directory."""
    config_path = temporary_path / "config.json"
    monkeypatch.setattr(wolt_client, "CONFIG_PATH", config_path)
    monkeypatch.setattr(wolt_client, "STATE_PATH", temporary_path / "state.json")
    monkeypatch.setattr(wolt_client, "STATE_LOCK_PATH", temporary_path / "state.lock")
    return config_path


def test_rotated_token_persists_and_is_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = configure_paths(monkeypatch, tmp_path)
    config_path.write_text(json.dumps({"refresh_token": "configured-token"}))
    monkeypatch.setattr(wolt_client, "RefreshTokenCredentials", RotatingCredentials)

    wolt_client.make_client()
    wolt_client.make_client()

    state = json.loads((tmp_path / "state.json").read_text())
    assert RotatingCredentials.refresh_tokens == [
        "configured-token",
        "rotated-configured-token",
    ]
    assert RotatingCredentials.refresh_calls == 2
    assert state["refresh_token"] == "rotated-rotated-configured-token"


def test_changed_config_token_ignores_persisted_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = configure_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(wolt_client, "RefreshTokenCredentials", RotatingCredentials)
    config_path.write_text(json.dumps({"refresh_token": "first-configured-token"}))
    wolt_client.make_client()

    config_path.write_text(
        json.dumps({"refresh_token": "replacement-configured-token"})
    )
    wolt_client.make_client()

    assert RotatingCredentials.refresh_tokens == [
        "first-configured-token",
        "replacement-configured-token",
    ]


def test_failed_state_write_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(wolt_client, "STATE_PATH", tmp_path / "state.json")

    def fail_json_dump(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(wolt_client.json, "dump", fail_json_dump)

    with pytest.raises(OSError, match="synthetic write failure"):
        wolt_client._persist_refresh_token("configured-token", "rotated-token")

    assert list(tmp_path.iterdir()) == []
