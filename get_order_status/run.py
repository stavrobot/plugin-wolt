#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.5.0"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import format_price, main, without_nulls


def get_order_status(
    params: dict[str, object], client: WoltClient
) -> dict[str, object]:
    """Return the operational state for one purchase ID."""
    order_status = client.get_order_status(params["purchase_id"])
    return without_nulls(
        {
            "purchase_id": order_status.purchase_id,
            "status": order_status.status,
            "currency": order_status.currency,
            "payment_amount": format_price(
                order_status.payment_amount, order_status.currency
            ),
            "total_price": format_price(
                order_status.total_price, order_status.currency
            ),
            "delivery_price": format_price(
                order_status.delivery_price, order_status.currency
            ),
            "delivery_method": order_status.delivery_method,
        }
    )


main(get_order_status)
