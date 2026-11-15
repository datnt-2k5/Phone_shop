
"""Task 54: real, independent-connection MariaDB checkout races.

These tests commit temporary data in phone_shop_test so separate
connections can race. The fixture deletes its own test records.

Never run against phone_shop demo/production databases.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from secrets import token_hex
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.checkout_order_service import CheckoutOrderService

NOW = datetime(2026, 11, 15, 6, 0)
PASSWORD = "MatKhau123!"


class FakeStore:
    def __init__(self, user_id):
        self.values = {
            AUTH_SESSION_USER_ID_KEY: user_id,
        }

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


@pytest.fixture
def ws(test_db: Connection):
    """Use separate committed connections in phone_shop_test ONLY."""
    engine = test_db.engine

    with engine.connect() as probe:
        assert probe.execute(
            text("SELECT DATABASE()")
        ).scalar_one() == "phone_shop_test"

    token = token_hex(8)

    user_id = None
    brand_id = None
    product_id = None

    def factory():
        # Each worker receives its own Session.
        return Session(bind=engine)

    try:
        auth = AuthService(
            session_factory=factory,
        )

        user_id = auth.register(
            email=f"t54race_{token}@example.test",
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name="Checkout Race Customer",
            phone="0912345678",
        ).user_id

        with factory() as session, session.begin():
            row = session.execute(
                text("""
                    INSERT INTO brands (name, created_at)
                    VALUES (:name, :created_at)
                """),
                {
                    "name": f"Task54 Race Brand {token}",
                    "created_at": NOW,
                },
            )

            brand_id = int(row.lastrowid)

            product_id = ProductRepository(session).create(
                sku=f"T54R-{token}",
                name=f"Task54 Race Phone {token}",
                brand_id=brand_id,
                storage="128GB",
                color="Black",
                sell_price=Decimal("12000000.00"),
                now_utc=NOW,
            )

        yield {
            "engine": engine,
            "factory": factory,
            "store": FakeStore(user_id),
            "customer_id": user_id,
            "product_id": product_id,
        }

    finally:
        # Guard again before deleting anything.
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT DATABASE()")
            ).scalar_one() == "phone_shop_test"

            if user_id is not None:
                connection.execute(
                    text("""
                        DELETE oi FROM order_items oi
                        JOIN orders o ON o.id = oi.order_id
                        WHERE o.customer_id = :customer_id
                    """),
                    {"customer_id": user_id},
                )

                connection.execute(
                    text("""
                        DELETE FROM orders
                        WHERE customer_id = :customer_id
                    """),
                    {"customer_id": user_id},
                )

            if product_id is not None:
                connection.execute(
                    text("""
                        DELETE FROM products
                        WHERE id = :id
                    """),
                    {"id": product_id},
                )

            if brand_id is not None:
                connection.execute(
                    text("""
                        DELETE FROM brands
                        WHERE id = :id
                    """),
                    {"id": brand_id},
                )

            if user_id is not None:
                connection.execute(
                    text("""
                        DELETE FROM users
                        WHERE id = :id
                    """),
                    {"id": user_id},
                )


def request(ws, *, key=None, quantity=1):
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Da Nang",
        "note": "",
        "items": [
            {
                "product_id": ws["product_id"],
                "quantity": quantity,
            }
        ],
        "idempotency_key": key or str(uuid4()),
    }


def count_orders(ws, *, key):
    with ws["factory"]() as session:
        return session.execute(
            text("""
                SELECT COUNT(*)
                FROM orders
                WHERE customer_id = :customer_id
                  AND idempotency_key = :key
            """),
            {
                "customer_id": ws["customer_id"],
                "key": key,
            },
        ).scalar_one()


def run_race(ws, first, second):
    barrier = Barrier(2)

    class RacingOrders(OrderRepository):
        def find_by_idempotency_key(
            self,
            *,
            customer_id,
            idempotency_key,
        ):
            existing = super().find_by_idempotency_key(
                customer_id=customer_id,
                idempotency_key=idempotency_key,
            )

            if existing is None:
                # Force both write transactions to see
                # the key as absent before INSERT.
                barrier.wait(timeout=20)

            return existing

    service = CheckoutOrderService(
        session_factory=ws["factory"],
        order_repository_factory=RacingOrders,
    )

    def worker(payload):
        try:
            return service.create(
                session_store=FakeStore(
                    ws["customer_id"],
                ),
                checkout_request=deepcopy(payload),
            )
        except AppError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(worker, first)
        right = pool.submit(worker, second)

        return [
            left.result(timeout=35),
            right.result(timeout=35),
        ]


def test_two_simultaneous_identical_checkouts_create_one_order(ws):
    payload = request(ws)

    results = run_race(
        ws,
        payload,
        payload,
    )

    assert sorted(
        result.outcome
        for result in results
    ) == [
        "CREATED",
        "REPLAY",
    ]

    assert results[0].order["id"] == results[1].order["id"]

    assert count_orders(
        ws,
        key=payload["idempotency_key"],
    ) == 1

    with ws["factory"]() as session:
        count_items = session.execute(
            text("""
                SELECT COUNT(*)
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = :cid
                  AND o.idempotency_key = :key
            """),
            {
                "cid": ws["customer_id"],
                "key": payload["idempotency_key"],
            },
        ).scalar_one()

    assert count_items == 1


def test_simultaneous_same_key_different_payload_returns_conflict(ws):
    key = str(uuid4())

    first = request(
        ws,
        key=key,
        quantity=1,
    )

    second = request(
        ws,
        key=key,
        quantity=2,
    )

    results = run_race(
        ws,
        first,
        second,
    )

    created = [
        result
        for result in results
        if getattr(result, "outcome", None) == "CREATED"
    ]

    conflicts = [
        result
        for result in results
        if (
            isinstance(result, AppError)
            and result.error_code == "IDEMPOTENCY_CONFLICT"
        )
    ]

    assert len(created) == 1
    assert len(conflicts) == 1

    assert count_orders(
        ws,
        key=key,
    ) == 1
