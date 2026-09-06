"""Shared authentication and formatting helpers for Wolt plugin tools."""

import fcntl
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from woltapi import (
    Basket,
    DeliveryTarget,
    HTTPStatusError,
    ItemSelection,
    OptionSelection,
    OptionValueSelection,
    PaymentMethod,
    RefreshTokenCredentials,
    ResponseShapeError,
    SelectionError,
    VenueCheckoutContext,
    WoltApiError,
    WoltClient,
)

CONFIG_PATH = Path("../config.json")
STATE_PATH = Path("../state.json")
STATE_LOCK_PATH = Path("../state.lock")
OPTION_SELECTIONS_SHAPE = (
    "option_selections must be a list of objects with a configuration_id string "
    "and a values list of objects with an id string and a positive integer count."
)


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


def configured_location() -> tuple[float, float]:
    """Return the plugin's configured coordinates."""
    config = _load_config()
    return float(config["latitude"]), float(config["longitude"])


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


def find_saved_basket(
    baskets_page: Mapping[str, object], slug: str
) -> dict[str, object] | None:
    """Return the saved basket for ``slug``, if the page contains one."""
    baskets = baskets_page.get("baskets")
    if not isinstance(baskets, list):
        return None
    for basket in baskets:
        if not isinstance(basket, dict):
            continue
        venue = basket.get("venue")
        if isinstance(venue, dict) and venue.get("slug") == slug:
            return basket
    return None


def rebuild_saved_basket(
    assortment: Mapping[str, object], saved_basket: Mapping[str, object]
) -> Basket:
    """Rebuild a server basket, naming saved items that prevent recovery."""
    catalog_items = assortment.get("items")
    saved_items = saved_basket.get("items")
    if isinstance(catalog_items, list) and isinstance(saved_items, list):
        catalog_item_ids = {
            item["id"]
            for item in catalog_items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        seen_item_ids: set[str] = set()
        for saved_item in saved_items:
            if not isinstance(saved_item, dict):
                continue
            item_id = saved_item.get("id")
            if not isinstance(item_id, str):
                continue
            item_name = saved_item.get("name")
            display_name = item_name if isinstance(item_name, str) else item_id
            if item_id not in catalog_item_ids:
                raise ValueError(
                    f"Saved basket item {display_name!r} (ID {item_id!r}) is no longer "
                    "on the menu. "
                    "This basket cannot be changed; empty it in the Wolt app."
                )
            if item_id in seen_item_ids:
                raise ValueError(
                    f"Saved basket has duplicate lines for {display_name!r} (ID "
                    f"{item_id!r}). "
                    "This basket cannot be changed; empty it in the Wolt app."
                )
            seen_item_ids.add(item_id)
    try:
        return Basket.from_saved_basket(assortment, saved_basket, "en")
    except (ResponseShapeError, SelectionError) as error:
        failure_description = (
            "has malformed saved basket data"
            if isinstance(error, ResponseShapeError)
            else "contains a saved menu selection that is no longer available"
        )
        if isinstance(saved_items, list):
            for saved_item in saved_items:
                if not isinstance(saved_item, dict):
                    continue
                try:
                    Basket.from_saved_basket(
                        assortment, {**saved_basket, "items": [saved_item]}, "en"
                    )
                except (ResponseShapeError, SelectionError):
                    item_name = saved_item.get("name")
                    display_name = (
                        item_name
                        if isinstance(item_name, str)
                        else saved_item.get("id", "an unnamed item")
                    )
                    raise ValueError(
                        f"Saved basket item {display_name!r} {failure_description}. "
                        "This basket cannot be changed; empty it in the Wolt app."
                    ) from None
        raise ValueError(
            f"The saved basket {failure_description}. "
            "This basket cannot be changed; empty it in the Wolt app."
        ) from None


def payment_eligibility_context(
    venue: VenueCheckoutContext, items: Sequence[ItemSelection]
) -> dict[str, object]:
    """Build the card-eligibility context for the current basket items."""
    context_items: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item.payment_fields, Mapping):
            raise TypeError("The selected item is missing payment eligibility fields.")
        context_items.append(
            {
                "id": item.id,
                "alcohol_permille": item.checkout_fields["alcohol_permille"],
                **item.payment_fields,
            }
        )
    return {
        "venue_id": venue.id,
        "country": venue.country,
        "delivery_method": "homedelivery",
        "available_methods": ["card"],
        "items": context_items,
    }


def resolve_card(cards: Sequence[PaymentMethod]) -> PaymentMethod:
    """Choose Wolt's default or selected card, or require an explicit choice."""
    for card in cards:
        if card.is_default:
            return card
    for card in cards:
        if card.is_selected:
            return card
    if len(cards) == 1:
        return cards[0]
    if not cards:
        raise ValueError("No enabled saved cards are available in Wolt.")
    available_cards = "; ".join(_card_description(card) for card in cards)
    raise ValueError(
        "Wolt did not mark a default or selected card. Choose a card in the Wolt "
        f"app, then retry. Available cards: {available_cards}."
    )


