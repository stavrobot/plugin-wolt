import importlib.util
from pathlib import Path

import pytest
from woltapi import VenueCheckoutContext

import wolt_client


def _saved_item(
    item_id: str, count: int, spice: str | None = None
) -> dict[str, object]:
    options: list[dict[str, object]] = []
    if spice is not None:
        options = [
            {
                "id": "pretend-spice-choice",
                "values": [{"id": spice, "count": 1}],
            }
        ]
    return {
        "id": item_id,
        "name": item_id,
        "count": count,
        "price": 100,
        "substitution_settings": {"is_allowed": False},
        "options": options,
    }


@pytest.fixture
def update_basket_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "update_basket" / "run.py"
    spec = importlib.util.spec_from_file_location("update_basket_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_location", lambda: (12.3, 45.6))
    return module


class FakeClient:
    def __init__(
        self,
        saved_items: list[dict[str, object]] | None,
        venue_id: str = "pretend-venue",
    ) -> None:
        self.calls: list[str] = []
        self.saved_items: list[tuple[object, ...]] = []
        self.venue_id = venue_id
        self.page = {
            "baskets": []
            if saved_items is None
            else [_saved_basket("pretend-noodles", saved_items)]
        }

    def get_baskets_page(self, latitude: float, longitude: float) -> dict[str, object]:
        assert (latitude, longitude) == (12.3, 45.6)
        self.calls.append("get_baskets_page")
        return self.page

    def get_assortment(self, slug: str) -> dict[str, object]:
        assert slug == "pretend-noodles"
        self.calls.append("get_assortment")
        return _assortment()

    def get_venue_checkout_context(self, slug: str) -> VenueCheckoutContext:
        assert slug == "pretend-noodles"
        self.calls.append("get_venue_checkout_context")
        return VenueCheckoutContext(self.venue_id, "FI", "EUR", False, None)

    def save_basket_items(
        self,
        assortment: dict[str, object],
        *,
        venue: VenueCheckoutContext,
        items: tuple[object, ...],
    ) -> None:
        assert assortment == _assortment()
        assert venue.currency == "EUR"
        self.calls.append("save_basket_items")
        self.saved_items.append(items)


@pytest.mark.parametrize(
    ("params", "saved_items", "expected_ids", "expected_counts", "expected_options"),
    [
        (
            {"action": "add", "item_id": "fake-dumplings", "count": 2},
            [_saved_item("fake-noodles", 1, "mild")],
            ["fake-noodles", "fake-dumplings"],
            [1, 2],
            [[("pretend-spice-choice", (("mild", 1),))], []],
        ),
        (
            {"action": "set_count", "item_id": "fake-noodles", "count": 3},
            [_saved_item("fake-noodles", 1, "mild")],
            ["fake-noodles"],
            [3],
            [[("pretend-spice-choice", (("mild", 1),))]],
        ),
        (
            {
                "action": "set_options",
                "item_id": "fake-noodles",
                "option_selections": [
                    {
                        "configuration_id": "pretend-spice-choice",
                        "values": [{"id": "hot", "count": 1}],
                    }
                ],
            },
            [_saved_item("fake-noodles", 1)],
            ["fake-noodles"],
            [1],
            [[("pretend-spice-choice", (("hot", 1),))]],
        ),
        (
            {"action": "remove", "item_id": "fake-dumplings"},
            [_saved_item("fake-noodles", 1, "mild"), _saved_item("fake-dumplings", 2)],
            ["fake-noodles"],
            [1],
            [[("pretend-spice-choice", (("mild", 1),))]],
        ),
    ],
)
def test_each_action_saves_and_returns_the_local_basket(
    update_basket_module: object,
    params: dict[str, object],
    saved_items: list[dict[str, object]],
    expected_ids: list[str],
    expected_counts: list[int],
    expected_options: list[list[tuple[str, tuple[tuple[str, int], ...]]]],
) -> None:
    client = FakeClient(saved_items)

    result = update_basket_module.update_basket(
        {"slug": "pretend-noodles", **params}, client
    )

    assert client.calls == [
        "get_baskets_page",
        "get_assortment",
        "get_venue_checkout_context",
        "save_basket_items",
    ]
    saved = client.saved_items[0]
    assert [item.id for item in saved] == expected_ids
    assert [item.count for item in saved] == expected_counts
    assert [_selection_options(item) for item in saved] == expected_options
    assert [item["count"] for item in result["items"]] == expected_counts
    if params["action"] == "set_options":
        assert result["items"][0]["options"] == [{"name": "Hot", "count": 1}]


