import importlib.util
from pathlib import Path

import pytest

import wolt_client


@pytest.fixture
def empty_basket_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "empty_basket" / "run.py"
    spec = importlib.util.spec_from_file_location("empty_basket_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "configured_location", lambda: (12.3, 45.6))
    return module


class FakeClient:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.calls: list[str] = []
        self.deleted_basket_ids: list[list[str]] = []

    def get_baskets_page(self, latitude: float, longitude: float) -> dict[str, object]:
        assert (latitude, longitude) == (12.3, 45.6)
        self.calls.append("get_baskets_page")
        return self.pages.pop(0)

    def delete_baskets(self, basket_ids: list[str]) -> None:
        self.calls.append("delete_baskets")
        self.deleted_basket_ids.append(basket_ids)


def test_deletes_a_matching_basket_and_confirms_it_is_gone(
    empty_basket_module: object,
) -> None:
    client = FakeClient(
        [
            {
                "baskets": [
                    _saved_basket("basket-1", "pretend-noodles", "Pretend Noodles")
                ]
            },
            {"baskets": []},
        ]
    )

    assert empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client) == {
        "slug": "pretend-noodles",
        "restaurant_name": "Pretend Noodles",
        "has_basket": True,
        "deleted_count": 1,
    }
    assert client.calls == [
        "get_baskets_page",
        "delete_baskets",
        "get_baskets_page",
    ]
    assert client.deleted_basket_ids == [["basket-1"]]


def test_missing_basket_is_a_success_without_a_delete(
    empty_basket_module: object,
) -> None:
    client = FakeClient(
        [{"baskets": [_saved_basket("basket-1", "other-cafe", "Other Cafe")]}]
    )

    assert empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client) == {
        "slug": "pretend-noodles",
        "has_basket": False,
        "deleted_count": 0,
    }
    assert client.calls == ["get_baskets_page"]
    assert client.deleted_basket_ids == []


def test_malformed_first_baskets_page_raises_without_a_delete(
    empty_basket_module: object,
) -> None:
    client = FakeClient([{}])

    with pytest.raises(ValueError, match="baskets page could not be read"):
        empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client)

    assert client.calls == ["get_baskets_page"]
    assert client.deleted_basket_ids == []


def test_deletes_all_baskets_with_the_same_slug_in_one_call(
    empty_basket_module: object,
) -> None:
    client = FakeClient(
        [
            {
                "baskets": [
                    _saved_basket("basket-1", "pretend-noodles", "Pretend Noodles"),
                    _saved_basket("basket-2", "pretend-noodles", "Pretend Noodles"),
                    _saved_basket("basket-3", "other-cafe", "Other Cafe"),
                ]
            },
            {"baskets": [_saved_basket("basket-3", "other-cafe", "Other Cafe")]},
        ]
    )

    result = empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client)

    assert result["deleted_count"] == 2
    assert client.deleted_basket_ids == [["basket-1", "basket-2"]]


def test_failed_delete_verification_raises_an_error(
    empty_basket_module: object,
) -> None:
    saved_basket = _saved_basket("basket-1", "pretend-noodles", "Pretend Noodles")
    client = FakeClient([{"baskets": [saved_basket]}, {"baskets": [saved_basket]}])

    with pytest.raises(ValueError, match="did not delete.*still present"):
        empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client)

    assert client.deleted_basket_ids == [["basket-1"]]


def test_malformed_verification_page_raises_after_a_delete(
    empty_basket_module: object,
) -> None:
    saved_basket = _saved_basket("basket-1", "pretend-noodles", "Pretend Noodles")
    client = FakeClient(
        [
            {"baskets": [saved_basket]},
            {},
        ]
    )

    with pytest.raises(ValueError, match="deletion could not be confirmed"):
        empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client)

    assert client.calls == [
        "get_baskets_page",
        "delete_baskets",
        "get_baskets_page",
    ]
    assert client.deleted_basket_ids == [["basket-1"]]


def test_invalid_saved_basket_id_is_not_sent_to_wolt(
    empty_basket_module: object,
) -> None:
    client = FakeClient(
        [{"baskets": [_saved_basket("", "pretend-noodles", "Pretend Noodles")]}]
    )

    with pytest.raises(ValueError, match="Saved basket ID is invalid"):
        empty_basket_module.empty_basket({"slug": "pretend-noodles"}, client)

    assert client.calls == ["get_baskets_page"]
    assert client.deleted_basket_ids == []


@pytest.mark.parametrize("params", [{}, {"slug": ""}, {"slug": ["pretend-noodles"]}])
def test_invalid_slug_is_rejected_before_any_client_call(
    empty_basket_module: object, params: dict[str, object]
) -> None:
    client = FakeClient([])

    with pytest.raises(ValueError, match="slug must be a non-empty restaurant slug"):
        empty_basket_module.empty_basket(params, client)

    assert client.calls == []
    assert client.deleted_basket_ids == []


def _saved_basket(basket_id: str, slug: str, name: str) -> dict[str, object]:
    return {
        "id": basket_id,
        "venue": {"slug": slug, "name": name},
    }
