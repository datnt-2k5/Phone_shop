"""Task 54 / US09-T07: PENDING order MariaDB integration tests.

All writes use the transactional phone_shop_test fixture.
Never run these tests against the demo phone_shop database.
"""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex
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
from services.checkout_request_hash import create_request_hash
from utils.time_utils import FixedClock

FIXED_TIME = datetime(2026, 11, 13, 9, 30, tzinfo=UTC)
DB_TIME = datetime(2026, 11, 13, 9, 30)
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

    token = token_hex(6)

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)

    customer_a = auth.register(
        email=f"t54a_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Customer Task54 A",
        phone="0912345678",
    ).user_id

    customer_b = auth.register(
        email=f"t54b_{token}@example.test",
        password=PASSWORD,
        confirm_password=PASSWORD,
        full_name="Customer Task54 B",
        phone="0987654321",
    ).user_id

    brand_name = f"Task54 Brand {token}"

    result = db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created_at)
        """),
        {
            "name": brand_name,
            "created_at": DB_TIME,
        },
    )

    brand_id = int(result.lastrowid)

    with factory() as session, session.begin():
        products = ProductRepository(session)

        product_a = products.create(
            sku=f"T54-A-{token}",
            name=f"Task54 Phone A {token}",
            brand_id=brand_id,
            storage="128GB",
            color="Black",
            sell_price=Decimal("12000000.50"),
            now_utc=DB_TIME,
        )

        product_b = products.create(
            sku=f"T54-B-{token}",
            name=f"Task54 Phone B {token}",
            brand_id=brand_id,
            storage="256GB",
            color="Blue",
            sell_price=Decimal("8000000.00"),
            now_utc=DB_TIME,
        )

    service = CheckoutOrderService(
        session_factory=factory,
        clock=FixedClock(FIXED_TIME),
    )

    return {
        "db": db,
        "factory": factory,
        "service": service,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "store_a": FakeStore(customer_a),
        "store_b": FakeStore(customer_b),
        "product_a": product_a,
        "product_b": product_b,
        "name_a": f"Task54 Phone A {token}",
        "name_b": f"Task54 Phone B {token}",
        "brand_name": brand_name,
    }


def request(ws, *, key=None):
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "Giao gio hanh chinh",
        "items": [
            {"product_id": ws["product_a"], "quantity": 2},
            {"product_id": ws["product_b"], "quantity": 1},
        ],
        "idempotency_key": key or str(uuid4()),
    }


def create(ws, payload, *, store=None, service=None):
    actual_store = (
        ws["store_a"] if store is None else store
    )
    actual_service = (
        ws["service"] if service is None else service
    )

    return actual_service.create(
        session_store=actual_store,
        checkout_request=payload,
    )


def count_orders(ws, customer_id):
    with ws["factory"]() as session:
        return session.execute(
            text("""
                SELECT COUNT(*)
                FROM orders
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        ).scalar_one()


def load_order(ws, order_id):
    with ws["factory"]() as session:
        repo = OrderRepository(session)

        return (
            repo.get_by_id(order_id),
            repo.list_items(order_id),
        )


def product_inventory(ws):
    rows = ws["db"].execute(
        text("""
            SELECT id, stock, cost_price
            FROM products
            WHERE id IN (:first, :second)
            ORDER BY id
        """),
        {
            "first": ws["product_a"],
            "second": ws["product_b"],
        },
    ).mappings().all()

    return [dict(row) for row in rows]


def test_create_pending_persists_price_and_name_snapshots(ws):
    payload = request(ws)
    before_inventory = product_inventory(ws)

    result = create(ws, payload)

    assert result.outcome == "CREATED"
    assert result.order["status"] == "PENDING"
    assert result.order["total_amount"] == Decimal(
        "32000001.00"
    )
    assert "chưa được giữ hàng" in result.message

    order_id = result.order["id"]

    assert result.order["code"] == f"ORD-{order_id:010d}"
    assert count_orders(ws, ws["customer_a"]) == 1

    order, items = load_order(ws, order_id)

    assert order["customer_id"] == ws["customer_a"]
    assert order["idempotency_key"] == payload["idempotency_key"]
    assert order["request_hash"] == create_request_hash(payload)
    assert order["total_amount"] == Decimal("32000001.00")
    assert order["created_at"] == DB_TIME
    assert order["updated_at"] == DB_TIME

    assert order["confirmed_at"] is None
    assert order["completed_at"] is None
    assert order["cancelled_at"] is None

    assert len(items) == 2

    by_product = {
        item["product_id"]: item
        for item in items
    }

    first = by_product[ws["product_a"]]
    second = by_product[ws["product_b"]]

    assert first["product_name"] == ws["name_a"]
    assert first["brand_name"] == ws["brand_name"]
    assert first["quantity"] == 2
    assert first["unit_price"] == Decimal("12000000.50")
    assert first["unit_cost"] is None

    assert second["product_name"] == ws["name_b"]
    assert second["quantity"] == 1
    assert second["unit_price"] == Decimal("8000000.00")
    assert second["unit_cost"] is None

    assert product_inventory(ws) == before_inventory

    assert set(result.order) == {
        "id",
        "code",
        "status",
        "total_amount",
    }


