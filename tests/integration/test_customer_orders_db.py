
"""Task 53: Customer order history integration tests."""

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
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.customer_order_service import CustomerOrderService

NOW = datetime(2026, 11, 15, 5, 0)
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

    brand_name = f"Task53 Brand {token}"

    result = db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created_at)
        """),
        {
            "name": brand_name,
            "created_at": NOW,
        },
    )

    brand_id = int(result.lastrowid)

    with factory() as session, session.begin():
        products = ProductRepository(session)

        product_id = products.create(
            sku=f"T53-{token}",
            name=f"Task53 Phone {token}",
            brand_id=brand_id,
            storage="128GB",
            color="Black",
            sell_price=Decimal("12000000.00"),
            now_utc=NOW,
        )

    def create_order(owner_id):
        with factory() as session, session.begin():
            orders = OrderRepository(session)

            order_id = orders.create_pending(
                temporary_code=f"TMP-{uuid4().hex}",
                customer_id=owner_id,
                idempotency_key=str(uuid4()),
                request_hash="a" * 64,
                receiver_name="Nguyen Van A",
                receiver_phone="0912345678",
                receiver_address="Da Nang",
                note="Giao gio hanh chinh",
                total_amount=Decimal("12000000.00"),
                now_utc=NOW,
            )

            orders.create_item(
                order_id=order_id,
                product_id=product_id,
                product_name=f"Task53 Phone {token}",
                brand_name=brand_name,
                quantity=1,
                unit_price=Decimal("12000000.00"),
            )

            assert orders.update_code(
                order_id=order_id,
                code=f"DH{order_id:08d}",
            )

        return order_id

    order_a1 = create_order(customer_a)
    order_a2 = create_order(customer_a)
    order_b1 = create_order(customer_b)

    return {
        "db": db,
        "service": CustomerOrderService(
            session_factory=factory,
            auth_service=auth,
        ),
        "store_a": FakeStore(customer_a),
        "store_b": FakeStore(customer_b),
        "customer_a": customer_a,
        "customer_b": customer_b,
        "product_id": product_id,
        "product_name": f"Task53 Phone {token}",
        "order_a1": order_a1,
        "order_a2": order_a2,
        "order_b1": order_b1,
    }


def test_customer_list_only_contains_own_orders(ws):
    result = ws["service"].list_orders(
        session_store=ws["store_a"],
    )

    ids = [row["id"] for row in result["items"]]

    assert ids == [
        ws["order_a2"],
        ws["order_a1"],
    ]
    assert ws["order_b1"] not in ids
    assert result["total"] == 2


def test_other_customer_sees_only_their_orders(ws):
    result = ws["service"].list_orders(
        session_store=ws["store_b"],
    )

    ids = [row["id"] for row in result["items"]]

    assert ids == [ws["order_b1"]]
    assert result["total"] == 1


def test_customer_pagination_uses_stable_order(ws):
    first = ws["service"].list_orders(
        session_store=ws["store_a"],
        page=1,
        page_size=1,
    )

    second = ws["service"].list_orders(
        session_store=ws["store_a"],
        page=2,
        page_size=1,
    )

    assert first["total_pages"] == 2
    assert first["items"][0]["id"] == ws["order_a2"]
    assert second["items"][0]["id"] == ws["order_a1"]


def test_order_detail_preserves_snapshot(ws):
    result = ws["service"].get_order(
        session_store=ws["store_a"],
        order_id=ws["order_a1"],
    )

    assert result["code"] == (
        f"DH{ws['order_a1']:08d}"
    )
    assert result["status"] == "PENDING"
    assert result["total_amount"] == Decimal(
        "12000000.00"
    )

    assert len(result["items"]) == 1

    item = result["items"][0]

    assert item["product_name"] == ws["product_name"]
    assert item["quantity"] == 1
    assert item["unit_price"] == Decimal(
        "12000000.00"
    )

    assert "unit_cost" not in item
    assert "request_hash" not in result
    assert "idempotency_key" not in result


def test_customer_cannot_read_someone_elses_order(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].get_order(
            session_store=ws["store_a"],
            order_id=ws["order_b1"],
        )

    assert caught.value.error_code == "NOT_FOUND"


def test_guest_cannot_read_customer_orders(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].list_orders(
            session_store=FakeStore(),
        )

    assert caught.value.error_code == "UNAUTHORIZED"


def test_snapshot_does_not_change_after_price_update(ws):
    ws["db"].execute(
        text("""
            UPDATE products
            SET sell_price = :price,
                name = :name
            WHERE id = :product_id
        """),
        {
            "price": Decimal("15000000.00"),
            "name": "Changed Name",
            "product_id": ws["product_id"],
        },
    )

    result = ws["service"].get_order(
        session_store=ws["store_a"],
        order_id=ws["order_a1"],
    )

    item = result["items"][0]

    assert item["unit_price"] == Decimal(
        "12000000.00"
    )
    assert item["product_name"] == ws["product_name"]


def test_order_history_queries_do_not_write_database(ws):
    def count_orders():
        return ws["db"].execute(
            text("SELECT COUNT(*) FROM orders")
        ).scalar_one()

    before = count_orders()

    ws["service"].list_orders(
        session_store=ws["store_a"],
    )
    ws["service"].get_order(
        session_store=ws["store_a"],
        order_id=ws["order_a1"],
    )

    assert count_orders() == before
