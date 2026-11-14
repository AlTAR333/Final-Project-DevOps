"""Planted-bug regression test for the API layer (owner: Armand). No database needed.

This is the red-to-green demonstration for the API. The scenario, end to end through HTTP:

  * The contract says quantity is an integer from 1 to 20 INCLUSIVE.
  * `scripts/planted_bug_quantity.patch` introduces a classic off-by-one in
    api/validation.py (`<= QUANTITY_MAX` becomes `< QUANTITY_MAX`): quantity 20 is then
    wrongly refused with 422.
  * These tests fail with the bug planted (red) and pass once it is repaired (green).

Run the whole demonstration with:  bash scripts/red_to_green_api.sh
"""

import json

import pytest

from api import orders
from api.app import create_app
from common.models import PlaceOrderResult

ORDER_ID = "0d9674de-7fac-4c13-bb2f-c4bcbaf743da"


class FakeConn:
    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        orders, "place_order", lambda *a: PlaceOrderResult(order_id=ORDER_ID, replayed=False)
    )
    return create_app(connect=FakeConn).test_client()


def post(client, quantity):
    payload = {"customer_id": "CUST-042", "items": [{"sku": "KIT-100", "quantity": quantity}]}
    return client.post(
        "/api/v1/orders",
        data=json.dumps(payload),
        headers={"Idempotency-Key": "planted-bug-key-1"},
    )


@pytest.mark.parametrize("quantity", [1, 2, 19, 20])
def test_quantities_from_1_to_20_are_accepted(client, quantity):
    response = post(client, quantity)
    assert response.status_code == 202, response.get_json()
    assert response.get_json() == {"order_id": ORDER_ID, "status": "queued"}


@pytest.mark.parametrize("quantity", [0, -1, 21, 100])
def test_quantities_outside_1_to_20_are_rejected(client, quantity):
    response = post(client, quantity)
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "INVALID_QUANTITY"
