
"""Task 55: persistent cart integration tests on phone_shop_test."""

import json
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import (
    AUTH_SESSION_USER_ID_KEY,
    CHECKOUT_HASH_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
)
from services.persistent_cart import PersistentCart

PASSWORD = "MatKhau123!"


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


@pytest.fixture
def ws(test_db: Connection):
    db = test_db

    assert db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    # Migration Task 55 must have been applied first.
    assert db.execute(
        text("""
            SELECT COUNT(*)
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'customer_carts'
        """)
    ).scalar_one() == 1

    token = token_hex(6)

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)

    customer_a = auth.register(
        email=f"cart_a_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Persistent Cart A",
        phone="0912345678",
    ).user_id

    customer_b = auth.register(
        email=f"cart_b_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Persistent Cart B",
        phone="0987654321",
    ).user_id

    def make_cart(user_id=None):
        return PersistentCart(
            FakeStore(user_id),
            session_factory=factory,
            auth_service=auth,
        )

    return {
        "db": db,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "factory": factory,
        "make_cart": make_cart,
    }


def test_cart_survives_new_customer_session(ws):
    first = ws["make_cart"](ws["customer_a"])

    first.add(5, 2)

    second = ws["make_cart"](ws["customer_a"])

    assert second.items() == [
        {"product_id": 5, "quantity": 2}
    ]


def test_two_sessions_share_latest_cart_changes(ws):
    first = ws["make_cart"](ws["customer_a"])
    second = ws["make_cart"](ws["customer_a"])

    first.add(5, 1)
    second.add(12, 2)
    first.set_quantity(5, 3)

    assert second.items() == [
        {"product_id": 5, "quantity": 3},
        {"product_id": 12, "quantity": 2},
    ]


def test_customers_have_independent_database_carts(ws):
    first = ws["make_cart"](ws["customer_a"])
    second = ws["make_cart"](ws["customer_b"])

    first.add(5, 1)
    second.add(12, 4)

    assert first.items() == [
        {"product_id": 5, "quantity": 1}
    ]
    assert second.items() == [
        {"product_id": 12, "quantity": 4}
    ]


def test_database_stores_no_prices_or_costs(ws):
    cart = ws["make_cart"](ws["customer_a"])

    cart.add(5, 2)

    with ws["factory"]() as session:
        raw = session.execute(
            text("""
                SELECT items_json
                FROM customer_carts
                WHERE customer_id = :customer_id
            """),
            {"customer_id": ws["customer_a"]},
        ).scalar_one()

    data = json.loads(raw)

    assert data == [
        {"product_id": 5, "quantity": 2}
    ]
    assert "sell_price" not in raw
    assert "unit_cost" not in raw
    assert "total_amount" not in raw


def test_checkout_key_invalidated_after_other_session_edit(ws):
    first = ws["make_cart"](ws["customer_a"])
    second = ws["make_cart"](ws["customer_a"])

    first.add(5, 1)

    first.store.set(
        CHECKOUT_SESSION_KEY,
        "old-key",
    )
    first.store.set(
        CHECKOUT_HASH_SESSION_KEY,
        "old-hash",
    )

    second.set_quantity(5, 3)

    assert first.items() == [
        {"product_id": 5, "quantity": 3}
    ]

    assert first.store.get(CHECKOUT_SESSION_KEY) is None
    assert first.store.get(
        CHECKOUT_HASH_SESSION_KEY
    ) is None


def test_clear_after_success_is_seen_in_new_session(ws):
    first = ws["make_cart"](ws["customer_a"])

    first.add(5, 1)
    first.clear()

    new_session = ws["make_cart"](ws["customer_a"])

    assert new_session.items() == []


def test_invalid_mutation_preserves_database_cart(ws):
    cart = ws["make_cart"](ws["customer_a"])

    cart.add(5, 2)

    with pytest.raises(AppError):
        cart.set_quantity(5, 0)

    again = ws["make_cart"](ws["customer_a"])

    assert again.items() == [
        {"product_id": 5, "quantity": 2}
    ]


def test_guest_cannot_read_saved_cart(ws):
    guest = ws["make_cart"]()

    with pytest.raises(AppError) as caught:
        guest.items()

    assert caught.value.error_code == "UNAUTHORIZED"
