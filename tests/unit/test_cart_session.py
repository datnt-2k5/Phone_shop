
"""Task 48 / US09-T01: cart session rules and isolation."""

import pytest

from models.app_error import AppError
from services.auth_session import (
    CART_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    SESSION_KEYS_TO_CLEAR,
)
from services.cart_session import MAX_CART_LINES, CartSession


class FakeStore:
    def __init__(self):
        self.data = {}
        self.writes = 0

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.writes += 1

    def remove(self, key):
        self.data.pop(key, None)


@pytest.fixture
def env():
    store = FakeStore()
    cart = CartSession(store)
    return cart, store


def test_new_cart_is_empty(env):
    cart, store = env

    assert cart.items() == []
    assert cart.line_count() == 0
    assert cart.total_quantity() == 0
    assert store.data == {}


def test_add_one_product(env):
    cart, _ = env

    result = cart.add(10)

    assert result == [
        {"product_id": 10, "quantity": 1}
    ]


def test_add_existing_product_increases_quantity(env):
    cart, _ = env

    cart.add(10)
    cart.add(10)

    assert cart.items() == [
        {"product_id": 10, "quantity": 2}
    ]
    assert cart.line_count() == 1


def test_add_custom_quantity(env):
    cart, _ = env

    cart.add(10, 3)
    cart.add(10, 2)

    assert cart.items()[0]["quantity"] == 5


def test_two_different_products_create_two_lines(env):
    cart, _ = env

    cart.add(10)
    cart.add(20, 3)

    assert cart.line_count() == 2
    assert cart.total_quantity() == 4


def test_cart_rejects_more_than_twenty_lines(env):
    cart, _ = env

    for product_id in range(1, MAX_CART_LINES + 1):
        cart.add(product_id)

    assert cart.line_count() == 20

    with pytest.raises(AppError) as caught:
        cart.add(21)

    assert caught.value.error_code == "CART_LIMIT_EXCEEDED"
    assert cart.line_count() == 20
    assert not cart.has_product(21)


def test_existing_product_can_increase_at_limit(env):
    cart, _ = env

    for product_id in range(1, 21):
        cart.add(product_id)

    cart.add(5, 2)

    assert cart.line_count() == 20
    assert cart.total_quantity() == 22


def test_update_quantity(env):
    cart, _ = env

    cart.add(10)
    cart.set_quantity(10, 7)

    assert cart.items()[0]["quantity"] == 7


def test_setting_same_quantity_does_not_write(env):
    cart, store = env

    cart.add(10, 2)
    writes_before = store.writes

    cart.set_quantity(10, 2)

    assert store.writes == writes_before


def test_setting_missing_product_is_rejected(env):
    cart, _ = env

    with pytest.raises(AppError) as caught:
        cart.set_quantity(999, 3)

    assert caught.value.error_code == "CART_ITEM_NOT_FOUND"


def test_remove_one_product_preserves_others(env):
    cart, _ = env

    cart.add(10)
    cart.add(20)

    assert cart.remove(10) is True
    assert cart.items() == [
        {"product_id": 20, "quantity": 1}
    ]


def test_remove_unknown_product_is_noop(env):
    cart, store = env

    cart.add(10)
    writes_before = store.writes

    assert cart.remove(999) is False
    assert store.writes == writes_before
    assert cart.line_count() == 1


def test_removing_last_product_clears_session_key(env):
    cart, store = env

    cart.add(10)
    cart.remove(10)

    assert CART_SESSION_KEY not in store.data
    assert cart.items() == []


def test_clear_cart(env):
    cart, store = env

    cart.add(10)
    cart.add(20)

    cart.clear()

    assert cart.items() == []
    assert CART_SESSION_KEY not in store.data


def test_snapshot_contains_only_ids_and_quantities(env):
    cart, _ = env

    cart.add(10, 2)
    cart.add(20, 4)

    snapshot = cart.snapshot()

    assert snapshot == {
        "items": [
            {"product_id": 10, "quantity": 2},
            {"product_id": 20, "quantity": 4},
        ],
        "line_count": 2,
        "total_quantity": 6,
    }

    assert "cost_price" not in str(snapshot)
    assert "sell_price" not in str(snapshot)


def test_two_sessions_are_isolated():
    store_a = FakeStore()
    store_b = FakeStore()

    cart_a = CartSession(store_a)
    cart_b = CartSession(store_b)

    cart_a.add(10, 3)

    assert cart_a.total_quantity() == 3
    assert cart_b.items() == []

    cart_b.add(20)

    assert cart_a.has_product(10)
    assert not cart_a.has_product(20)
    assert cart_b.has_product(20)


def test_items_returns_copy_not_live_session_reference(env):
    cart, store = env

    cart.add(10)
    rows = cart.items()
    rows[0]["quantity"] = 999
    rows.append({"product_id": 20, "quantity": 1})

    assert cart.items() == [
        {"product_id": 10, "quantity": 1}
    ]

    assert store.data[CART_SESSION_KEY][0]["quantity"] == 1


def test_cart_change_invalidates_checkout_key(env):
    cart, store = env

    store.set(CHECKOUT_SESSION_KEY, "old-checkout-key")
    cart.add(10)

    assert CHECKOUT_SESSION_KEY not in store.data

    store.set(CHECKOUT_SESSION_KEY, "another-key")
    cart.set_quantity(10, 3)

    assert CHECKOUT_SESSION_KEY not in store.data

    store.set(CHECKOUT_SESSION_KEY, "third-key")
    cart.remove(10)

    assert CHECKOUT_SESSION_KEY not in store.data


def test_unchanged_cart_does_not_invalidate_checkout_key(env):
    cart, store = env

    cart.add(10, 2)
    store.set(CHECKOUT_SESSION_KEY, "same-key")

    cart.set_quantity(10, 2)

    assert store.get(CHECKOUT_SESSION_KEY) == "same-key"


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "10", None, 1.5],
)
def test_invalid_product_id_is_rejected(env, bad_id):
    cart, store = env

    with pytest.raises(AppError) as caught:
        cart.add(bad_id)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert store.data == {}


@pytest.mark.parametrize(
    "bad_quantity",
    [0, -1, True, "2", None, 1.5],
)
def test_invalid_quantity_is_rejected(env, bad_quantity):
    cart, store = env

    with pytest.raises(AppError) as caught:
        cart.add(10, bad_quantity)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert store.data == {}


@pytest.mark.parametrize(
    "bad_data",
    [
        "invalid",
        {},
        [1],
        [{"product_id": 10}],
        [{"product_id": True, "quantity": 1}],
        [{"product_id": 10, "quantity": 0}],
        [
            {"product_id": 10, "quantity": 1},
            {"product_id": 10, "quantity": 2},
        ],
        [
            {
                "product_id": 10,
                "quantity": 1,
                "cost_price": "123",
            }
        ],
    ],
)
def test_invalid_stored_cart_is_rejected(bad_data):
    store = FakeStore()
    store.set(CART_SESSION_KEY, bad_data)

    cart = CartSession(store)

    with pytest.raises(AppError) as caught:
        cart.items()

    assert caught.value.error_code == "CART_INVALID"


def test_logout_configuration_already_clears_cart():
    assert CART_SESSION_KEY in SESSION_KEYS_TO_CLEAR
    assert CHECKOUT_SESSION_KEY in SESSION_KEYS_TO_CLEAR
