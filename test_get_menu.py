import importlib.util
from pathlib import Path

import pytest

import wolt_client


@pytest.fixture
def get_menu_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "get_menu" / "run.py"
    spec = importlib.util.spec_from_file_location("get_menu_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_menu_items_include_basket_selection_fields(get_menu_module: object) -> None:
    class FakeClient:
        def get_assortment(self, slug: str) -> dict[str, object]:
            assert slug == "test-venue"
            return {
                "items": [
                    {
                        "id": "plain-item",
                        "name": "Plain item",
                        "description": "No options or restrictions",
                        "price": 1099,
                        "options": [],
                        "restrictions": [],
                        "alcohol_permille": 0,
                    },
                    {
                        "id": "configured-item",
                        "name": "Configured item",
                        "price": 1299,
                        "options": [{"id": "size"}],
                        "restrictions": [{"type": "age"}],
                        "alcohol_permille": 0,
                    },
                    {
                        "id": "alcoholic-item",
                        "name": "Alcoholic item",
                        "price": 699,
                        "options": [],
                        "restrictions": [],
                        "alcohol_permille": 45,
                    },
                ]
            }

        def get_venue_static(self, slug: str) -> dict[str, object]:
            assert slug == "test-venue"
            return {"venue": {"currency": "EUR"}}

    result = get_menu_module.get_menu({"slug": "test-venue"}, FakeClient())

    assert result == {
        "total": 3,
        "items": [
            {
                "id": "plain-item",
                "name": "Plain item",
                "description": "No options or restrictions",
                "price": "10.99 EUR",
                "has_options": False,
                "is_restricted_or_alcoholic": False,
            },
            {
                "id": "configured-item",
                "name": "Configured item",
                "price": "12.99 EUR",
                "has_options": True,
                "is_restricted_or_alcoholic": True,
            },
            {
                "id": "alcoholic-item",
                "name": "Alcoholic item",
                "price": "6.99 EUR",
                "has_options": False,
                "is_restricted_or_alcoholic": True,
            },
        ],
    }


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"slug": "test-venue", "filter": 1}, "filter must be a string"),
        ({"slug": "test-venue", "limit": True}, "limit must be a positive integer"),
    ],
)
def test_invalid_filter_or_limit_is_rejected_before_fetching_menu(
    get_menu_module: object, params: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        get_menu_module.get_menu(params, object())