def test_retry_after_price_change_and_discontinue_replays_old_order(ws):
    payload = request(ws)

    first = create(ws, payload)
    order_id = first.order["id"]

    ws["db"].execute(
        text("""
            UPDATE products
            SET sell_price = :price,
                status = 'DISCONTINUED',
                name = :name
            WHERE id = :product_id
        """),
        {
            "price": Decimal("15000000.00"),
            "name": "Changed Phone Name",
            "product_id": ws["product_a"],
        },
    )

    second = create(ws, payload)

    assert second.outcome == "REPLAY"
    assert second.order == first.order
    assert count_orders(ws, ws["customer_a"]) == 1

    order, items = load_order(ws, order_id)
    by_product = {
        item["product_id"]: item
        for item in items
    }

    assert order["status"] == "PENDING"
    assert by_product[ws["product_a"]]["unit_price"] == (
        Decimal("12000000.50")
    )
    assert by_product[ws["product_a"]]["product_name"] == (
        ws["name_a"]
    )


def test_same_key_different_quantity_returns_conflict(ws):
    payload = request(ws)
    first = create(ws, payload)

    changed = deepcopy(payload)
    changed["items"][0]["quantity"] = 3

    with pytest.raises(AppError) as caught:
        create(ws, changed)

    assert caught.value.error_code == "IDEMPOTENCY_CONFLICT"
    assert count_orders(ws, ws["customer_a"]) == 1

    order, items = load_order(ws, first.order["id"])

    assert order["request_hash"] == create_request_hash(payload)
    assert len(items) == 2


def test_new_order_rejects_missing_product(ws):
    payload = request(ws)

    payload["items"][0]["product_id"] = (
        9_223_372_036_854_775_807
    )

    with pytest.raises(AppError) as caught:
        create(ws, payload)

    assert caught.value.error_code == "PRODUCT_UNAVAILABLE"
    assert count_orders(ws, ws["customer_a"]) == 0


def test_new_order_rejects_discontinued_product(ws):
    payload = request(ws)

    ws["db"].execute(
        text("""
            UPDATE products
            SET status = 'DISCONTINUED'
            WHERE id = :product_id
        """),
        {"product_id": ws["product_b"]},
    )

    with pytest.raises(AppError) as caught:
        create(ws, payload)

    assert caught.value.error_code == "PRODUCT_UNAVAILABLE"
    assert count_orders(ws, ws["customer_a"]) == 0


def test_new_order_uses_latest_database_price(ws):
    payload = request(ws)

    ws["db"].execute(
        text("""
            UPDATE products
            SET sell_price = :price
            WHERE id = :product_id
        """),
        {
            "price": Decimal("15000000.00"),
            "product_id": ws["product_a"],
        },
    )

    result = create(ws, payload)

    assert result.outcome == "CREATED"
    assert result.order["total_amount"] == Decimal(
        "38000000.00"
    )

    _, items = load_order(ws, result.order["id"])

    first = next(
        item
        for item in items
        if item["product_id"] == ws["product_a"]
    )

    assert first["unit_price"] == Decimal("15000000.00")


def test_second_item_insert_failure_rolls_back_order(ws):
    class FailingOrderRepository(OrderRepository):
        def create_item(self, **kwargs):
            super().create_item(**kwargs)
            raise RuntimeError("forced item failure")

    service = CheckoutOrderService(
        session_factory=ws["factory"],
        clock=FixedClock(FIXED_TIME),
        order_repository_factory=FailingOrderRepository,
    )

    payload = request(ws)

    with pytest.raises(
        RuntimeError,
        match="forced item failure",
    ):
        create(ws, payload, service=service)

    assert count_orders(ws, ws["customer_a"]) == 0

    with ws["factory"]() as session:
        item_count = session.execute(
            text("""
                SELECT COUNT(*)
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE o.customer_id = :customer_id
            """),
            {"customer_id": ws["customer_a"]},
        ).scalar_one()

    assert item_count == 0


def test_same_key_can_be_used_by_different_customers(ws):
    shared_key = str(uuid4())
    first_payload = request(ws, key=shared_key)
    second_payload = deepcopy(first_payload)

    first = create(
        ws,
        first_payload,
        store=ws["store_a"],
    )

    second = create(
        ws,
        second_payload,
        store=ws["store_b"],
    )

    assert first.outcome == "CREATED"
    assert second.outcome == "CREATED"
    assert first.order["id"] != second.order["id"]
    assert first.order["code"] != second.order["code"]
    assert count_orders(ws, ws["customer_a"]) == 1
    assert count_orders(ws, ws["customer_b"]) == 1


def test_unauthenticated_checkout_cannot_create_order(ws):
    payload = request(ws)

    with pytest.raises(AppError) as caught:
        create(
            ws,
            payload,
            store=FakeStore(),
        )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert count_orders(ws, ws["customer_a"]) == 0


def test_total_exceeding_decimal_column_is_rejected(ws):
    payload = request(ws)

    payload["items"] = [
        {
            "product_id": ws["product_a"],
            "quantity": 2_147_483_647,
        }
    ]

    with pytest.raises(AppError) as caught:
        create(ws, payload)

    assert caught.value.error_code == "ORDER_TOTAL_EXCEEDED"
    assert count_orders(ws, ws["customer_a"]) == 0
