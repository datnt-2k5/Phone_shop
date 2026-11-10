
"""US05 Task 26: unit tests for ProductRepository SQL contracts."""

import re
from datetime import datetime
from decimal import Decimal

import pytest

from repositories.product_repository import ProductRepository

NOW = datetime(2026, 11, 9, 9, 0)


class FakeResult:
    def __init__(self, *, row=None, rows=None, lastrowid=19, rowcount=1):
        self.row = row
        self.rows = rows if rows is not None else []
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
        self.result = result or FakeResult()
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((statement.text, params))
        return self.result


def new_product_args():
    return {
        "sku": "T26-001",
        "name": "Demo Phone",
        "brand_id": 5,
        "storage": "128GB",
        "color": "Black",
        "sell_price": Decimal("12990000.00"),
        "min_stock": 2,
        "now_utc": NOW,
        "updated_by": 7,
    }


def test_create_forces_zero_stock_zero_cost_and_active():
    session = FakeSession()
    repo = ProductRepository(session)
    assert repo.create(**new_product_args()) == 19
    sql, params = session.calls[0]
    assert "0, 0, :min_stock, 'ACTIVE'" in sql
    assert "cost_price" in sql and "stock" in sql
    assert "cost_price" not in params and "stock" not in params
    assert params["sell_price"] == Decimal("12990000.00")


def test_create_returns_generated_primary_key():
    session = FakeSession(FakeResult(lastrowid=88))
    assert ProductRepository(session).create(**new_product_args()) == 88


def test_create_requires_generated_primary_key():
    session = FakeSession(FakeResult(lastrowid=None))
    with pytest.raises(RuntimeError, match="ID sản phẩm"):
        ProductRepository(session).create(**new_product_args())


def test_get_by_id_supports_for_update():
    session = FakeSession(FakeResult(row={"id": 4, "sku": "SKU4"}))
    item = ProductRepository(session).get_by_id(4, for_update=True)
    assert item == {"id": 4, "sku": "SKU4"}
    sql, params = session.calls[0]
    assert sql.rstrip().endswith("FOR UPDATE")
    assert params == {"product_id": 4}


def test_get_by_sku_is_parameterized():
    session = FakeSession(FakeResult(row={"id": 4}))
    assert ProductRepository(session).get_by_sku("ABC' OR 1=1") == {"id": 4}
    sql, params = session.calls[0]
    assert "WHERE p.sku = :sku" in sql
    assert "OR 1=1" not in sql
    assert params["sku"] == "ABC' OR 1=1"


def test_get_missing_product_returns_none():
    session = FakeSession()
    assert ProductRepository(session).get_by_id(999) is None


def test_find_variant_can_exclude_current_product():
    session = FakeSession(FakeResult(row={"id": 3, "sku": "A"}))
    item = ProductRepository(session).find_variant(
        brand_id=5,
        name="Demo",
        storage="128GB",
        color="Black",
        exclude_id=9,
    )
    assert item == {"id": 3, "sku": "A"}
    sql, params = session.calls[0]
    assert "id <> :exclude_id" in sql
    assert params["exclude_id"] == 9


def test_find_variant_without_exclusion_has_no_extra_filter():
    session = FakeSession()
    ProductRepository(session).find_variant(
        brand_id=5,
        name="Demo",
        storage="128GB",
        color="Black",
    )
    sql, params = session.calls[0]
    assert "exclude_id" not in sql
    assert "exclude_id" not in params


def test_update_details_whitelists_fields():
    session = FakeSession()
    updated = ProductRepository(session).update_details(
        product_id=3,
        name="Updated",
        sell_price=Decimal("100.00"),
        min_stock=4,
        description=None,
        image_url=None,
        now_utc=NOW,
        updated_by=7,
    )
    assert updated
    sql, params = session.calls[0]
    update_clause = sql.split(
        "SET", maxsplit=1
    )[1].split("WHERE", maxsplit=1)[0]
    for immutable in (
        "stock", "cost_price", "sku",
        "brand_id", "storage", "color",
    ):
        assert re.search(
            rf"\b{immutable}\s*=",
            update_clause,
        ) is None
    assert params["min_stock"] == 4


def test_update_nonexistent_product_returns_false():
    session = FakeSession(FakeResult(rowcount=0))
    assert not ProductRepository(session).update_details(
        product_id=404,
        name="X",
        sell_price=Decimal("10.00"),
        min_stock=0,
        description=None,
        image_url=None,
        now_utc=NOW,
        updated_by=None,
    )


@pytest.mark.parametrize(
    "bad_status",
    ["", "DELETED", "PENDING", None],
)
def test_status_rejects_unknown_values(bad_status):
    session = FakeSession()
    with pytest.raises(ValueError, match="Trạng thái"):
        ProductRepository(session).set_status(
            product_id=4,
            status=bad_status,
            now_utc=NOW,
            updated_by=7,
        )
    assert not session.calls


def test_set_status_updates_only_status_and_audit():
    session = FakeSession()
    assert ProductRepository(session).set_status(
        product_id=4,
        status="DISCONTINUED",
        now_utc=NOW,
        updated_by=7,
    )
    sql, params = session.calls[0]
    assert "SET status = :status" in sql
    assert params["status"] == "DISCONTINUED"


def test_admin_list_contains_cost_and_exact_stock():
    session = FakeSession(
        FakeResult(
            rows=[{"sku": "A", "cost_price": Decimal(0)}]
        )
    )
    assert ProductRepository(session).list_products() == [
        {"sku": "A", "cost_price": Decimal(0)}
    ]
    sql, _ = session.calls[0]
    assert "p.cost_price" in sql and "p.stock" in sql


def test_public_list_hides_cost_and_exact_stock():
    session = FakeSession()
    ProductRepository(session).list_public()
    sql, _ = session.calls[0]
    assert "p.cost_price" not in sql
    assert "p.stock > 0" in sql
    assert "p.stock," not in sql
    assert "p.status = 'ACTIVE'" in sql


def test_public_detail_hides_cost_and_discontinued():
    session = FakeSession()
    assert ProductRepository(session).get_public_by_id(11) is None
    sql, params = session.calls[0]
    assert "p.cost_price" not in sql
    assert "p.status = 'ACTIVE'" in sql
    assert params["product_id"] == 11


@pytest.mark.parametrize(
    "limit,offset",
    [
        (0, 0),
        (101, 0),
        (True, 0),
        (5, -1),
        (5, 2.0),
    ],
)
def test_invalid_pagination_is_rejected(limit, offset):
    session = FakeSession()
    with pytest.raises(ValueError):
        ProductRepository(session).list_products(
            limit=limit,
            offset=offset,
        )
    assert not session.calls
