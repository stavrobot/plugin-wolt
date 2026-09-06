import importlib.util
from pathlib import Path

import pytest

import wolt_client


@pytest.fixture
def get_item_options_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "get_item_options" / "run.py"
    spec = importlib.util.spec_from_file_location("get_item_options_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def get_assortment(self, slug: str) -> dict[str, object]:
        assert slug == "test-venue"
        return {
            "items": [
                {"id": "plain-item", "options": []},
                {
                    "id": "configured-item",
                    "options": [
                        _configuration("quantity", "extras", minimum=1, maximum=2),
                        {
                            **_configuration("conditional", "extras"),
                            "prerequisite_values": ["other-value"],
                        },
                        {
                            **_configuration("free", "extras"),
                            "multi_choice_config": {
                                "total_range": {"min": 0, "max": 1},
                                "max_single_selections": 1,
                                "free_selections": 1,
                            },
                        },
                        _configuration("unsupported-type", "unsupported-root"),
                        {
                            **_configuration("bad-constraints", "extras"),
                            "multi_choice_config": {
                                "total_range": {"min": "one", "max": 1},
                                "max_single_selections": 1,
                                "free_selections": 0,
                            },
                        },
                        _configuration("missing-root", "not-in-assortment"),
                    ],
                },
            ],
            "options": [
                {
                    "id": "extras",
                    "type": "multi_choice",
                    "values": [
                        {
                            "id": "caramel",
                            "name": [{"lang": "en", "value": "caramel syrup"}],
                            "price": 30,
                        }
                    ],
                },
                {"id": "unsupported-root", "type": "text", "values": []},
            ],
        }

    def get_venue_static(self, slug: str) -> dict[str, object]:
        assert slug == "test-venue"
        return {"venue": {"currency": "EUR"}}


def _configuration(
    configuration_id: str,
    option_id: str,
    *,
    minimum: int = 0,
    maximum: int = 1,
) -> dict[str, object]:
    return {
        "id": configuration_id,
        "option_id": option_id,
        "name": "Extras",
        "prerequisite_values": [],
        "multi_choice_config": {
            "total_range": {"min": minimum, "max": maximum},
            "max_single_selections": 1,
            "free_selections": 0,
        },
    }


def test_get_item_options_formats_values_and_marks_unsupported_configurations(
    get_item_options_module: object,
) -> None:
    result = get_item_options_module.get_item_options(
        {"slug": "test-venue", "item_id": "configured-item"}, FakeClient()
    )

    assert result == {
        "options": [
            {
                "id": "quantity",
                "name": "Extras",
                "required": True,
                "total_range": {"min": 1, "max": 2},
                "max_single_selections": 1,
                "values": [
                    {"id": "caramel", "name": "caramel syrup", "price": "0.30 EUR"}
                ],
                "unsupported": False,
            },
            {
                "id": "conditional",
                "name": "Extras",
                "required": False,
                "total_range": {"min": 0, "max": 1},
                "max_single_selections": 1,
                "values": [
                    {"id": "caramel", "name": "caramel syrup", "price": "0.30 EUR"}
                ],
                "unsupported": True,
                "unsupported_reason": "Conditional options are unsupported.",
            },
            {
                "id": "free",
                "name": "Extras",
                "required": False,
                "total_range": {"min": 0, "max": 1},
                "max_single_selections": 1,
                "values": [
                    {"id": "caramel", "name": "caramel syrup", "price": "0.30 EUR"}
                ],
                "unsupported": True,
                "unsupported_reason": "Free-selection pricing is unsupported.",
            },
            {
                "id": "unsupported-type",
                "name": "Extras",
                "required": False,
                "total_range": {"min": 0, "max": 1},
                "max_single_selections": 1,
                "values": [],
                "unsupported": True,
                "unsupported_reason": "The root option type is unsupported.",
            },
            {
                "id": "bad-constraints",
                "name": "Extras",
                "required": None,
                "total_range": {"min": None, "max": None},
                "max_single_selections": None,
                "values": [
                    {"id": "caramel", "name": "caramel syrup", "price": "0.30 EUR"}
                ],
                "unsupported": True,
                "unsupported_reason": "Option selection constraints are unsupported.",
            },
            {
                "id": "missing-root",
                "name": "Extras",
                "required": False,
                "total_range": {"min": 0, "max": 1},
                "max_single_selections": 1,
                "values": [],
                "unsupported": True,
                "unsupported_reason": "The referenced root option is missing from the assortment.",
            },
        ]
    }


def test_get_item_options_handles_plain_items_and_invalid_ids(
    get_item_options_module: object,
) -> None:
    assert get_item_options_module.get_item_options(
        {"slug": "test-venue", "item_id": "plain-item"}, FakeClient()
    ) == {"options": []}

    with pytest.raises(ValueError, match="Call get_menu to get valid item IDs"):
        get_item_options_module.get_item_options(
            {"slug": "test-venue", "item_id": "not-on-menu"}, FakeClient()
        )


def test_non_object_params_are_rejected_before_fetching_options(
    get_item_options_module: object,
) -> None:
    with pytest.raises(ValueError, match="params must be an object"):
        get_item_options_module.get_item_options([], object())
