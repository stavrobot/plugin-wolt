import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from woltapi import DeliveryTarget, PaymentMethod, VenueCheckoutContext

import wolt_client


@pytest.fixture
def get_quote_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "get_quote" / "run.py"
    spec = importlib.util.spec_from_file_location("get_quote_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_location", lambda: (12.3, 45.6))
    return module


class FakeClient:
    def __init__(
        self,
        *,
        page: dict[str, object] | None = None,
        venue_id: str = "fake-venue",
        targets: tuple[DeliveryTarget, ...] | None = None,
        cards: tuple[PaymentMethod, ...] | None = None,
        quote_response: dict[str, object] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.page = page if page is not None else _saved_page()
        self.venue_id = venue_id
        self.targets = targets or (_delivery_target(),)
        self.cards = cards if cards is not None else (_card(),)
        self.quote_response = (
            quote_response if quote_response is not None else _quote_response()
        )
        self.selection_args: dict[str, object] | None = None

    def get_baskets_page(self, latitude: float, longitude: float) -> dict[str, object]:
        assert (latitude, longitude) == (12.3, 45.6)
        self.calls.append("get_baskets_page")
        return self.page

    def get_assortment(self, slug: str) -> dict[str, object]:
        assert slug == "fake-noodles"
        self.calls.append("get_assortment")
        return _assortment()

    def get_venue_checkout_context(self, slug: str) -> VenueCheckoutContext:
        assert slug == "fake-noodles"
        self.calls.append("get_venue_checkout_context")
        return VenueCheckoutContext(self.venue_id, "FI", "EUR", False, None)

    def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
        self.calls.append("list_delivery_targets")
        return self.targets

    def get_payment_methods(
        self, context: dict[str, object]
    ) -> tuple[PaymentMethod, ...]:
        assert context["venue_id"] == "fake-venue"
        self.calls.append("get_payment_methods")
        return self.cards

    def create_selection(self, assortment: dict[str, object], **kwargs: object) -> object:
        assert self.calls[-2:] == ["list_delivery_targets", "get_payment_methods"]
        assert assortment == _assortment()
        self.calls.append("create_selection")
        self.selection_args = kwargs
        return object()

    def quote_checkout(self, selection: object) -> SimpleNamespace:
        self.calls.append("quote_checkout")
        return SimpleNamespace(
            payable_amount=1440,
            purchase_validation={"end_amount": 1365},
            response=self.quote_response,
        )

    def prepare_purchase(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("A quote tool must never prepare a purchase.")

    def submit_prepared_order(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("A quote tool must never submit an order.")


def test_quote_returns_live_checkout_data_without_a_purchase(
    get_quote_module: object,
) -> None:
    client = FakeClient()

    result = get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert client.calls == [
        "get_baskets_page",
        "get_assortment",
        "get_venue_checkout_context",
        "list_delivery_targets",
        "get_payment_methods",
        "create_selection",
        "quote_checkout",
    ]
    assert client.selection_args is not None
    assert client.selection_args["courier_tip"] == 0
    assert client.selection_args["payment_method"] == {"id": "fake-card", "type": "card"}
    assert "prepare_purchase" not in client.calls
    assert "submit_prepared_order" not in client.calls
    assert result == {
        "payable_amount": "14.40 EUR",
        "purchase_validation_end_amount": "13.65 EUR",
        "fee_breakdown": {
            "items": [
                {"label": "Item subtotal", "amount": "13.60 EUR"},
                {
                    "label": "Service fee",
                    "amount": "0.00 EUR",
                    "original_amount": "0.68 EUR",
                },
                {"label": "Delivery (790 m)", "amount": "0.80 EUR"},
            ],
            "total": "14.40 EUR",
        },
        "courier_tip": "0.00 EUR",
        "delivery_address": {
            "id": "fake-home",
            "alias": "Pretend home",
            "address": "1 Example Way",
            "city": "Faketown",
            "postcode": "00000",
        },
        "card": {"id": "fake-card", "type": "card", "title": "Pretend Visa"},
        "purchase_allowed": True,
        "purchasing_restriction": "none",
        "age_verification_required": False,
        "use_address_matching_for_age_verification": False,
        "basket": {
            "items": [
                {
                    "name": "Fake Noodles",
                    "count": 1,
                    "options": [],
                    "line_price": "7.00 EUR",
                }
            ],
            "total": "7.00 EUR",
        },
        "notice": "Nothing was bought and no card was charged.",
    }


@pytest.mark.parametrize(
    ("quote_response", "restriction", "purchase_allowed"),
    [
        ({"call_to_action": {}}, "not provided", None),
        (
            {"purchasing_disabled": None, "call_to_action": {"enabled": "yes"}},
            "none",
            None,
        ),
        (
            {
                "purchasing_disabled": {"reason": "restricted"},
                "call_to_action": {"enabled": False},
            },
            "present",
            False,
        ),
    ],
)
def test_quote_reports_purchasing_restriction_and_boolean_purchase_permission(
    get_quote_module: object,
    quote_response: dict[str, object],
    restriction: str,
    purchase_allowed: bool | None,
) -> None:
    client = FakeClient(quote_response=quote_response)

    result = get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert result["purchasing_restriction"] == restriction
    assert result["purchase_allowed"] is purchase_allowed


def test_quote_omits_fee_breakdown_when_checkout_rows_are_absent(
    get_quote_module: object,
) -> None:
    client = FakeClient(
        quote_response={
            "payment_breakdown": {"unallocated": {"amount": 1250}},
            "call_to_action": {"enabled": True},
        }
    )

    result = get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert "fee_breakdown" not in result
    assert "unallocated_amount" not in result


def test_quote_ignores_model_supplied_coordinates(get_quote_module: object) -> None:
    client = FakeClient()

    get_quote_module.get_quote(
        {"slug": "fake-noodles", "latitude": -90, "longitude": -180}, client
    )

    assert client.selection_args is not None
    delivery = client.selection_args["delivery"]
    assert (delivery.latitude, delivery.longitude) == (12.3, 45.6)


def test_missing_basket_refuses_before_checkout(get_quote_module: object) -> None:
    client = FakeClient(page={"baskets": []})

    with pytest.raises(ValueError, match="has no saved basket to quote. Use update_basket"):
        get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert client.calls == ["get_baskets_page"]


def test_malformed_baskets_page_refuses_before_checkout(get_quote_module: object) -> None:
    client = FakeClient(page={"baskets": {}})

    with pytest.raises(ValueError, match="baskets page could not be read"):
        get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert client.calls == ["get_baskets_page"]


def test_venue_mismatch_refuses_before_address_and_card_lookups(
    get_quote_module: object,
) -> None:
    client = FakeClient(venue_id="different-fake-venue")

    with pytest.raises(ValueError, match="Saved basket venue does not match"):
        get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert client.calls == [
        "get_baskets_page",
        "get_assortment",
        "get_venue_checkout_context",
    ]


def test_unknown_delivery_target_refuses_before_card_lookup(
    get_quote_module: object,
) -> None:
    client = FakeClient()

    with pytest.raises(ValueError, match="not one of the saved delivery addresses"):
        get_quote_module.get_quote(
            {"slug": "fake-noodles", "delivery_target_id": "missing-target"}, client
        )

    assert client.calls == [
        "get_baskets_page",
        "get_assortment",
        "get_venue_checkout_context",
        "list_delivery_targets",
    ]


def test_non_string_delivery_target_refuses_before_any_network_call(
    get_quote_module: object,
) -> None:
    client = FakeClient()

    with pytest.raises(ValueError, match="delivery_target_id must be a saved delivery"):
        get_quote_module.get_quote(
            {"slug": "fake-noodles", "delivery_target_id": ["fake-home"]}, client
        )

    assert client.calls == []


def test_no_cards_refuses_before_selection(get_quote_module: object) -> None:
    client = FakeClient(cards=())

    with pytest.raises(ValueError, match="No enabled saved cards"):
        get_quote_module.get_quote({"slug": "fake-noodles"}, client)

    assert client.calls == [
        "get_baskets_page",
        "get_assortment",
        "get_venue_checkout_context",
        "list_delivery_targets",
        "get_payment_methods",
    ]


@pytest.mark.parametrize("courier_tip", [-1, 1.5, True, "100"])
def test_invalid_courier_tip_refuses_before_any_network_call(
    get_quote_module: object, courier_tip: object
) -> None:
    client = FakeClient()

    with pytest.raises(ValueError, match="courier_tip must be a non-negative integer"):
        get_quote_module.get_quote(
            {"slug": "fake-noodles", "courier_tip": courier_tip}, client
        )

    assert client.calls == []


def _saved_page() -> dict[str, object]:
    return {
        "baskets": [
            {
                "venue": {
                    "id": "fake-venue",
                    "name": "Fake Noodles",
                    "slug": "fake-noodles",
                    "country": "FI",
                    "available": True,
                },
                "items": [
                    {
                        "id": "fake-noodles",
                        "name": "Fake Noodles",
                        "count": 1,
                        "price": 700,
                        "substitution_settings": {"is_allowed": False},
                        "options": [],
                    }
                ],
            }
        ]
    }


def _quote_response() -> dict[str, object]:
    return {
        "payment_breakdown": {
            "total": {"amount": 1440, "formatted_amount": "€14.40"},
            "unallocated": {"amount": 0, "formatted_amount": "€0.00"},
            "parts": [{"amount": {"amount": 1440}, "payment_method": {}}],
        },
        "checkout_rows": [
            {
                "template": "amount_row",
                "label": "Item subtotal",
                "amount": {"amount": 1360, "formatted_amount": "€13.60"},
                "original_amount": None,
            },
            {
                "template": "amount_row",
                "label": "Service fee",
                "amount": {"amount": 0, "formatted_amount": "€0.00"},
                "original_amount": {"amount": 68, "formatted_amount": "0.68"},
            },
            {
                "template": "amount_row",
                "label": "Delivery (790 m)",
                "amount": {"amount": 80, "formatted_amount": "€0.80"},
                "original_amount": None,
            },
            {
                "template": "price_total_amount_row",
                "label": "Total",
                "price_total_amount": {
                    "amount": 1440,
                    "formatted_amount": "€14.40",
                },
            },
            {"template": "fees_explanation_row", "title": "Fees"},
            {"template": "wolt_plus_text_banner", "text": "Wolt+"},
            {"template": "amount_row", "label": "Malformed", "amount": None},
        ],
        "purchasing_disabled": None,
        "is_age_verification_required": False,
        "use_address_matching_for_age_verification": False,
        "call_to_action": {"enabled": True},
    }


def _delivery_target() -> DeliveryTarget:
    return DeliveryTarget(
        id="fake-home",
        alias="Pretend home",
        label_type="home",
        address="1 Example Way",
        city="Faketown",
        postcode="00000",
    )


def _card() -> PaymentMethod:
    return PaymentMethod(
        id="fake-card",
        type="card",
        is_selected=True,
        is_default=True,
        title="Pretend Visa",
        subtitle=None,
    )


def _assortment() -> dict[str, object]:
    return {
        "items": [
            {
                "id": "fake-noodles",
                "name": [{"lang": "en", "value": "Fake Noodles"}],
                "price": 700,
                "options": [],
                "restrictions": [],
                "alcohol_permille": 0,
                "product_hierarchy_tags": [],
                "vat_percentage": 14,
                "vat_percentage_decimal": "14.0",
            }
        ],
        "options": [],
        "categories": [{"id": "fake-mains", "item_ids": ["fake-noodles"]}],
    }
