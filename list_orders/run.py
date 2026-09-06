#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.4.1"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import main, text, without_nulls

ITEM_LIMIT = 10
DEFAULT_ORDER_LIMIT = 5


def order_limit(params: dict[str, object]) -> int:
    """Return the requested number of orders after validating its range."""
    limit = params.get("limit", DEFAULT_ORDER_LIMIT)
    if limit < 1:
        raise ValueError("limit must be a positive integer.")
    return limit


def list_orders(params: dict[str, object], client: WoltClient) -> dict[str, object]:
    """Return a compact summary of the first order-history page."""
    page = client.get_orders_page()
    orders = page["orders"]

    summaries: list[dict[str, object]] = []
    for order in orders[: order_limit(params)]:
        venue = order["venue"]
        items = order["items"]

        omitted_item_count = len(items) - ITEM_LIMIT
        summaries.append(
            without_nulls(
                {
                    "purchase_id": order["purchase_id"],
                    "timestamp": order["timestamp"],
                    "venue_name": text(venue["name"]),
                    "items": [
                        without_nulls(
                            {
                                "count": item["count"],
                                "name": text(item["name"]),
                            }
                        )
                        for item in items[:ITEM_LIMIT]
                    ],
                    "status": text(order["status"]),
                    "total": text(order.get("total")),
                    "omitted_item_count": (
                        omitted_item_count if omitted_item_count > 0 else None
                    ),
                }
            )
        )

    return {"orders": summaries}


main(list_orders)
