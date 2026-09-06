import importlib.util
from pathlib import Path

import pytest
from woltapi import DeliveryTarget

import wolt_client


@pytest.fixture
def list_delivery_addresses_module(monkeypatch: pytest.MonkeyPatch):
    """Load the tool module without running its command-line entrypoint."""
    monkeypatch.setattr(wolt_client, "main", lambda handler: None)
    module_path = Path(__file__).parent / "list_delivery_addresses" / "run.py"
    spec = importlib.util.spec_from_file_location(
        "list_delivery_addresses_run", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_delivery_addresses_use_alias_or_label_type(
    list_delivery_addresses_module: object,
) -> None:
    class FakeClient:
        def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
            return (
                DeliveryTarget(
                    id="fake-home-id",
                    alias="Home",
                    label_type="home",
                    address="123 Example Street",
                    city="Faketown",
                    postcode="00000",
                ),
                DeliveryTarget(
                    id="fake-work-id",
                    alias=None,
                    label_type="Work",
                    address="45 Fictional Avenue",
                    city="Testville",
                    postcode="99999",
                ),
            )

    result = list_delivery_addresses_module.list_delivery_addresses({}, FakeClient())

    assert result == {
        "addresses": [
            {
                "id": "fake-home-id",
                "alias": "Home",
                "address": "123 Example Street",
                "city": "Faketown",
                "postcode": "00000",
            },
            {
                "id": "fake-work-id",
                "alias": "Work",
                "address": "45 Fictional Avenue",
                "city": "Testville",
                "postcode": "99999",
            },
        ]
    }


def test_delivery_addresses_are_empty_when_none_are_saved(
    list_delivery_addresses_module: object,
) -> None:
    class FakeClient:
        def list_delivery_targets(self) -> tuple[DeliveryTarget, ...]:
            return ()

    result = list_delivery_addresses_module.list_delivery_addresses({}, FakeClient())

    assert result == {"addresses": []}
