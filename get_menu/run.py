#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.5.0"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import format_price, main, text, without_nulls


def get_menu(params: dict[str, object], client: WoltClient) -> dict[str, object]:
    """Return a bounded, optionally filtered restaurant menu."""
    slug = params["slug"]
    filter_value = params.get("filter", "")
    limit = params.get("limit", 30)
    if not isinstance(filter_value, str):
        raise ValueError("filter must be a string.")
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer.")
    assortment = client.get_assortment(slug)
    items = assortment["items"]
    venue = client.get_venue_static(slug)["venue"]
    currency = venue.get("currency")
    matching_items = [
        item
        for item in items
        if (name := text(item.get("name"))) is not None
        and filter_value.casefold() in name.casefold()
    ]
    return {
        "total": len(matching_items),
        "items": [_menu_item(item, currency) for item in matching_items[:limit]],
    }


def _menu_item(item: dict[str, object], currency: str | None) -> dict[str, object]:
    """Format the item fields useful for menu selection."""
    return without_nulls(
        {
            "id": item.get("id"),
            "name": text(item.get("name")),
            "description": text(item.get("description")),
            "price": format_price(item.get("price"), currency),
            "has_options": bool(item.get("options")),
            "is_restricted_or_alcoholic": bool(item.get("restrictions"))
            or bool(item.get("alcohol_permille")),
        }
    )


main(get_menu)