@pytest.mark.parametrize(
    ("params", "saved_items", "message"),
    [
        (
            {"action": "add", "item_id": "fake-noodles", "count": 1},
            [_saved_item("fake-noodles", 2, "mild")],
            r"already in the basket with count 2 and options pretend-spice-choice=\[mild x1\]\. Use set_count",
        ),
        (
            {"action": "add", "item_id": "fake-wine", "count": 1},
            [_saved_item("fake-wine", 2)],
            r"already in the basket with count 2 and options no options\. Use set_count",
        ),
        (
            {"action": "add", "item_id": "restricted-fake-roll", "count": 1},
            [_saved_item("fake-noodles", 1)],
            "has restrictions, so it cannot be added. Choose a different item from get_menu",
        ),
        (
            {"action": "add", "item_id": "fake-wine", "count": 1},
            [_saved_item("fake-noodles", 1)],
            "contains alcohol, so it cannot be added. Choose a different item from get_menu",
        ),
        (
            {"action": "remove", "item_id": "fake-noodles"},
            [_saved_item("fake-noodles", 1)],
            "last item in the basket. Use empty_basket to delete the whole basket",
        ),
        (
            {"action": "set_count", "item_id": "fake-dumplings", "count": 2},
            [_saved_item("fake-noodles", 1)],
            "is not in the basket. Use view_basket to see current items or add to add it",
        ),
        (
            {
                "action": "set_options",
                "item_id": "fake-dumplings",
                "option_selections": [],
            },
            [_saved_item("fake-noodles", 1)],
            "is not in the basket. Use view_basket to see current items or add to add it",
        ),
        (
            {"action": "remove", "item_id": "fake-dumplings"},
            [_saved_item("fake-noodles", 1)],
            "is not in the basket. Use view_basket to see current items or add to add it",
        ),
        (
            {
                "action": "set_options",
                "item_id": "fake-noodles",
                "option_selections": [
                    {
                        "configuration_id": "pretend-spice-choice",
                        "values": [{"id": "not-a-pretend-spice", "count": 1}],
                    }
                ],
            },
            [_saved_item("fake-noodles", 1)],
            "Cannot set_options 'Fake Noodles'.*selected option value is absent.*Choose a permitted count or option selection",
        ),
    ],
)
def test_refusals_do_not_save_an_existing_basket(
    update_basket_module: object,
    params: dict[str, object],
    saved_items: list[dict[str, object]],
    message: str,
) -> None:
    client = FakeClient(saved_items)

    with pytest.raises(ValueError, match=message):
        update_basket_module.update_basket(
            {"slug": "pretend-noodles", **params}, client
        )

    assert client.saved_items == []
    assert "save_basket_items" not in client.calls


@pytest.mark.parametrize("action", ["set_count", "set_options", "remove"])
def test_existing_basket_actions_require_a_saved_basket(
    update_basket_module: object, action: str
) -> None:
    client = FakeClient(None)
    params: dict[str, object] = {
        "slug": "pretend-noodles",
        "action": action,
        "item_id": "fake-noodles",
    }
    if action == "set_count":
        params["count"] = 1
    if action == "set_options":
        params["option_selections"] = []

    with pytest.raises(ValueError, match="has no saved basket. Use add first"):
        update_basket_module.update_basket(params, client)

    assert client.saved_items == []
    assert "save_basket_items" not in client.calls


@pytest.mark.parametrize(
    ("params", "message"),
    [
        (
            {"slug": "pretend-noodles", "action": "replace", "item_id": "fake-noodles"},
            "action must be one of: add, set_count, set_options, or remove",
        ),
        (
            {
                "slug": "pretend-noodles",
                "action": ["add"],
                "item_id": "fake-noodles",
            },
            "action must be one of: add, set_count, set_options, or remove",
        ),
        (
            {
                "slug": "pretend-noodles",
                "action": "add",
                "item_id": "fake-noodles",
                "count": 1,
                "option_selections": {"not": "a list"},
            },
            "option_selections must be a list of objects",
        ),
        (
            {
                "slug": "pretend-noodles",
                "action": "add",
                "item_id": "missing",
                "count": 1,
            },
            "is not in this restaurant's assortment. Call get_menu for valid item IDs",
        ),
    ],
)
def test_invalid_requests_do_not_save(
    update_basket_module: object, params: dict[str, object], message: str
) -> None:
    client = FakeClient([_saved_item("fake-noodles", 1)])

    with pytest.raises(ValueError, match=message):
        update_basket_module.update_basket(params, client)

    assert client.saved_items == []
    assert "save_basket_items" not in client.calls