def resolve_delivery_target(
    delivery_targets: Sequence[DeliveryTarget], delivery_target_id: object | None = None
) -> DeliveryTarget:
    """Choose a requested saved address or the first address returned by Wolt."""
    if delivery_target_id is not None:
        if not isinstance(delivery_target_id, str):
            raise ValueError("delivery_target_id must be a saved delivery address ID.")
        target = next(
            (target for target in delivery_targets if target.id == delivery_target_id),
            None,
        )
        if target is None:
            raise ValueError(
                "The requested delivery_target_id is not one of the saved delivery "
                "addresses. Call list_delivery_addresses and retry with its ID."
            )
        return target
    if not delivery_targets:
        raise ValueError("No saved delivery addresses are available in Wolt.")
    return delivery_targets[0]


def validate_option_selections(value: object) -> tuple[OptionSelection, ...]:
    """Validate JSON tool option selections and convert them to library values."""
    if not isinstance(value, list):
        raise _option_selections_shape_error()

    selections: list[OptionSelection] = []
    for selection in value:
        if not isinstance(selection, dict) or not isinstance(
            selection.get("configuration_id"), str
        ):
            raise _option_selections_shape_error()
        values = selection.get("values")
        if not isinstance(values, list):
            raise _option_selections_shape_error()
        selected_values: list[OptionValueSelection] = []
        for selected_value in values:
            count = (
                selected_value.get("count")
                if isinstance(selected_value, dict)
                else None
            )
            if (
                not isinstance(selected_value, dict)
                or not isinstance(selected_value.get("id"), str)
                or type(count) is not int
                or count <= 0
            ):
                raise _option_selections_shape_error()
            selected_values.append(OptionValueSelection(selected_value["id"], count))
        selections.append(
            OptionSelection(selection["configuration_id"], selected_values)
        )
    return tuple(selections)


def format_basket(
    basket: Basket, assortment: Mapping[str, object], currency: str | None
) -> dict[str, object]:
    """Format current catalog-derived basket lines and their total for tool output."""
    assortment_options = assortment.get("options")
    if not isinstance(assortment_options, list):
        assortment_options = []
    root_options = {
        option["id"]: option
        for option in assortment_options
        if isinstance(option, dict) and isinstance(option.get("id"), str)
    }
    assortment_items = assortment.get("items")
    if not isinstance(assortment_items, list):
        assortment_items = []
    catalog_items = {
        item["id"]: item
        for item in assortment_items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    lines: list[dict[str, object]] = []
    total = 0
    for item in basket.item_selections():
        total += item.basket_price
        lines.append(
            {
                "name": item.basket_name,
                "count": item.count,
                "options": _selected_option_names(
                    item, catalog_items.get(item.id), root_options
                ),
                "line_price": format_price(item.basket_price, currency),
            }
        )
    return {"items": lines, "total": format_price(total, currency)}


def item_restriction_reason(item: Mapping[str, object]) -> str | None:
    """Return why an item is restricted or alcoholic, if it must be refused."""
    has_restrictions = bool(item.get("restrictions"))
    has_alcohol = item.get("alcohol_permille") != 0
    if has_restrictions and has_alcohol:
        return "This item has restrictions and contains alcohol, so it cannot be added."
    if has_restrictions:
        return "This item has restrictions, so it cannot be added."
    if has_alcohol:
        return "This item contains alcohol, so it cannot be added."
    return None


def _card_description(card: PaymentMethod) -> str:
    return " | ".join(value for value in (card.title, card.subtitle) if value) or (
        f"{card.id} ({card.type})"
    )


def _option_selections_shape_error() -> ValueError:
    return ValueError(OPTION_SELECTIONS_SHAPE)


def _selected_option_names(
    item: ItemSelection,
    catalog_item: dict[str, object] | None,
    root_options: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    configurations = {
        configuration["id"]: configuration
        for configuration in (catalog_item or {}).get("options", [])
        if isinstance(configuration, dict) and isinstance(configuration.get("id"), str)
    }
    selected_names: list[dict[str, object]] = []
    for selection in item.options:
        configuration = configurations.get(selection.configuration_id, {})
        root_option = root_options.get(configuration.get("option_id"), {})
        values = {
            value["id"]: value
            for value in root_option.get("values", [])
            if isinstance(value, dict) and isinstance(value.get("id"), str)
        }
        for selected_value in selection.values:
            value = values.get(selected_value.id, {})
            selected_names.append(
                {
                    "name": text(value.get("name")) or selected_value.id,
                    "count": selected_value.count,
                }
            )
    return selected_names


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
    except (ValueError, WoltApiError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from None
    json.dump(result, sys.stdout)
