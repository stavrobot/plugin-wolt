#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.4.1"]
# ///

import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import WoltClient

from wolt_client import format_price, main, text


def get_item_options(
    params: Mapping[str, object], client: WoltClient
) -> dict[str, object]:
    """Return the selectable configurations for one catalog item."""
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object.")
    slug = params.get("slug")
    item_id = params.get("item_id")
    if not isinstance(slug, str):
        raise ValueError("slug must be a restaurant slug.")
    if not isinstance(item_id, str):
        raise ValueError(
            "item_id must be a valid menu item ID. Call get_menu to get valid item IDs."
        )

    assortment = client.get_assortment(slug)
    items = assortment.get("items")
    item = (
        next(
            (
                candidate
                for candidate in items
                if isinstance(candidate, dict) and candidate.get("id") == item_id
            ),
            None,
        )
        if isinstance(items, list)
        else None
    )
    if item is None:
        raise ValueError(
            "item_id is not in this restaurant's assortment. "
            "Call get_menu to get valid item IDs."
        )

    configurations = item.get("options")
    if not isinstance(configurations, list) or not configurations:
        return {"options": []}
    root_options = {
        option["id"]: option
        for option in assortment.get("options", [])
        if isinstance(option, dict) and isinstance(option.get("id"), str)
    }
    venue = client.get_venue_static(slug)["venue"]
    currency = venue.get("currency")
    return {
        "options": [
            _option_configuration(configuration, root_options, currency)
            for configuration in configurations
            if isinstance(configuration, dict)
        ]
    }


def _option_configuration(
    configuration: dict[str, object],
    root_options: dict[str, dict[str, object]],
    currency: str | None,
) -> dict[str, object]:
    """Format one item configuration and state whether woltapi can save it."""
    root_option_id = configuration.get("option_id")
    root_option = (
        root_options.get(root_option_id) if isinstance(root_option_id, str) else None
    )
    minimum, maximum, maximum_single, constraints_reason = _constraints(configuration)
    reason = _unsupported_reason(configuration, root_option, constraints_reason)
    values = root_option.get("values", []) if root_option is not None else []
    if not isinstance(values, list):
        values = []

    result: dict[str, object] = {
        "id": configuration.get("id"),
        "name": text(configuration.get("name")),
        "required": minimum > 0 if minimum is not None else None,
        "total_range": {"min": minimum, "max": maximum},
        "max_single_selections": maximum_single,
        "values": [
            {
                "id": value.get("id"),
                "name": text(value.get("name")),
                "price": format_price(value.get("price"), currency),
            }
            for value in values
            if isinstance(value, dict)
        ],
        "unsupported": reason is not None,
    }
    if reason is not None:
        result["unsupported_reason"] = reason
    return result


def _constraints(
    configuration: Mapping[str, object],
) -> tuple[int | None, int | None, int | None, str | None]:
    """Return selection constraints, or the reason they cannot be used."""
    rules = configuration.get("multi_choice_config")
    total_range = rules.get("total_range") if isinstance(rules, Mapping) else None
    minimum = total_range.get("min") if isinstance(total_range, Mapping) else None
    maximum = total_range.get("max") if isinstance(total_range, Mapping) else None
    maximum_single = (
        rules.get("max_single_selections") if isinstance(rules, Mapping) else None
    )
    free_selections = (
        rules.get("free_selections") if isinstance(rules, Mapping) else None
    )
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or type(maximum_single) is not int
        or type(free_selections) is not int
        or minimum < 0
        or maximum < minimum
        or maximum_single <= 0
    ):
        return None, None, None, "Option selection constraints are unsupported."
    if free_selections != 0:
        return (
            minimum,
            maximum,
            maximum_single,
            "Free-selection pricing is unsupported.",
        )
    return minimum, maximum, maximum_single, None


def _unsupported_reason(
    configuration: Mapping[str, object],
    root_option: Mapping[str, object] | None,
    constraints_reason: str | None,
) -> str | None:
    """Return the first woltapi limitation that prevents saving this configuration."""
    if configuration.get("prerequisite_values") != []:
        return "Conditional options are unsupported."
    if root_option is None:
        return "The referenced root option is missing from the assortment."
    if root_option.get("type") not in {"choice", "multi_choice"}:
        return "The root option type is unsupported."
    return constraints_reason


main(get_item_options)