def test_non_object_params_do_not_save(update_basket_module: object) -> None:
    client = FakeClient([_saved_item("fake-noodles", 1)])

    with pytest.raises(ValueError, match="params must be an object"):
        update_basket_module.update_basket([], client)

    assert client.calls == []
    assert client.saved_items == []


@pytest.mark.parametrize(
    ("page", "message"),
    [
        ({"baskets": {}}, "baskets page could not be read; no change was made"),
        (
            {
                "baskets": [
                    {"venue": {"slug": "pretend-noodles"}},
                    {"venue": {"slug": "pretend-noodles"}},
                ]
            },
            "More than one saved basket matches this restaurant; no change was made",
        ),
    ],
)
def test_unreadable_or_ambiguous_baskets_page_does_not_save(
    update_basket_module: object, page: dict[str, object], message: str
) -> None:
    client = FakeClient(None)
    client.page = page

    with pytest.raises(ValueError, match=message):
        update_basket_module.update_basket(
            {
                "slug": "pretend-noodles",
                "action": "add",
                "item_id": "fake-dumplings",
                "count": 1,
            },
            client,
        )

    assert client.calls == ["get_baskets_page"]
    assert client.saved_items == []


def test_venue_mismatch_does_not_save(update_basket_module: object) -> None:
    client = FakeClient([_saved_item("fake-noodles", 1)], venue_id="different-venue")

    with pytest.raises(
        ValueError,
        match="Saved basket venue does not match the requested restaurant; no change was made",
    ):
        update_basket_module.update_basket(
            {
                "slug": "pretend-noodles",
                "action": "set_count",
                "item_id": "fake-noodles",
                "count": 2,
            },
            client,
        )

    assert "save_basket_items" not in client.calls
    assert client.saved_items == []


def test_save_failure_does_not_name_requested_item(
    update_basket_module: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient([_saved_item("fake-noodles", 1)])

    def reject_save(*args: object, **kwargs: object) -> None:
        raise update_basket_module.SelectionError("another basket item is invalid")

    monkeypatch.setattr(client, "save_basket_items", reject_save)

    with pytest.raises(
        ValueError,
        match="Wolt rejected the basket because another basket item is invalid. The cause may be another item already in the basket",
    ) as error:
        update_basket_module.update_basket(
            {
                "slug": "pretend-noodles",
                "action": "set_count",
                "item_id": "fake-noodles",
                "count": 2,
            },
            client,
        )

    assert "Fake Noodles" not in str(error.value)


def _selection_options(item: object) -> list[tuple[str, tuple[tuple[str, int], ...]]]:
    return [
        (
            option.configuration_id,
            tuple((value.id, value.count) for value in option.values),
        )
        for option in item.options
    ]


def _saved_basket(slug: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "venue": {
            "id": "pretend-venue",
            "name": "Pretend Noodles",
            "slug": slug,
            "country": "FI",
            "available": True,
        },
        "items": items,
    }


def _assortment() -> dict[str, object]:
    return {
        "items": [
            _item("fake-noodles", "Fake Noodles", 700, options=True),
            _item("fake-dumplings", "Fake Dumplings", 500),
            _item(
                "restricted-fake-roll",
                "Restricted Fake Roll",
                600,
                restrictions=["age"],
            ),
            _item("fake-wine", "Fake Wine", 800, alcohol_permille=120),
        ],
        "options": [
            {
                "id": "pretend-spices",
                "type": "multi_choice",
                "values": [
                    {
                        "id": "mild",
                        "name": [{"lang": "en", "value": "Mild"}],
                        "price": 0,
                    },
                    {
                        "id": "hot",
                        "name": [{"lang": "en", "value": "Hot"}],
                        "price": 50,
                    },
                ],
            }
        ],
        "categories": [
            {
                "id": "pretend-main-dishes",
                "item_ids": [
                    "fake-noodles",
                    "fake-dumplings",
                    "restricted-fake-roll",
                    "fake-wine",
                ],
            }
        ],
    }


def _item(
    item_id: str,
    name: str,
    price: int,
    *,
    options: bool = False,
    restrictions: list[str] | None = None,
    alcohol_permille: int = 0,
) -> dict[str, object]:
    return {
        "id": item_id,
        "name": [{"lang": "en", "value": name}],
        "price": price,
        "options": [{"id": "pretend-spice-choice", "option_id": "pretend-spices"}]
        if options
        else [],
        "restrictions": restrictions or [],
        "alcohol_permille": alcohol_permille,
        "product_hierarchy_tags": [],
        "vat_percentage": 14,
        "vat_percentage_decimal": 14.0,
    }
