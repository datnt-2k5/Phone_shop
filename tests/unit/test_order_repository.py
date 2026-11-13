
"""Task 49 / US09-T02: Order Repository unit tests."""

from datetime import datetime
from decimal import Decimal

import pytest

from repositories.order_repository import OrderRepository

NOW = datetime(2026, 11, 13, 1, 0)

ORDER_ROW = {
    "id": 7,
    "code": "ORD-000007",
    "customer_id": 12,
    "idempotency_key": "checkout-key-001",
    "request_hash": "a" * 64,
    "status": "PENDING",
    "receiver_name": "Nguyen Van A",
    "receiver_phone": "0912345678",
    "receiver_address": "Cao Lanh, Dong Thap",
    "note": None,
    "total_amount": Decimal("25000000.00"),
    "created_at": NOW,
    "confirmed_at": None,
    "completed_at": None,
    "cancelled_at": None,
    "cancelled_by": None,
    "cancel_reason": None,
    "updated_at": NOW,
}

ITEM_ROW = {
    "id": 30,
    "order_id": 7,
    "product_id": 9,
    "product_name": "Phone A",
    "brand_name": "Brand A",
    "quantity": 2,
    "unit_price": Decimal("10000000.00"),
    "unit_cost": None,
}


class FakeResult:
    def __init__(
        self,
        *,
        row=None,
        rows=None,
        lastrowid=7,
        rowcount=1,
    ):
        self.row = row
        self.rows = [] if rows is None else rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, result=None):
        self.result = (
            FakeResult() if result is None else result
        )
        self.calls = []

    def execute(self, statement, params):
        self.calls.append(
            (statement.text, dict(params))
        )
        return self.result

    def commit(self):
        raise AssertionError(
            "Repository không được tự commit."
        )

    def rollback(self):
        raise AssertionError(
            "Repository không được tự rollback."
        )


def pending_args():
    return {
        "temporary_code": "TMP-ABC123",
        "customer_id": 12,
        "idempotency_key": "checkout-key-001",
        "request_hash": "a" * 64,
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "Giao trong gio hanh chinh",
        "total_amount": Decimal("25000000.00"),
        "now_utc": NOW,
    }


def item_args():
    return {
        "order_id": 7,
        "product_id": 9,
        "product_name": "Phone A",
        "brand_name": "Brand A",
        "quantity": 2,
        "unit_price": Decimal("10000000.00"),
    }


def test_get_by_id_returns_a_copy():
    session = FakeSession(
        FakeResult(row=ORDER_ROW)
    )
    repo = OrderRepository(session)

    result = repo.get_by_id(7)

    assert result == ORDER_ROW
    assert result is not ORDER_ROW

    sql, params = session.calls[0]

    assert "FROM orders" in sql
    assert "WHERE id = :order_id" in sql
    assert params == {"order_id": 7}


def test_get_missing_order_returns_none():
    session = FakeSession()
    repo = OrderRepository(session)

    assert repo.get_by_id(999) is None


def test_get_by_code_uses_bound_parameter():
    session = FakeSession(
        FakeResult(row=ORDER_ROW)
    )
    repo = OrderRepository(session)

    result = repo.get_by_code("ORD-000007")

    sql, params = session.calls[0]

    assert result == ORDER_ROW
    assert "WHERE code = :code" in sql
    assert params == {"code": "ORD-000007"}


def test_idempotency_lookup_is_scoped_to_customer():
    session = FakeSession(
        FakeResult(row=ORDER_ROW)
    )
    repo = OrderRepository(session)

    result = repo.find_by_idempotency_key(
        customer_id=12,
        idempotency_key="checkout-key-001",
    )

    sql, params = session.calls[0]

    assert result == ORDER_ROW
    assert "customer_id = :customer_id" in sql
    assert "idempotency_key = :idempotency_key" in sql

    assert params == {
        "customer_id": 12,
        "idempotency_key": "checkout-key-001",
    }


