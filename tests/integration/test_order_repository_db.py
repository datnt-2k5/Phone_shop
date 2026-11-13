
"""Task 49 / US09-T02: Order Repository integration tests.

Runs exclusively on phone_shop_test using the project's
transactional test_db fixture.
"""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService

NOW = datetime(2026, 11, 13, 1, 0)
TEST_PASSWORD = "MatKhau123!"


@pytest.fixture
def ws(test_db: Connection):
    """Create isolated customers and products for one test."""
    db = test_db

    assert (
        db.execute(text("SELECT DATABASE()")).scalar_one()
        == "phone_shop_test"
    )

    token = token_hex(6)

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)

    customer_a = auth.register(
        email=f"t49a_{token}@example.test",
        password=TEST_PASSWORD,
        confirm_password=TEST_PASSWORD,
        full_name="Customer Task49 A",
        phone="0912345678",
    ).user_id

    customer_b = auth.register(
        email=f"t49b_{token}@example.test",
        password=TEST_PASSWORD,
        confirm_password=TEST_PASSWORD,
        full_name="Customer Task49 B",
        phone="0987654321",
    ).user_id

    result = db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created_at)
        """),
        {
            "name": f"Task49 Brand {token}",
            "created_at": NOW,
        },
    )

    brand_id = int(result.lastrowid)

    with factory() as session, session.begin():
        products = ProductRepository(session)

        product_a = products.create(
            sku=f"T49-A-{token}",
            name=f"Task49 Phone A {token}",
            brand_id=brand_id,
            storage="128GB",
            color="Black",
            sell_price=Decimal("12000000.00"),
            now_utc=NOW,
        )

        product_b = products.create(
            sku=f"T49-B-{token}",
            name=f"Task49 Phone B {token}",
            brand_id=brand_id,
            storage="256GB",
            color="Blue",
            sell_price=Decimal("8000000.00"),
            now_utc=NOW,
        )

    return {
        "db": db,
        "factory": factory,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "product_a": product_a,
        "product_b": product_b,
        "brand_name": f"Task49 Brand {token}",
        "name_a": f"Task49 Phone A {token}",
        "name_b": f"Task49 Phone B {token}",
    }


def order_args(ws):
    return {
        "temporary_code": f"TMP-{token_hex(12)}",
        "customer_id": ws["customer_a"],
        "idempotency_key": token_hex(16),
        "request_hash": "a" * 64,
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": None,
        "total_amount": Decimal("32000000.00"),
        "now_utc": NOW,
    }


def create_order(ws, **changes):
    data = order_args(ws)
    data.update(changes)

    with ws["factory"]() as session, session.begin():
        order_id = OrderRepository(session).create_pending(
            **data
        )

    return order_id, data


def create_order_item(
    ws,
    order_id,
    product_id=None,
    quantity=2,
    unit_price=Decimal("12000000.00"),
):
    actual_product_id = (
        ws["product_a"]
        if product_id is None
        else product_id
    )

    with ws["factory"]() as session, session.begin():
        return OrderRepository(session).create_item(
            order_id=order_id,
            product_id=actual_product_id,
            product_name=ws["name_a"],
            brand_name=ws["brand_name"],
            quantity=quantity,
            unit_price=unit_price,
        )


# ============================================================
# TEST 01: Schema
# ============================================================

def test_orders_and_order_items_have_required_columns(ws):
    rows = ws["db"].execute(
        text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name IN ('orders', 'order_items')
        """)
    ).mappings().all()

    columns = {
        "orders": set(),
        "order_items": set(),
    }

    for row in rows:
        columns[row["table_name"]].add(
            row["column_name"]
        )

    assert {
        "id",
        "code",
        "customer_id",
        "idempotency_key",
        "request_hash",
        "status",
        "receiver_name",
        "receiver_phone",
        "receiver_address",
        "note",
        "total_amount",
        "created_at",
        "confirmed_at",
        "completed_at",
        "cancelled_at",
        "cancelled_by",
        "cancel_reason",
        "updated_at",
    } <= columns["orders"]

    assert {
        "id",
        "order_id",
        "product_id",
        "product_name",
        "brand_name",
        "quantity",
        "unit_price",
        "unit_cost",
    } <= columns["order_items"]


# ============================================================
# TEST 02: Create PENDING
# ============================================================

def test_create_pending_order_with_correct_defaults(ws):
    order_id, data = create_order(ws)

    with ws["factory"]() as session:
        row = OrderRepository(session).get_by_id(order_id)

    assert row is not None
    assert row["id"] == order_id
    assert row["customer_id"] == ws["customer_a"]
    assert row["code"] == data["temporary_code"]
    assert row["idempotency_key"] == data["idempotency_key"]
    assert row["request_hash"] == "a" * 64
    assert row["status"] == "PENDING"

    assert row["total_amount"] == Decimal("32000000.00")
    assert row["created_at"] == NOW
    assert row["updated_at"] == NOW

    assert row["confirmed_at"] is None
    assert row["completed_at"] is None
    assert row["cancelled_at"] is None
    assert row["cancelled_by"] is None
    assert row["cancel_reason"] is None


