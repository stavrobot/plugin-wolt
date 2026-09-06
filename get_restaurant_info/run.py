#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.1.0"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import default_location, format_price, main, text, without_nulls


def get_restaurant_info(
    params: dict[str, object], client: WoltClient
) -> dict[str, object]:
    """Return the practical details for a restaurant at a delivery location."""
    latitude, longitude = default_location(params)
    static = client.get_venue_static(params["slug"])
    dynamic = client.get_venue_dynamic(params["slug"], latitude, longitude)
    static_venue = static["venue"]
    dynamic_venue = dynamic["venue"]
    currency = static_venue["currency"]
    delivery_config = next(
        (
            config
            for config in dynamic_venue["delivery_configs"]
            if config["method"] == "homedelivery"
        ),
        None,
    )
    delivery_status = next(
        (
            status
            for status in dynamic_venue["header"]["delivery_method_statuses"]
            if status["delivery_method"]
            == dynamic_venue["header"]["delivery_method_default"]
        ),
        None,
    )
    delivery_fee = (
        next(
            (
                metadata
                for metadata in delivery_status["metadata"]
                if metadata["meaning"] == "DELIVERY_FEE"
            ),
            None,
        )
        if delivery_status is not None
        else None
    )
    opening_status = dynamic_venue["delivery_open_status"]
    opening_hours = {
        schedule["day"]: schedule["formatted_times"]
        for schedule in static_venue["opening_times_schedule"]
    }
    return without_nulls(
        {
            "name": text(static_venue["name"]),
            "address": text(static_venue["address"]),
            "opening_hours": opening_hours,
            "is_open": opening_status["is_open"],
            "open_status": text(opening_status["value"]),
            "minimum_order_value": format_price(static["order_minimum"], currency),
            # Wolt sends rating as null, not a missing key, for an unrated venue.
            "rating": text((static_venue.get("rating") or {}).get("score")),
            "phone": text(static_venue.get("phone")),
            "url": static_venue["share_url"],
            "delivery_estimate": (
                text(delivery_config["estimate"]["label"])
                if delivery_config is not None
                else None
            ),
            "delivery_fee": (
                text(delivery_fee["value"]) if delivery_fee is not None else None
            ),
        }
    )


main(get_restaurant_info)
