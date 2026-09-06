import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
from woltapi import (
    HTTPStatusError,
    ItemSelection,
    PaymentMethod,
    VenueCheckoutContext,
    WoltApiError,
)
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


def test_validate_option_selections_converts_valid_json_values() -> None:
    selections = wolt_client.validate_option_selections(
        [
            {
                "configuration_id": "size",
                "values": [{"id": "large", "count": 2}],
            }
        ]
    )

    assert selections[0].configuration_id == "size"
    assert selections[0].values[0].id == "large"
    assert selections[0].values[0].count == 2


@pytest.mark.parametrize(
    "value",
    [
        {},
        [{"values": []}],
        [{"configuration_id": "size", "values": {}}],
        [{"configuration_id": "size", "values": [{"id": "large", "count": 0}]}],
        [{"configuration_id": "size", "values": [{"id": "large", "count": True}]}],
    ],
)
def test_validate_option_selections_rejects_invalid_shape(value: object) -> None:
    with pytest.raises(ValueError, match="must be a list of objects"):
        wolt_client.validate_option_selections(value)


def test_resolve_card_prefers_default_over_selected() -> None:
    selected = PaymentMethod("selected", "card", True, False, "Selected", None)
    default = PaymentMethod("default", "card", False, True, "Default", None)

    assert wolt_client.resolve_card((selected, default)) is default


def test_resolve_card_uses_selected_then_only_card() -> None:
    selected = PaymentMethod("selected", "card", True, False, "Selected", None)
    other = PaymentMethod("other", "card", False, False, "Other", None)
    only = PaymentMethod("only", "card", False, False, "Only", None)

    assert wolt_client.resolve_card((other, selected)) is selected
    assert wolt_client.resolve_card((only,)) is only


def test_resolve_card_lists_ambiguous_cards() -> None:
    cards = (
        PaymentMethod("one", "card", False, False, "Visa", "•••• 1234"),
        PaymentMethod("two", "card", False, False, "Mastercard", "•••• 5678"),
    )

    with pytest.raises(ValueError, match="Visa.*Mastercard"):
        wolt_client.resolve_card(cards)


def test_rebuild_saved_basket_names_removed_item() -> None:
    saved_basket = {"items": [{"id": "removed", "name": "Retired ramen"}]}

    with pytest.raises(ValueError, match="Retired ramen.*empty it in the Wolt app"):
        wolt_client.rebuild_saved_basket({"items": []}, saved_basket)


def test_rebuild_saved_basket_names_duplicate_item() -> None:
    saved_basket = {
        "items": [
            {"id": "ramen", "name": "Ramen"},
            {"id": "ramen", "name": "Ramen with extra egg"},
        ]
    }

    with pytest.raises(
        ValueError, match="Ramen with extra egg.*empty it in the Wolt app"
    ):
        wolt_client.rebuild_saved_basket({"items": [{"id": "ramen"}]}, saved_basket)


def test_rebuild_saved_basket_names_item_with_removed_option_value() -> None:
    assortment = {
        "items": [
            {
                "id": "ramen",
                "price": 1000,
                "options": [{"id": "size", "option_id": "sizes"}],
            }
        ],
        "options": [{"id": "sizes", "values": []}],
    }
    saved_basket = {
        "venue": {
            "id": "venue",
            "name": "Ramen shop",
            "slug": "ramen-shop",
            "country": "FI",
            "available": True,
        },
        "items": [
            {
                "id": "ramen",
                "name": "Spicy ramen",
                "price": 1000,
                "count": 1,
                "substitution_settings": {"is_allowed": False},
                "options": [
                    {"id": "size", "values": [{"id": "large", "count": 1}]}
                ],
            }
        ],
    }

    with pytest.raises(
        ValueError, match="Spicy ramen.*cannot be changed.*empty it in the Wolt app"
    ):
        wolt_client.rebuild_saved_basket(assortment, saved_basket)


def test_rebuild_saved_basket_names_item_with_malformed_data() -> None:
    saved_basket = {
        "venue": {
            "id": "venue",
            "name": "Ramen shop",
            "slug": "ramen-shop",
            "country": "FI",
            "available": True,
        },
        "items": [{"id": "ramen", "name": "Spicy ramen"}],
    }

    with pytest.raises(
        ValueError, match="Spicy ramen.*malformed.*empty it in the Wolt app"
    ):
        wolt_client.rebuild_saved_basket({"items": [{"id": "ramen"}]}, saved_basket)


def test_payment_eligibility_context_has_payment_methods_request_shape() -> None:
    venue = VenueCheckoutContext("venue-id", "FI", "EUR", False, None)
    item = ItemSelection(
        "ramen",
        2,
        "Spicy ramen",
        2000,
        2000,
        False,
        {"alcohol_permille": 0},
        payment_fields={
            "product_hierarchy_tags": ["ramen"],
            "vat_percentage": 14,
            "vat_percentage_decimal": "14.0",
        },
    )

    assert wolt_client.payment_eligibility_context(venue, (item,)) == {
        "venue_id": "venue-id",
        "country": "FI",
        "delivery_method": "homedelivery",
        "available_methods": ["card"],
        "items": [
            {
                "id": "ramen",
                "alcohol_permille": 0,
                "product_hierarchy_tags": ["ramen"],
                "vat_percentage": 14,
                "vat_percentage_decimal": "14.0",
            }
        ],
    }


@pytest.mark.parametrize(
    "error",
    [ValueError("retry with a valid option selection"), WoltApiError("item is unavailable")],
)
def test_main_prints_actionable_errors_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(wolt_client.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(wolt_client, "make_client", lambda: object())

    with pytest.raises(SystemExit, match="1"):
        wolt_client.main(lambda params, client: (_ for _ in ()).throw(error))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{error}\n"


def test_main_reraises_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wolt_client.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(wolt_client, "make_client", lambda: object())

    with pytest.raises(KeyError, match="missing parameter"):
        wolt_client.main(
            lambda params, client: (_ for _ in ()).throw(KeyError("missing parameter"))
        )


def test_main_guides_refresh_when_authentication_returns_401(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(wolt_client.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(wolt_client, "make_client", lambda: object())

    with pytest.raises(SystemExit, match="1"):
        wolt_client.main(
            lambda params, client: (_ for _ in ()).throw(
                HTTPStatusError("authentication", 401)
            )
        )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refresh token is expired or revoked" in captured.err


def test_main_reraises_non_authentication_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = HTTPStatusError("consumer", 500)
    monkeypatch.setattr(wolt_client.sys, "stdin", io.StringIO("{}"))
    monkeypatch.setattr(wolt_client, "make_client", lambda: object())

    with pytest.raises(HTTPStatusError) as raised:
        wolt_client.main(lambda params, client: (_ for _ in ()).throw(error))

    assert raised.value is error
