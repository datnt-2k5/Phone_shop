
"""Task 55: unit tests for DB-backed Customer carts."""

import json
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.auth_session import (
    AUTH_SESSION_USER_ID_KEY,
    CART_SESSION_KEY,
    CHECKOUT_HASH_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
)
from services.persistent_cart import PersistentCart
from ui.checkout_key_state import CheckoutKeyState


class FakeStore:
    def __init__(self, user_id=None):
        self.values = {}

        if user_id is not None:
            self.values[AUTH_SESSION_USER_ID_KEY] = user_id

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


class StrictFakeStore(FakeStore):
    """Mimic Flet SessionStore.remove() on missing keys."""

    def remove(self, key):
        del self.values[key]

class FakeAuth:
    def require_user(self, *, session_store, allowed_roles):
        assert allowed_roles == ("CUSTOMER",)

        user_id = session_store.get(AUTH_SESSION_USER_ID_KEY)

        if user_id is None:
            raise AppError(
                "UNAUTHORIZED",
                "Vui lòng đăng nhập.",
            )

        return SimpleNamespace(user_id=user_id)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return self


class FakeCartRepository:
    def __init__(self, records):
        self.records = records

    def read(self, *, customer_id):
        return self.records.get(customer_id)

    def lock_or_create(self, *, customer_id):
        return self.records.setdefault(customer_id, "[]")

    def save(self, *, customer_id, items_json):
        self.records[customer_id] = items_json


def make_cart(*, user_id=7, records=None, store=None):
    if records is None:
        records = {}

    if store is None:
        store = FakeStore(user_id)

    cart = PersistentCart(
        store,
        session_factory=FakeSession,
        auth_service=FakeAuth(),
        repository_factory=lambda session: FakeCartRepository(
            records
        ),
    )

    return store, cart, records


def test_add_persists_only_product_and_quantity():
    store, cart, records = make_cart()

    result = cart.add(5, 2)

    assert result == [
        {"product_id": 5, "quantity": 2}
    ]
    assert json.loads(records[7]) == result
    assert store.get(CART_SESSION_KEY) == result
    assert "sell_price" not in records[7]


def test_new_session_restores_customer_cart():
    _store_a, cart_a, records = make_cart()

    cart_a.add(5, 2)

    store_b, cart_b, _ = make_cart(
        records=records,
    )

    assert store_b.get(CART_SESSION_KEY) is None
    assert cart_b.items() == [
        {"product_id": 5, "quantity": 2}
    ]


def test_two_sessions_see_updated_quantity():
    _, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 1)
    second.set_quantity(5, 4)

    assert first.items() == [
        {"product_id": 5, "quantity": 4}
    ]


def test_two_sessions_do_not_overwrite_different_items():
    _, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 1)
    second.add(12, 2)

    assert first.items() == [
        {"product_id": 5, "quantity": 1},
        {"product_id": 12, "quantity": 2},
    ]


def test_repeated_product_increases_quantity():
    _, cart, _ = make_cart()

    cart.add(5, 1)
    cart.add(5, 2)

    assert cart.items() == [
        {"product_id": 5, "quantity": 3}
    ]
    assert cart.line_count() == 1
    assert cart.total_quantity() == 3


def test_remove_syncs_to_another_session():
    _, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 1)
    first.add(12, 1)

    assert second.remove(5) is True
    assert first.items() == [
        {"product_id": 12, "quantity": 1}
    ]


def test_clear_keeps_database_cart_empty():
    _, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 2)
    first.clear()

    assert second.items() == []
    assert json.loads(records[7]) == []


def test_two_customers_have_isolated_carts():
    _, first, records = make_cart(user_id=7)
    _, second, _ = make_cart(
        user_id=8,
        records=records,
    )

    first.add(5, 1)
    second.add(12, 2)

    assert first.items() == [
        {"product_id": 5, "quantity": 1}
    ]
    assert second.items() == [
        {"product_id": 12, "quantity": 2}
    ]


def test_cart_limit_is_enforced():
    _, cart, _ = make_cart()

    for product_id in range(1, 21):
        cart.add(product_id, 1)

    assert cart.line_count() == 20

    with pytest.raises(AppError) as caught:
        cart.add(21, 1)

    assert caught.value.error_code == "CART_LIMIT_EXCEEDED"
    assert cart.line_count() == 20


