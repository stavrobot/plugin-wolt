#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.4.1"]
# ///

import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import (
    configured_location,
    find_saved_basket,
    format_basket,
    main,
    rebuild_saved_basket,
    text,
    without_nulls,
)


def view_basket(
    params: Mapping[str, object], client: WoltClient
) -> dict[str, object]:
    """Return saved basket summaries or one current menu-priced basket."""
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object.")
    latitude, longitude = configured_location()
    baskets_page = client.get_baskets_page(latitude, longitude)
    slug = params.get("slug")
    if slug is None:
        return {"baskets": _basket_summaries(baskets_page)}
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError("slug must be a non-empty restaurant slug.")

    saved_basket = find_saved_basket(baskets_page, slug)
    if saved_basket is None:
        return {"slug": slug, "has_basket": False}

    assortment = client.get_assortment(slug)
    basket = rebuild_saved_basket(assortment, saved_basket)
    venue = client.get_venue_static(slug)["venue"]
    currency = venue.get("currency")
    return {
        **_basket_summary(saved_basket),
        **format_basket(basket, assortment, currency),
    }


def _basket_summaries(baskets_page: dict[str, object]) -> list[dict[str, object]]:
    """Format each valid saved basket without fetching its assortment."""
    baskets = baskets_page.get("baskets")
    if not isinstance(baskets, list):
        return []
    return [_basket_summary(basket) for basket in baskets if isinstance(basket, dict)]


def _basket_summary(saved_basket: dict[str, object]) -> dict[str, object]:
    """Return the page-only fields needed to identify a saved basket."""
    venue = saved_basket.get("venue")
    if not isinstance(venue, dict):
        venue = {}
    items = saved_basket.get("items")
    return without_nulls(
        {
            "restaurant_name": text(venue.get("name")),
            "slug": venue.get("slug"),
            "item_count": len(items) if isinstance(items, list) else 0,
            "available": venue.get("available"),
        }
    )


main(view_basket)
