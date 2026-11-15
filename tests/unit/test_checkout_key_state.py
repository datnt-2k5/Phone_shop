
"""Unit tests for Task 52 checkout key lifecycle."""

from copy import deepcopy
from uuid import UUID

import pytest

from models.app_error import AppError
from ui.checkout_key_state import (
    CHECKOUT_HASH,
    CHECKOUT_KEY,
    CheckoutKeyState,
)


class FakeSession:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


def valid_payload():
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "",
        "items": [
            {"product_id": 12, "quantity": 2},
            {"product_id": 5, "quantity": 1},
        ],
    }


def test_initial_checkout_creates_uuid4():
    session = FakeSession()
    state = CheckoutKeyState(session)

    result = state.prepare(valid_payload())

    assert UUID(result["idempotency_key"]).version == 4
    assert session.get(CHECKOUT_KEY) == result["idempotency_key"]
    assert len(session.get(CHECKOUT_HASH)) == 64


def test_retry_same_payload_keeps_key():
    state = CheckoutKeyState(FakeSession())

    first = state.prepare(valid_payload())
    second = state.prepare(valid_payload())

    assert first["idempotency_key"] == second["idempotency_key"]


def test_reordered_cart_keeps_same_key():
    state = CheckoutKeyState(FakeSession())
    first = state.prepare(valid_payload())

    changed = valid_payload()
    changed["items"].reverse()

    second = state.prepare(changed)

    assert first["idempotency_key"] == second["idempotency_key"]


def test_quantity_change_creates_new_key():
    state = CheckoutKeyState(FakeSession())
    first = state.prepare(valid_payload())

    changed = valid_payload()
    changed["items"][0]["quantity"] = 3

    second = state.prepare(changed)

    assert first["idempotency_key"] != second["idempotency_key"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("receiver_name", "Nguyen Van B"),
        ("receiver_phone", "0987654321"),
        ("receiver_address", "Da Nang"),
        ("note", "Giao buoi sang"),
    ],
)
def test_receiver_change_creates_new_key(field, value):
    state = CheckoutKeyState(FakeSession())
    first = state.prepare(valid_payload())

    changed = valid_payload()
    changed[field] = value

    second = state.prepare(changed)

    assert first["idempotency_key"] != second["idempotency_key"]


def test_normalized_whitespace_keeps_key():
    state = CheckoutKeyState(FakeSession())
    first = state.prepare(valid_payload())

    changed = valid_payload()
    changed["receiver_name"] = " Nguyen  Van  A "

    second = state.prepare(changed)

    assert first["idempotency_key"] == second["idempotency_key"]


def test_invalid_request_does_not_replace_key():
    session = FakeSession()
    state = CheckoutKeyState(session)

    original = state.prepare(valid_payload())
    original_hash = session.get(CHECKOUT_HASH)

    invalid = valid_payload()
    invalid["items"] = []

    with pytest.raises(AppError):
        state.prepare(invalid)

    assert session.get(CHECKOUT_KEY) == original["idempotency_key"]
    assert session.get(CHECKOUT_HASH) == original_hash


def test_original_payload_is_unchanged():
    state = CheckoutKeyState(FakeSession())
    payload = valid_payload()
    original = deepcopy(payload)

    state.prepare(payload)

    assert payload == original
    assert "idempotency_key" not in payload


def test_success_clears_key_and_hash():
    session = FakeSession()
    state = CheckoutKeyState(session)

    state.prepare(valid_payload())
    state.clear()

    assert session.get(CHECKOUT_KEY) is None
    assert session.get(CHECKOUT_HASH) is None


def test_new_checkout_after_success_uses_new_key():
    state = CheckoutKeyState(FakeSession())

    first = state.prepare(valid_payload())
    state.clear()
    second = state.prepare(valid_payload())

    assert first["idempotency_key"] != second["idempotency_key"]


def test_invalid_stored_key_is_replaced():
    session = FakeSession()
    session.set(CHECKOUT_KEY, "invalid-key")

    result = CheckoutKeyState(session).prepare(valid_payload())

    assert UUID(result["idempotency_key"]).version == 4