def test_customer_listing_is_stably_paginated():
    rows = [
        dict(ORDER_ROW),
        {**ORDER_ROW, "id": 6},
    ]

    session = FakeSession(
        FakeResult(rows=rows)
    )
    repo = OrderRepository(session)

    result = repo.list_customer_orders(
        customer_id=12,
        limit=2,
        offset=3,
    )

    sql, params = session.calls[0]

    assert result == rows
    assert result[0] is not rows[0]
    assert "WHERE customer_id = :customer_id" in sql
    assert "ORDER BY created_at DESC, id DESC" in sql

    assert params == {
        "customer_id": 12,
        "limit": 2,
        "offset": 3,
    }


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (True, 0),
        (10, -1),
        (10, True),
    ],
)
def test_invalid_pagination_rejected_without_sql(
    limit,
    offset,
):
    session = FakeSession()
    repo = OrderRepository(session)

    with pytest.raises(ValueError):
        repo.list_customer_orders(
            customer_id=12,
            limit=limit,
            offset=offset,
        )

    assert session.calls == []


def test_create_pending_binds_all_values():
    session = FakeSession(
        FakeResult(lastrowid=55)
    )
    repo = OrderRepository(session)

    result = repo.create_pending(
        **pending_args()
    )

    sql, params = session.calls[0]

    assert result == 55
    assert "INSERT INTO orders" in sql
    assert "'PENDING'" in sql
    assert ":request_hash" in sql
    assert ":total_amount" in sql
    assert "confirmed_at" not in sql
    assert "unit_cost" not in sql

    assert params == {
        "code": "TMP-ABC123",
        "customer_id": 12,
        "idempotency_key": "checkout-key-001",
        "request_hash": "a" * 64,
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "Giao trong gio hanh chinh",
        "total_amount": Decimal("25000000.00"),
        "now_utc": NOW,
    }


def test_create_pending_requires_inserted_id():
    session = FakeSession(
        FakeResult(lastrowid=None)
    )
    repo = OrderRepository(session)

    with pytest.raises(RuntimeError):
        repo.create_pending(**pending_args())


def test_update_code_uses_bound_values():
    session = FakeSession(
        FakeResult(rowcount=1)
    )
    repo = OrderRepository(session)

    assert repo.update_code(
        order_id=7,
        code="ORD-2026-000007",
    )

    sql, params = session.calls[0]

    assert "UPDATE orders" in sql
    assert "status = 'PENDING'" in sql

    assert params == {
        "order_id": 7,
        "code": "ORD-2026-000007",
    }


def test_update_missing_order_returns_false():
    session = FakeSession(
        FakeResult(rowcount=0)
    )
    repo = OrderRepository(session)

    assert not repo.update_code(
        order_id=999,
        code="ORD-MISSING",
    )


def test_create_item_saves_snapshot_without_cost():
    session = FakeSession(
        FakeResult(lastrowid=30)
    )
    repo = OrderRepository(session)

    result = repo.create_item(
        **item_args()
    )

    sql, params = session.calls[0]

    assert result == 30
    assert "INSERT INTO order_items" in sql
    assert "product_name" in sql
    assert "brand_name" in sql
    assert "unit_price" in sql
    assert "unit_cost" in sql
    assert "NULL" in sql

    assert params == item_args()


def test_create_item_requires_inserted_id():
    session = FakeSession(
        FakeResult(lastrowid=None)
    )
    repo = OrderRepository(session)

    with pytest.raises(RuntimeError):
        repo.create_item(**item_args())


def test_list_items_returns_snapshot_copies():
    session = FakeSession(
        FakeResult(rows=[ITEM_ROW])
    )
    repo = OrderRepository(session)

    result = repo.list_items(7)

    sql, params = session.calls[0]

    assert result == [ITEM_ROW]
    assert result[0] is not ITEM_ROW
    assert "FROM order_items" in sql
    assert "WHERE order_id = :order_id" in sql
    assert "ORDER BY id ASC" in sql
    assert params == {"order_id": 7}


def test_empty_order_items_returns_empty_list():
    session = FakeSession(
        FakeResult(rows=[])
    )
    repo = OrderRepository(session)

    assert repo.list_items(999) == []


def test_idempotency_lookup_never_embeds_user_input():
    session = FakeSession()
    repo = OrderRepository(session)

    suspicious_key = "abc' OR 1=1 --"

    repo.find_by_idempotency_key(
        customer_id=12,
        idempotency_key=suspicious_key,
    )

    sql, params = session.calls[0]

    assert suspicious_key not in sql
    assert params["idempotency_key"] == suspicious_key
    assert ":idempotency_key" in sql
