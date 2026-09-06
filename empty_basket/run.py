#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.5.0"]
# ///

import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import (
    configured_location,
    find_saved_baskets,
    main,
    text,
    without_nulls,
)


def empty_basket(params: Mapping[str, object], client: WoltClient) -> dict[str, object]:
    """Permanently delete every saved basket matching one restaurant."""
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object.")
    slug = params.get("slug")
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError("slug must be a non-empty restaurant slug.")

    latitude, longitude = configured_location()
    baskets_page = client.get_baskets_page(latitude, longitude)
    if not isinstance(baskets_page, Mapping) or not isinstance(
        baskets_page.get("baskets"), list
    ):
        raise ValueError("The baskets page could not be read; no basket was deleted.")
    matching_baskets = find_saved_baskets(baskets_page, slug)
    if not matching_baskets:
        return without_nulls(
            {
                "slug": slug,
                "restaurant_name": None,
                "has_basket": False,
                "deleted_count": 0,
            }
        )

    basket_ids: list[str] = []
    for basket in matching_baskets:
        basket_id = basket.get("id")
        if not isinstance(basket_id, str) or not basket_id.strip():
            raise ValueError("Saved basket ID is invalid; no basket was deleted.")
        basket_ids.append(basket_id)

    venue = matching_baskets[0].get("venue")
    restaurant_name = text(venue.get("name")) if isinstance(venue, dict) else None
    client.delete_baskets(basket_ids)

    # This only rechecks the coordinate-based page that found the basket; its pagination
    # cursor is not followed, and coordinate filtering is uncertain, so absence is not proof.
    baskets_page = client.get_baskets_page(latitude, longitude)
    if not isinstance(baskets_page, Mapping) or not isinstance(
        baskets_page.get("baskets"), list
    ):
        raise ValueError(
            "The baskets page could not be read; deletion could not be confirmed."
        )
    if find_saved_baskets(baskets_page, slug):
        raise ValueError("Wolt did not delete the saved basket; it is still present.")

    return without_nulls(
        {
            "slug": slug,
            "restaurant_name": restaurant_name,
            "has_basket": True,
            "deleted_count": len(basket_ids),
        }
    )


main(empty_basket)
