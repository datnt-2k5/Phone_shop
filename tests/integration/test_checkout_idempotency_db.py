
"""Task 53 / US09-T06: MariaDB idempotency lookup tests.

Only uses the transactional phone_shop_test fixture.
The test never modifies the demo/production phone_shop DB.
"""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from secrets import token_hex
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.order_repository import OrderRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.checkout_idempotency_service import (
    CheckoutIdempotencyService,
)
from services.checkout_request_hash import create_request_hash

NOW = datetime(2026, 11, 13, 1, 0)
PASSWORD = "MatKhau123!"


class FakeStore:
    """Minimal server-side session store for integration tests."""

    def __init__(self, user_id=None):
        self.values = {}

        if user_id is not None:
            self.set(AUTH_SESSION_USER_ID_KEY, user_id)

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


@pytest.fixture
def ws(test_db: Connection):
    """Create isolated test customers in phone_shop_test."""
    db = test_db

    assert db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    token = token_hex(6)

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)

    customer_a = auth.register(
        email=f"t53a_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Customer Task53 A",
        phone="0912345678",
    ).user_id

    customer_b = auth.register(
        email=f"t53b_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Customer Task53 B",
        phone="0987654321",
    ).user_id

    service = CheckoutIdempotencyService(
        session_factory=factory,
        auth_service=auth,
    )

    return {
        "db": db,
        "factory": factory,
        "service": service,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "store_a": FakeStore(customer_a),
        "store_b": FakeStore(customer_b),
    }


def checkout_request():
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "",
        "items": [
            {
                "product_id": 9_223_372_036_854_775_807,
                "quantity": 1,
            }
        ],
        "idempotency_key": str(uuid4()),
    }


def seed_existing_order(ws, request, *, customer_id=None):
    """Create an earlier PENDING order without creating product rows."""
    owner_id = (
        ws["customer_a"]
        if customer_id is None
        else customer_id
    )

    with (
        ws["factory"]() as session,
        session.begin(),
    ):
        repo = OrderRepository(session)

        order_id = repo.create_pending(
            temporary_code=f"TMP-{token_hex(12)}",
            customer_id=owner_id,
            idempotency_key=request["idempotency_key"],
            request_hash=create_request_hash(request),
            receiver_name=request["receiver_name"],
            receiver_phone=request["receiver_phone"],
            receiver_address=request["receiver_address"],
            note=request.get("note"),
            total_amount=Decimal("100.00"),
            now_utc=NOW,
        )

    return order_id


def count_customer_orders(ws, customer_id):
    with ws["factory"]() as session:
        return session.execute(
            text("""
                SELECT COUNT(*)
                FROM orders
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        ).scalar_one()


def test_new_key_returns_new_without_inserting_order(ws):
    request = checkout_request()

    before = count_customer_orders(
        ws, ws["customer_a"]
    )

    result = ws["service"].check(
        session_store=ws["store_a"],
        checkout_request=request,
    )

    after = count_customer_orders(
        ws, ws["customer_a"]
    )

    assert result.outcome == "NEW"
    assert result.customer_id == ws["customer_a"]
    assert result.existing_order is None
    assert result.request_hash == create_request_hash(request)
    assert before == after


def test_same_key_same_hash_replays_existing_order(ws):
    request = checkout_request()

    order_id = seed_existing_order(
        ws,
        request,
    )

    before = count_customer_orders(
        ws, ws["customer_a"]
    )

    result = ws["service"].check(
        session_store=ws["store_a"],
        checkout_request=request,
    )

    after = count_customer_orders(
        ws, ws["customer_a"]
    )

    assert result.outcome == "REPLAY"
    assert result.existing_order["id"] == order_id
    assert result.existing_order["status"] == "PENDING"
    assert result.existing_order["total_amount"] == Decimal(
        "100.00"
    )
    assert before == after

    # The product ID is structurally valid but does not need
    # to exist in the product catalog for a replay.
    assert request["items"][0]["product_id"] == (
        9_223_372_036_854_775_807
    )


def test_same_key_different_quantity_causes_conflict(ws):
    original = checkout_request()

    order_id = seed_existing_order(
        ws,
        original,
    )

    changed = deepcopy(original)
    changed["items"][0]["quantity"] = 2

    with pytest.raises(AppError) as caught:
        ws["service"].check(
            session_store=ws["store_a"],
            checkout_request=changed,
        )

    assert caught.value.error_code == "IDEMPOTENCY_CONFLICT"

    with ws["factory"]() as session:
        old = OrderRepository(session).get_by_id(order_id)

    assert old is not None
    assert old["request_hash"] == create_request_hash(original)

    assert count_customer_orders(
        ws,
        ws["customer_a"],
    ) == 1


def test_other_customer_cannot_replay_first_customer_order(ws):
    request = checkout_request()

    first_order_id = seed_existing_order(
        ws,
        request,
        customer_id=ws["customer_a"],
    )

    result = ws["service"].check(
        session_store=ws["store_b"],
        checkout_request=request,
    )

    assert result.outcome == "NEW"
    assert result.customer_id == ws["customer_b"]
    assert result.existing_order is None

    with ws["factory"]() as session:
        old = OrderRepository(session).get_by_id(
            first_order_id
        )

    assert old["customer_id"] == ws["customer_a"]
    assert count_customer_orders(
        ws,
        ws["customer_b"],
    ) == 0


def test_different_key_with_same_payload_returns_new(ws):
    request = checkout_request()

    seed_existing_order(ws, request)

    changed = deepcopy(request)
    changed["idempotency_key"] = str(uuid4())

    result = ws["service"].check(
        session_store=ws["store_a"],
        checkout_request=changed,
    )

    assert result.outcome == "NEW"
    assert result.existing_order is None

    assert result.request_hash == create_request_hash(
        request
    )

    assert count_customer_orders(
        ws,
        ws["customer_a"],
    ) == 1


def test_guest_cannot_query_existing_order(ws):
    request = checkout_request()

    seed_existing_order(ws, request)

    with pytest.raises(AppError) as caught:
        ws["service"].check(
            session_store=FakeStore(),
            checkout_request=request,
        )

    assert caught.value.error_code == "UNAUTHORIZED"

    assert count_customer_orders(
        ws,
        ws["customer_a"],
    ) == 1
