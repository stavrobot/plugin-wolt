#!/usr/bin/env -S uv run
# /// script
# dependencies = ["woltapi~=0.4.1"]
# ///

import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from woltapi import DeliverySelection, WoltClient

from wolt_client import (
    configured_location,
    find_saved_basket,
    format_basket,
    format_price,
    main,
    payment_eligibility_context,
    rebuild_saved_basket,
    resolve_card,
    resolve_delivery_target,
    without_nulls,
)


def get_quote(params: Mapping[str, object], client: WoltClient) -> dict[str, object]:
    """Return a live checkout quote for an existing basket without buying anything."""
    if not isinstance(params, Mapping):
        raise ValueError("params must be an object.")
    slug = _required_slug(params.get("slug"))
    delivery_target_id = _delivery_target_id(params)
    courier_tip = _courier_tip(params.get("courier_tip", 0))

    latitude, longitude = configured_location()
    baskets_page = client.get_baskets_page(latitude, longitude)
    if not isinstance(baskets_page, Mapping) or not isinstance(
        baskets_page.get("baskets"), list
    ):
        raise ValueError(
            "The baskets page could not be read; no quote was requested."
        )
    matching_baskets = [
        basket
        for basket in baskets_page["baskets"]
        if isinstance(basket, dict)
        and isinstance(basket.get("venue"), dict)
        and basket["venue"].get("slug") == slug
    ]
    if len(matching_baskets) > 1:
        raise ValueError(
            "More than one saved basket matches this restaurant; no quote was requested."
        )
    saved_basket = find_saved_basket(baskets_page, slug)
    if saved_basket is None:
        raise ValueError(
            "This restaurant has no saved basket to quote. Use update_basket first."
        )

    assortment = client.get_assortment(slug)
    basket = rebuild_saved_basket(assortment, saved_basket)
    venue_context = client.get_venue_checkout_context(slug)
    saved_venue = saved_basket.get("venue")
    if (
        not isinstance(saved_venue, Mapping)
        or saved_venue.get("id") != venue_context.id
    ):
        raise ValueError(
            "Saved basket venue does not match the requested restaurant; "
            "no change was made."
        )

    delivery_target = resolve_delivery_target(
        client.list_delivery_targets(), delivery_target_id
    )
    items = basket.item_selections()
    cards = client.get_payment_methods(payment_eligibility_context(venue_context, items))
    card = resolve_card(cards)
    selection = client.create_selection(
        assortment,
        venue=venue_context,
        delivery=DeliverySelection(delivery_target.id, latitude, longitude),
        payment_method={"id": card.id, "type": card.type},
        courier_tip=courier_tip,
        items=items,
    )
    quote = client.quote_checkout(selection)
    response = quote.response
    purchase_validation = quote.purchase_validation
    call_to_action = response.get("call_to_action")
    action_enabled = (
        call_to_action.get("enabled") if isinstance(call_to_action, Mapping) else None
    )
    # payment_breakdown splits the total by payment method; checkout_rows holds fees.
    fee_breakdown = _fee_breakdown(response.get("checkout_rows"), venue_context.currency)

    result = without_nulls(
        {
            "payable_amount": format_price(quote.payable_amount, venue_context.currency),
            "purchase_validation_end_amount": format_price(
                purchase_validation.get("end_amount"), venue_context.currency
            ),
            "fee_breakdown": fee_breakdown,
            "courier_tip": format_price(courier_tip, venue_context.currency),
            "delivery_address": _delivery_address(delivery_target),
            "card": without_nulls(
                {
                    "id": card.id,
                    "type": card.type,
                    "title": card.title,
                    "subtitle": card.subtitle,
                }
            ),
            "purchasing_restriction": _purchasing_restriction(response),
            "age_verification_required": _boolean(
                response.get("is_age_verification_required")
            ),
            "use_address_matching_for_age_verification": _boolean(
                response.get("use_address_matching_for_age_verification")
            ),
            "basket": format_basket(basket, assortment, venue_context.currency),
            "notice": "Nothing was bought and no card was charged.",
        }
    ) | {"purchase_allowed": _boolean(action_enabled)}
    return result


def _required_slug(value: object) -> str:
    """Require a non-blank restaurant slug."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("slug must be a non-empty restaurant slug.")
    return value


def _delivery_target_id(params: Mapping[str, object]) -> str | None:
    """Validate the optional saved-address reference before listing addresses."""
    if "delivery_target_id" not in params:
        return None
    target_id = params["delivery_target_id"]
    if not isinstance(target_id, str):
        raise ValueError(
            "delivery_target_id must be a saved delivery address ID."
        )
    return target_id


def _courier_tip(value: object) -> int:
    """Require a non-negative integer cent amount without accepting booleans."""
    if type(value) is not int or value < 0:
        raise ValueError("courier_tip must be a non-negative integer number of cents.")
    return value


def _delivery_address(delivery_target: object) -> dict[str, object]:
    """Return the selected saved address so an implicit choice remains visible."""
    return without_nulls(
        {
            "id": getattr(delivery_target, "id", None),
            "alias": getattr(delivery_target, "alias", None)
            or getattr(delivery_target, "label_type", None),
            "address": getattr(delivery_target, "address", None),
            "city": getattr(delivery_target, "city", None),
            "postcode": getattr(delivery_target, "postcode", None),
        }
    )


def _boolean(value: object) -> bool | None:
    """Return a server boolean only when it has the expected JSON type."""
    return value if isinstance(value, bool) else None


def _fee_breakdown(
    checkout_rows: object, currency: str
) -> dict[str, object] | None:
    """Format dynamic fee rows and their displayed checkout total."""
    if not isinstance(checkout_rows, list):
        return None

    items: list[dict[str, str]] = []
    total: str | None = None
    for row in checkout_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("template") == "amount_row":
            label = row.get("label")
            amount = _format_checkout_amount(row.get("amount"), currency)
            if not isinstance(label, str) or amount is None:
                continue
            item = {"label": label, "amount": amount}
            if row.get("original_amount") is not None:
                original_amount = _format_checkout_amount(
                    row.get("original_amount"), currency
                )
                if original_amount is not None:
                    item["original_amount"] = original_amount
            items.append(item)
        elif row.get("template") == "price_total_amount_row":
            row_total = _format_checkout_amount(
                row.get("price_total_amount"), currency
            )
            if row_total is not None:
                total = row_total

    return without_nulls({"items": items, "total": total})


def _format_checkout_amount(amount: object, currency: str) -> str | None:
    """Format an amount object from a checkout row using its cent value."""
    if not isinstance(amount, Mapping):
        return None
    return format_price(amount.get("amount"), currency)


def _purchasing_restriction(response: Mapping[str, object]) -> str:
    """Describe whether the server included a purchasing restriction value."""
    if "purchasing_disabled" not in response:
        return "not provided"
    return "none" if response["purchasing_disabled"] is None else "present"


main(get_quote)