@pytest.mark.parametrize(
    "product_id,quantity",
    [
        (0, 1),
        (-1, 1),
        (True, 1),
        (5, 0),
        (5, -1),
        (5, True),
    ],
)
def test_invalid_cart_mutation_is_rejected(
    product_id,
    quantity,
):
    _, cart, _ = make_cart()

    with pytest.raises(AppError):
        cart.add(product_id, quantity)

    assert cart.items() == []


def test_guest_cannot_access_persistent_cart():
    _store, cart, records = make_cart(
        store=FakeStore(),
    )

    with pytest.raises(AppError) as caught:
        cart.add(5, 1)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert records == {}


def test_reading_external_change_invalidates_old_checkout_key():
    store_a, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 1)

    store_a.set(CHECKOUT_SESSION_KEY, "old-key")
    store_a.set(CHECKOUT_HASH_SESSION_KEY, "old-hash")

    second.set_quantity(5, 2)
    first.items()

    assert store_a.get(CHECKOUT_SESSION_KEY) is None
    assert store_a.get(CHECKOUT_HASH_SESSION_KEY) is None


def test_reading_unchanged_cart_preserves_checkout_key():
    store, cart, _ = make_cart()

    cart.add(5, 1)

    store.set(CHECKOUT_SESSION_KEY, "same-key")
    store.set(CHECKOUT_HASH_SESSION_KEY, "same-hash")

    cart.items()

    assert store.get(CHECKOUT_SESSION_KEY) == "same-key"
    assert store.get(CHECKOUT_HASH_SESSION_KEY) == "same-hash"


def test_corrupted_database_cart_is_rejected():
    records = {7: '{"unexpected":true}'}
    _, cart, _ = make_cart(records=records)

    with pytest.raises(AppError) as caught:
        cart.items()

    assert caught.value.error_code == "CART_INVALID"


def test_logout_new_session_does_not_erase_database_cart():
    store, cart, records = make_cart()

    cart.add(5, 3)

    store.remove(AUTH_SESSION_USER_ID_KEY)
    store.remove(CART_SESSION_KEY)

    new_store = FakeStore(7)
    _, new_cart, _ = make_cart(
        records=records,
        store=new_store,
    )

    assert new_cart.items() == [
        {"product_id": 5, "quantity": 3}
    ]


def test_has_product_uses_latest_database_cart():
    _, first, records = make_cart()
    _, second, _ = make_cart(records=records)

    first.add(5, 1)

    assert second.has_product(5) is True

    first.remove(5)

    assert second.has_product(5) is False


def test_strict_store_add_without_checkout_key():
    store = StrictFakeStore(7)
    _, cart, records = make_cart(store=store)

    result = cart.add(5, 1)

    assert result == [
        {"product_id": 5, "quantity": 1}
    ]
    assert json.loads(records[7]) == result
    assert store.get(CHECKOUT_SESSION_KEY) is None


def test_strict_store_update_without_checkout_key():
    store = StrictFakeStore(7)
    _, cart, _ = make_cart(store=store)

    cart.add(5, 1)
    cart.set_quantity(5, 3)

    assert cart.items() == [
        {"product_id": 5, "quantity": 3}
    ]
    assert store.get(CHECKOUT_SESSION_KEY) is None


def test_strict_store_clear_cart_without_checkout_key():
    store = StrictFakeStore(7)
    _, cart, _ = make_cart(store=store)

    cart.add(5, 2)
    cart.clear()

    assert cart.items() == []
    assert store.get(CHECKOUT_SESSION_KEY) is None


def test_strict_store_checkout_clear_twice():
    store = StrictFakeStore(7)
    checkout_keys = CheckoutKeyState(store)

    # Before any checkout, neither key exists.
    checkout_keys.clear()

    store.set(CHECKOUT_SESSION_KEY, "example-key")
    store.set(CHECKOUT_HASH_SESSION_KEY, "example-hash")

    checkout_keys.clear()

    assert store.get(CHECKOUT_SESSION_KEY) is None
    assert store.get(CHECKOUT_HASH_SESSION_KEY) is None

    # Repeated clear must be safe.
    checkout_keys.clear()
