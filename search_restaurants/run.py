#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.1.0"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import default_location, main, text, without_nulls


def search_restaurants(
    params: dict[str, object], client: WoltClient
) -> dict[str, object]:
    """Return compact nearby restaurant search results."""
    latitude, longitude = default_location(params)
    venues = client.search_venues(params["query"], latitude, longitude)
    return {
        "restaurants": [
            without_nulls(
                {
                    "title": text(venue.title) or venue.slug,
                    "slug": venue.slug,
                    "currency": venue.currency,
                    "delivers": venue.delivers,
                    "online": venue.online,
                }
            )
            for venue in venues[:10]
        ]
    }


main(search_restaurants)