# ============================================================
# TEST 03: Product snapshots
# ============================================================

def test_create_items_with_name_price_snapshot_and_null_cost(ws):
    order_id, _ = create_order(ws)

    first_id = create_order_item(
        ws,
        order_id,
    )

    with ws["factory"]() as session, session.begin():
        second_id = OrderRepository(session).create_item(
            order_id=order_id,
            product_id=ws["product_b"],
            product_name=ws["name_b"],
            brand_name=ws["brand_name"],
            quantity=1,
            unit_price=Decimal("8000000.00"),
        )

    assert first_id != second_id

    with ws["factory"]() as session:
        rows = OrderRepository(session).list_items(order_id)

    assert len(rows) == 2
    assert rows[0]["id"] == first_id
    assert rows[1]["id"] == second_id

    assert rows[0]["product_name"] == ws["name_a"]
    assert rows[0]["brand_name"] == ws["brand_name"]
    assert rows[0]["quantity"] == 2
    assert rows[0]["unit_price"] == Decimal("12000000.00")

    assert rows[1]["product_name"] == ws["name_b"]
    assert rows[1]["quantity"] == 1
    assert rows[1]["unit_price"] == Decimal("8000000.00")

    assert all(row["unit_cost"] is None for row in rows)


# ============================================================
# TEST 04: Replace temporary order code
# ============================================================

def test_update_temporary_code_and_find_by_code(ws):
    order_id, data = create_order(ws)
    official_code = f"ORD-{token_hex(10)}"

    with ws["factory"]() as session, session.begin():
        updated = OrderRepository(session).update_code(
            order_id=order_id,
            code=official_code,
        )

    assert updated is True

    with ws["factory"]() as session:
        repo = OrderRepository(session)

        found = repo.get_by_code(official_code)
        old = repo.get_by_code(data["temporary_code"])

    assert found is not None
    assert found["id"] == order_id
    assert found["status"] == "PENDING"
    assert old is None


# ============================================================
# TEST 05: Idempotency scoped to customer
# ============================================================

def test_idempotency_lookup_is_scoped_to_customer(ws):
    shared_key = token_hex(16)

    first_id, _ = create_order(
        ws,
        customer_id=ws["customer_a"],
        idempotency_key=shared_key,
    )

    second_id, _ = create_order(
        ws,
        customer_id=ws["customer_b"],
        idempotency_key=shared_key,
    )

    assert first_id != second_id

    with ws["factory"]() as session:
        repo = OrderRepository(session)

        first = repo.find_by_idempotency_key(
            customer_id=ws["customer_a"],
            idempotency_key=shared_key,
        )

        second = repo.find_by_idempotency_key(
            customer_id=ws["customer_b"],
            idempotency_key=shared_key,
        )

    assert first["id"] == first_id
    assert second["id"] == second_id


# ============================================================
# TEST 06: UNIQUE(customer_id, idempotency_key)
# ============================================================

def test_same_customer_cannot_insert_duplicate_idempotency_key(ws):
    shared_key = token_hex(16)

    first_id, _ = create_order(
        ws,
        idempotency_key=shared_key,
    )

    with pytest.raises(IntegrityError):
        create_order(
            ws,
            idempotency_key=shared_key,
            request_hash="b" * 64,
        )

    with ws["factory"]() as session:
        row = OrderRepository(
            session
        ).find_by_idempotency_key(
            customer_id=ws["customer_a"],
            idempotency_key=shared_key,
        )

    assert row["id"] == first_id
    assert row["request_hash"] == "a" * 64


# ============================================================
# TEST 07: UNIQUE(code)
# ============================================================

def test_order_code_must_be_unique(ws):
    shared_code = f"TMP-{token_hex(12)}"

    first_id, _ = create_order(
        ws,
        temporary_code=shared_code,
    )

    with pytest.raises(IntegrityError):
        create_order(
            ws,
            customer_id=ws["customer_b"],
            temporary_code=shared_code,
        )

    with ws["factory"]() as session:
        found = OrderRepository(
            session
        ).get_by_code(shared_code)

    assert found["id"] == first_id


# ============================================================
# TEST 08: UNIQUE(order_id, product_id)
# ============================================================

