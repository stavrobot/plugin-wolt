#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.5.0"]
# ///

import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import Basket, SelectionError, WoltClient

from wolt_client import (
    configured_location,
    find_saved_baskets,
    format_basket,
    item_restriction_reason,
    main,
    rebuild_saved_basket,
    text,
    validate_option_selections,
)

_ACTIONS = {"add", "set_count", "set_options", "remove"}


def update_basket(
    params: Mapping[str, object], client: WoltClient
) -> dict[str, object]:
    """Apply one safe basket change and return the local basket just saved."""
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object.")
    slug = _required_text(params.get("slug"), "slug", "restaurant slug")
    action = params.get("action")
    if not isinstance(action, str) or action not in _ACTIONS:
        raise ValueError(
            "action must be one of: add, set_count, set_options, or remove."
        )
    item_id = _required_text(params.get("item_id"), "item_id", "menu item ID")
    count, options = _action_fields(params, action)

    latitude, longitude = configured_location()
    baskets_page = client.get_baskets_page(latitude, longitude)
    if not isinstance(baskets_page, Mapping) or not isinstance(
        baskets_page.get("baskets"), list
    ):
        raise ValueError(
            "The baskets page could not be read; no change was made."
        )
    matching_baskets = find_saved_baskets(baskets_page, slug)
    if len(matching_baskets) > 1:
        raise ValueError(
            "More than one saved basket matches this restaurant; no change was made."
        )
    saved_basket = matching_baskets[0] if matching_baskets else None
    if saved_basket is None and action != "add":
        raise ValueError(
            f"Cannot {action} {_item_label(None, item_id)}: this restaurant has no "
            "saved basket. Use add first to create one."
        )

    assortment = client.get_assortment(slug)
    catalog_item = _catalog_item(assortment, item_id)
    if action == "add" and catalog_item is None:
        raise ValueError(
            f"Cannot add item ID {item_id!r}: it is not in this restaurant's "
            "assortment. Call get_menu for valid item IDs."
        )

    basket = (
        rebuild_saved_basket(assortment, saved_basket)
        if saved_basket is not None
        else Basket(assortment, "en")
    )
    item_label = _item_label(catalog_item, item_id)

    if action == "add":
        assert catalog_item is not None
        existing = basket.contents.get(item_id)
        if existing is not None:
            raise ValueError(
                f"Cannot add {item_label}: it is already in the basket with count "
                f"{existing.count} and options {_option_summary(existing)}. Use "
                "set_count to change the count or set_options to change the options."
            )
        restriction_reason = item_restriction_reason(catalog_item)
        if restriction_reason is not None:
            raise ValueError(
                f"Cannot add {item_label}: {restriction_reason} "
                "Choose a different item from get_menu."
            )
    # Deleting a basket must remain an explicit caller choice, never a side
    # effect of removing its final item.
    elif (
        action == "remove" and item_id in basket.contents and len(basket.contents) == 1
    ):
        raise ValueError(
            f"Cannot remove {item_label}: it is the last item in the basket. "
            "Use empty_basket to delete the whole basket."
        )

    try:
        if action == "add":
            basket.add_item(item_id, count, options)
        elif action == "set_count":
            basket.set_count(item_id, count)
        elif action == "set_options":
            basket.set_options(item_id, options)
        else:
            basket.remove_item(item_id)
    except SelectionError as error:
        raise ValueError(_selection_error(action, item_label, error)) from None

    venue_context = client.get_venue_checkout_context(slug)
    if saved_basket is not None:
        saved_venue = saved_basket.get("venue")
        if (
            not isinstance(saved_venue, Mapping)
            or saved_venue.get("id") != venue_context.id
        ):
            raise ValueError(
                "Saved basket venue does not match the requested restaurant; "
                "no change was made."
            )
    try:
        client.save_basket_items(
            assortment, venue=venue_context, items=basket.item_selections()
        )
    except SelectionError as error:
        raise ValueError(
            f"Wolt rejected the basket because {error}. The cause may be another "
            "item already in the basket."
        ) from None

    return format_basket(basket, assortment, venue_context.currency)


def _action_fields(
    params: Mapping[str, object], action: str
) -> tuple[int | None, tuple[object, ...]]:
    """Validate action-specific JSON fields before reading or replacing a basket."""
    count: int | None = None
    options: tuple[object, ...] = ()
    if action in {"add", "set_count"}:
        count = _positive_count(params.get("count"))
    if action == "set_options" or (action == "add" and "option_selections" in params):
        options = validate_option_selections(params.get("option_selections"))
    return count, options


def _catalog_item(
    assortment: Mapping[str, object], item_id: str
) -> Mapping[str, object] | None:
    """Return the requested menu item when it is present in the assortment."""
    items = assortment.get("items")
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, Mapping) and item.get("id") == item_id
        ),
        None,
    )


def _required_text(value: object, field_name: str, description: str) -> str:
    """Require a non-blank string tool parameter."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty {description}.")
    return value


def _positive_count(value: object) -> int:
    """Require a positive integer count without accepting JSON booleans."""
    if type(value) is not int or value <= 0:
        raise ValueError("count must be a positive integer.")
    return value


def _item_label(item: Mapping[str, object] | None, item_id: str) -> str:
    """Return a useful item name and ID for a refusal message."""
    name = text(item.get("name")) if item is not None else None
    return f"{name or item_id!r} (ID {item_id!r})"


def _option_summary(item: object) -> str:
    """Summarize a stored selection's chosen options for duplicate-add guidance."""
    options = getattr(item, "options", ())
    summaries = []
    for option in options:
        values = ", ".join(f"{value.id} x{value.count}" for value in option.values)
        summaries.append(f"{option.configuration_id}=[{values}]")
    return "; ".join(summaries) if summaries else "no options"


def _selection_error(action: str, item_label: str, error: SelectionError) -> str:
    """Make library validation failures actionable without changing the basket."""
    if str(error) == "The item is not in the basket.":
        return (
            f"Cannot {action} {item_label}: it is not in the basket. Use "
            "view_basket to see current items or add to add it."
        )
    return (
        f"Cannot {action} {item_label}: Wolt cannot save this selection because "
        f"{error} Choose a permitted count or option selection (use "
        "get_item_options for options) and retry."
    )


main(update_basket)
