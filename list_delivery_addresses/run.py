#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.5.0"]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import main, without_nulls


def list_delivery_addresses(
    params: dict[str, object], client: WoltClient
) -> dict[str, object]:
    """Return the account's saved delivery addresses."""
    return {
        "addresses": [
            without_nulls(
                {
                    "id": target.id,
                    "alias": target.alias or target.label_type,
                    "address": target.address,
                    "city": target.city,
                    "postcode": target.postcode,
                }
            )
            for target in client.list_delivery_targets()
        ]
    }


main(list_delivery_addresses)