def test_duplicate_product_line_is_rejected(ws):
    order_id, _ = create_order(ws)

    first_id = create_order_item(
        ws,
        order_id,
    )

    with pytest.raises(IntegrityError):
        create_order_item(
            ws,
            order_id,
            quantity=3,
        )

    with ws["factory"]() as session:
        rows = OrderRepository(
            session
        ).list_items(order_id)

    assert len(rows) == 1
    assert rows[0]["id"] == first_id
    assert rows[0]["quantity"] == 2


# ============================================================
# TEST 09: MariaDB CHECK
# ============================================================

def test_invalid_quantity_and_unit_price_fail_database_check(ws):
    order_id, _ = create_order(ws)

    for quantity, unit_price in [
        (0, Decimal("12000000.00")),
        (1, Decimal(0)),
    ]:
        with pytest.raises(DatabaseError) as caught:
            create_order_item(
                ws,
                order_id,
                quantity=quantity,
                unit_price=unit_price,
            )

        # MariaDB CHECK constraint violation.
        assert caught.value.orig.args[0] == 4025

    with ws["factory"]() as session:
        assert OrderRepository(
            session
        ).list_items(order_id) == []



# ============================================================
# TEST 10: Caller transaction rollback
# ============================================================

def test_order_and_items_rollback_together(ws):
    data = order_args(ws)

    with pytest.raises(
        RuntimeError,
        match="cancel transaction",
    ), ws["factory"]() as session, session.begin():
        repo = OrderRepository(session)

        order_id = repo.create_pending(
            **data
        )

        repo.create_item(
            order_id=order_id,
            product_id=ws["product_a"],
            product_name=ws["name_a"],
            brand_name=ws["brand_name"],
            quantity=2,
            unit_price=Decimal("12000000.00"),
        )

        raise RuntimeError("cancel transaction")

    with ws["factory"]() as session:
        repo = OrderRepository(session)

        found = repo.find_by_idempotency_key(
            customer_id=ws["customer_a"],
            idempotency_key=data["idempotency_key"],
        )

    assert found is None


# ============================================================
# TEST 11: Customer pagination and ownership filtering
# ============================================================

def test_list_customer_orders_isolated_and_stably_paginated(ws):
    first_id, _ = create_order(ws)
    second_id, _ = create_order(ws)
    third_id, _ = create_order(ws)

    other_id, _ = create_order(
        ws,
        customer_id=ws["customer_b"],
    )

    with ws["factory"]() as session:
        repo = OrderRepository(session)

        first_page = repo.list_customer_orders(
            customer_id=ws["customer_a"],
            limit=2,
            offset=0,
        )

        second_page = repo.list_customer_orders(
            customer_id=ws["customer_a"],
            limit=2,
            offset=2,
        )

    assert [
        row["id"] for row in first_page
    ] == [third_id, second_id]

    assert [
        row["id"] for row in second_page
    ] == [first_id]

    assert other_id not in {
        row["id"]
        for row in first_page + second_page
    }


# ============================================================
# TEST 12: Product changes do not rewrite snapshots
# ============================================================

def test_product_changes_do_not_change_order_item_snapshot(ws):
    order_id, _ = create_order(ws)

    create_order_item(
        ws,
        order_id,
    )

    ws["db"].execute(
        text("""
            UPDATE products
            SET name = :name,
                sell_price = :price
            WHERE id = :product_id
        """),
        {
            "name": "Changed Product Name",
            "price": Decimal("15000000.00"),
            "product_id": ws["product_a"],
        },
    )

    with ws["factory"]() as session:
        item = OrderRepository(
            session
        ).list_items(order_id)[0]

    assert item["product_name"] == ws["name_a"]
    assert item["brand_name"] == ws["brand_name"]
    assert item["unit_price"] == Decimal("12000000.00")
    assert item["unit_cost"] is None


# ============================================================
# TEST 13: Creating PENDING does not affect inventory
# ============================================================

def test_pending_order_creation_does_not_reduce_stock(ws):
    def inventory_snapshot():
        rows = ws["db"].execute(
            text("""
                SELECT id, stock, cost_price
                FROM products
                WHERE id IN (:a, :b)
                ORDER BY id
            """),
            {
                "a": ws["product_a"],
                "b": ws["product_b"],
            },
        ).mappings().all()

        return [dict(row) for row in rows]

    before = inventory_snapshot()

    order_id, _ = create_order(ws)

    create_order_item(
        ws,
        order_id,
    )

    with ws["factory"]() as session, session.begin():
        OrderRepository(session).create_item(
            order_id=order_id,
            product_id=ws["product_b"],
            product_name=ws["name_b"],
            brand_name=ws["brand_name"],
            quantity=1,
            unit_price=Decimal("8000000.00"),
        )

    after = inventory_snapshot()

    assert before == after
    assert len(after) == 2

    with ws["factory"]() as session:
        row = OrderRepository(session).get_by_id(order_id)

    assert row["status"] == "PENDING"
