import importlib.util
from pathlib import Path

import pytest

import wolt_client


@pytest.fixture
def view_basket_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "view_basket" / "run.py"
    spec = importlib.util.spec_from_file_location("view_basket_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_location", lambda: (12.3, 45.6))
    return module


def test_no_baskets_returns_an_empty_summary(view_basket_module: object) -> None:
    class FakeClient:
        def get_baskets_page(
            self, latitude: float, longitude: float
        ) -> dict[str, object]:
            assert (latitude, longitude) == (12.3, 45.6)
            return {"baskets": []}

        def get_assortment(self, slug: str) -> dict[str, object]:
            raise AssertionError("summary mode must not fetch an assortment")

    assert view_basket_module.view_basket({}, FakeClient()) == {"baskets": []}


def test_non_object_params_are_rejected_before_fetching_baskets(
    view_basket_module: object,
) -> None:
    with pytest.raises(ValueError, match="params must be an object"):
        view_basket_module.view_basket([], object())


def test_summary_mode_uses_only_the_baskets_page(view_basket_module: object) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get_baskets_page(
            self, latitude: float, longitude: float
        ) -> dict[str, object]:
            self.calls.append("get_baskets_page")
            return {
                "baskets": [
                    _saved_basket("pretend-pizzeria", "Pretend Pizzeria", True, []),
                    _saved_basket(
                        "imaginary-noodles",
                        "Imaginary Noodles",
                        False,
                        [{"id": "fake-noodles"}, {"id": "fake-tea"}],
                    ),
                ]
            }

        def get_assortment(self, slug: str) -> dict[str, object]:
            raise AssertionError("summary mode must not fetch an assortment")

        def get_venue_static(self, slug: str) -> dict[str, object]:
            raise AssertionError("summary mode must not fetch venue details")

    client = FakeClient()
    assert view_basket_module.view_basket({}, client) == {
        "baskets": [
            {
                "restaurant_name": "Pretend Pizzeria",
                "slug": "pretend-pizzeria",
                "item_count": 0,
                "available": True,
            },
            {
                "restaurant_name": "Imaginary Noodles",
                "slug": "imaginary-noodles",
                "item_count": 2,
                "available": False,
            },
        ]
    }
    assert client.calls == ["get_baskets_page"]


def test_slug_mode_rebuilds_and_formats_current_menu_items(
    view_basket_module: object,
) -> None:
    saved_basket = _saved_basket(
        "make-believe-soup",
        "Make-Believe Soup",
        True,
        [
            {
                "id": "storybook-soup",
                "name": "Old soup name",
                "count": 2,
                "price": 1,
                "substitution_settings": {"is_allowed": False},
                "options": [
                    {"id": "spice-choice", "values": [{"id": "mild", "count": 2}]}
                ],
            }
        ],
    )

    class FakeClient:
        def get_baskets_page(
            self, latitude: float, longitude: float
        ) -> dict[str, object]:
            return {"baskets": [saved_basket]}

        def get_assortment(self, slug: str) -> dict[str, object]:
            assert slug == "make-believe-soup"
            return _assortment()

        def get_venue_static(self, slug: str) -> dict[str, object]:
            assert slug == "make-believe-soup"
            return {"venue": {"currency": "EUR"}}

    assert view_basket_module.view_basket(
        {"slug": "make-believe-soup"}, FakeClient()
    ) == {
        "restaurant_name": "Make-Believe Soup",
        "slug": "make-believe-soup",
        "item_count": 1,
        "available": True,
        "items": [
            {
                "name": "Current Storybook Soup",
                "count": 2,
                "options": [{"name": "Mild pretend spice", "count": 2}],
                "line_price": "19.00 EUR",
            }
        ],
        "total": "19.00 EUR",
    }


def test_slug_without_a_saved_basket_is_not_an_error(
    view_basket_module: object,
) -> None:
    class FakeClient:
        def get_baskets_page(
            self, latitude: float, longitude: float
        ) -> dict[str, object]:
            return {"baskets": []}

        def get_assortment(self, slug: str) -> dict[str, object]:
            raise AssertionError("a missing basket must not fetch an assortment")

    assert view_basket_module.view_basket({"slug": "absent-cafe"}, FakeClient()) == {
        "slug": "absent-cafe",
        "has_basket": False,
    }


def test_slug_mode_propagates_actionable_broken_basket_error(
    view_basket_module: object,
) -> None:
    saved_basket = _saved_basket(
        "gone-grill",
        "Gone Grill",
        False,
        [
            {
                "id": "removed-item",
                "name": "Discontinued fake burger",
                "count": 1,
                "price": 500,
                "substitution_settings": {"is_allowed": False},
                "options": [],
            }
        ],
    )

    class FakeClient:
        def get_baskets_page(
            self, latitude: float, longitude: float
        ) -> dict[str, object]:
            return {"baskets": [saved_basket]}

        def get_assortment(self, slug: str) -> dict[str, object]:
            return {
                "assortment_id": "gone-grill-assortment",
                "available_languages": ["en"],
                "categories": [],
                "compliance_info": {},
                "items": [],
                "loading_strategy": "eager",
                "options": [],
                "primary_language": "en",
                "selected_language": "en",
                "variant_groups": [],
            }

    with pytest.raises(
        ValueError,
        match="Discontinued fake burger.*empty it in the Wolt app",
    ):
        view_basket_module.view_basket({"slug": "gone-grill"}, FakeClient())


def _saved_basket(
    slug: str, name: str, available: bool, items: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "venue": {
            "available": available,
            "city_slug": "helsinki",
            "country": "FI",
            "delivery_status": "available",
            "id": f"{slug}-id",
            "image": {"url": "https://example.test/venue.jpg"},
            "language": "en",
            "name": name,
            "open_status": "open",
            "product_line": "restaurant",
            "slug": slug,
        },
        "items": items,
    }


def _assortment() -> dict[str, object]:
    return {
        "assortment_id": "make-believe-soup-assortment",
        "available_languages": ["en"],
        "items": [
            {
                "id": "storybook-soup",
                "name": [{"lang": "en", "value": "Current Storybook Soup"}],
                "price": 700,
                "options": [{"id": "spice-choice", "option_id": "spices"}],
                "restrictions": [],
                "alcohol_permille": 0,
                "product_hierarchy_tags": ["pretend-soup"],
                "vat_percentage": 14,
                "vat_percentage_decimal": 14.0,
            }
        ],
        "compliance_info": {},
        "loading_strategy": "eager",
        "options": [
            {
                "id": "spices",
                "values": [
                    {
                        "id": "mild",
                        "name": [{"lang": "en", "value": "Mild pretend spice"}],
                        "price": 125,
                    }
                ],
            }
        ],
        "categories": [{"id": "soups", "item_ids": ["storybook-soup"]}],
        "primary_language": "en",
        "selected_language": "en",
        "variant_groups": [],
    }
