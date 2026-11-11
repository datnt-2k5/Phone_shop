
"""Task 39: read-only warehouse history against phone_shop_test MariaDB."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.brand_repository import BrandRepository
from repositories.product_repository import ProductRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.auth_service import AuthService
from services.import_service import ImportService
from services.warehouse_query_service import WarehouseQueryService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 11, 2, 0, tzinfo=UTC)
DB_NOW = NOW.replace(tzinfo=None)
PASSWORD = "MatKhau123!"


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


@pytest.fixture
def env(test_db: Connection):
    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)
    people = {}

    for role in ("admin", "customer"):
        email = f"t39_{role}_{token_hex(7)}@example.test"
        user = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task39 {role}",
            phone="0912345678",
        )
        people[role] = {
            "id": user.user_id,
            "email": email,
            "store": Store(),
        }

    test_db.execute(
        text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
        {"id": people["admin"]["id"]},
    )

    for person in people.values():
        auth.login(
            email=person["email"],
            password=PASSWORD,
            session_store=person["store"],
        )

    with factory() as session, session.begin():
        brand_id = BrandRepository(session).create(
            name=f"T39 Brand {token_hex(7)}",
            now_utc=DB_NOW,
        )
        supplier_id = SupplierRepository(session).create(
            name=f"T39 Supplier {token_hex(7)}",
        )

        products = {}
        for name, min_stock in (
            ("low", 3),
            ("ok", 1),
            ("out", 2),
        ):
            products[name] = ProductRepository(session).create(
                sku=f"T39-{token_hex(6)}",
                name=f"T39 Phone {name} {token_hex(5)}",
                brand_id=brand_id,
                storage="128GB",
                color="Black",
                sell_price=Decimal("8000000.00"),
                min_stock=min_stock,
                now_utc=DB_NOW,
            )

    imports = ImportService(
        session_factory=factory,
        auth_service=auth,
        clock=FixedClock(NOW),
    )

    first = imports.create_import(
        session_store=people["admin"]["store"],
        supplier_id=supplier_id,
        items=[
            {
                "product_id": products["low"],
                "quantity": 2,
                "import_price": "1000.00",
            },
            {
                "product_id": products["ok"],
                "quantity": 5,
                "import_price": "2000.00",
            },
        ],
    )

    second = imports.create_import(
        session_store=people["admin"]["store"],
        supplier_id=supplier_id,
        items=[
            {
                "product_id": products["low"],
                "quantity": 1,
                "import_price": "3000.00",
            }
        ],
    )

    return {
        "db": test_db,
        "factory": factory,
        "people": people,
        "supplier_id": supplier_id,
        "products": products,
        "first": first,
        "second": second,
        "service": WarehouseQueryService(
            session_factory=factory,
            auth_service=auth,
        ),
    }


def test_receipt_history_has_supplier_creator_and_newest_first(env):
    rows = env["service"].list_receipts(
        session_store=env["people"]["admin"]["store"],
        limit=2,
    )

    assert [row["id"] for row in rows] == [
        env["second"]["id"],
        env["first"]["id"],
    ]
    assert rows[0]["supplier_id"] == env["supplier_id"]
    assert rows[0]["supplier_name"].startswith("T39 Supplier")
    assert rows[0]["created_by_name"] == "Task39 admin"
    assert rows[0]["total_amount"] == Decimal("3000.00")


def test_receipt_history_is_paginated(env):
    store = env["people"]["admin"]["store"]

    first_page = env["service"].list_receipts(
        session_store=store,
        limit=1,
        offset=0,
    )
    second_page = env["service"].list_receipts(
        session_store=store,
        limit=1,
        offset=1,
    )

    assert first_page[0]["id"] == env["second"]["id"]
    assert second_page[0]["id"] == env["first"]["id"]


def test_receipt_details_include_immutable_item_snapshot(env):
    detail = env["service"].get_receipt(
        session_store=env["people"]["admin"]["store"],
        receipt_id=env["first"]["id"],
    )

    assert detail["receipt"]["code"] == env["first"]["code"]
    assert detail["receipt"]["total_amount"] == Decimal("12000.00")
    assert len(detail["items"]) == 2

    by_id = {
        row["product_id"]: row
        for row in detail["items"]
    }

    low = by_id[env["products"]["low"]]
    assert low["sku"].startswith("T39-")
    assert low["quantity"] == 2
    assert low["import_price"] == Decimal("1000.00")
    assert low["line_total"] == Decimal("2000.00")


def test_missing_receipt_is_not_found(env):
    with pytest.raises(AppError) as caught:
        env["service"].get_receipt(
            session_store=env["people"]["admin"]["store"],
            receipt_id=2_147_483_647,
        )

    assert caught.value.error_code == "NOT_FOUND"


def test_movements_can_filter_by_product_and_type(env):
    low = env["products"]["low"]

    rows = env["service"].list_movements(
        session_store=env["people"]["admin"]["store"],
        product_id=low,
        movement_type="import",
    )

    assert len(rows) == 2
    assert [row["stock_after"] for row in rows] == [3, 2]
    assert all(row["type"] == "IMPORT" for row in rows)
    assert rows[0]["operation_key"] == (
        f"IMPORT:{env['second']['id']}:{low}"
    )
    assert rows[0]["created_by_name"] == "Task39 admin"


def test_inventory_out_low_alert_and_all_filters(env):
    store = env["people"]["admin"]["store"]
    service = env["service"]

    out = service.list_inventory(session_store=store, level="OUT")
    low = service.list_inventory(session_store=store, level="LOW")
    alert = service.list_inventory(session_store=store, level="ALERT")
    all_rows = service.list_inventory(
        session_store=store, level="ALL"
    )

    ids = env["products"]

    assert ids["out"] in {row["id"] for row in out}
    assert ids["low"] in {row["id"] for row in low}
    assert ids["out"] not in {row["id"] for row in low}

    assert {ids["low"], ids["out"]} <= {
        row["id"] for row in alert
    }
    assert ids["ok"] not in {row["id"] for row in alert}

    assert {ids["low"], ids["ok"], ids["out"]} <= {
        row["id"] for row in all_rows
    }

    by_id = {
        row["id"]: row
        for row in all_rows
    }

    assert by_id[ids["low"]]["stock"] == 3
    assert by_id[ids["low"]]["min_stock"] == 3
    assert by_id[ids["low"]]["cost_price"] == Decimal("1666.67")
    assert by_id[ids["out"]]["stock_level"] == "OUT"
    assert by_id[ids["ok"]]["stock_level"] == "OK"


@pytest.mark.parametrize(
    "method,extra",
    [
        ("list_receipts", {}),
        ("get_receipt", {"receipt_id": 1}),
        ("list_movements", {}),
        ("list_inventory", {}),
    ],
)
@pytest.mark.parametrize(
    "actor,error",
    [
        ("customer", "FORBIDDEN"),
        ("guest", "UNAUTHORIZED"),
    ],
)
def test_customer_or_guest_cannot_read_warehouse(
    env, method, extra, actor, error
):
    store = (
        env["people"][actor]["store"]
        if actor != "guest"
        else Store()
    )

    with pytest.raises(AppError) as caught:
        getattr(env["service"], method)(
            session_store=store,
            **extra,
        )

    assert caught.value.error_code == error


def test_supplier_discontinued_does_not_hide_old_receipts(env):
    with env["factory"]() as session, session.begin():
        assert SupplierStatusRepository(session).deactivate(
            supplier_id=env["supplier_id"]
        )

    detail = env["service"].get_receipt(
        session_store=env["people"]["admin"]["store"],
        receipt_id=env["first"]["id"],
    )

    assert not bool(
        detail["receipt"]["supplier_is_active"]
    )
    assert len(detail["items"]) == 2


def test_discontinued_product_is_hidden_by_default_but_readable_on_demand(
    env,
):
    product_id = env["products"]["out"]

    env["db"].execute(
        text("""
            UPDATE products
            SET status = 'DISCONTINUED'
            WHERE id = :id
        """),
        {"id": product_id},
    )

    store = env["people"]["admin"]["store"]

    default = env["service"].list_inventory(
        session_store=store,
        level="OUT",
    )
    extended = env["service"].list_inventory(
        session_store=store,
        level="OUT",
        include_discontinued=True,
    )

    assert product_id not in {
        row["id"] for row in default
    }
    assert product_id in {
        row["id"] for row in extended
    }


def test_read_queries_do_not_mutate_stock_or_history(env):
    product_id = env["products"]["low"]

    before = env["db"].execute(
        text("""
            SELECT stock, cost_price
            FROM products
            WHERE id = :id
        """),
        {"id": product_id},
    ).mappings().one()

    before_count = env["db"].execute(
        text("""
            SELECT COUNT(*)
            FROM stock_movements
            WHERE product_id = :id
        """),
        {"id": product_id},
    ).scalar_one()

    store = env["people"]["admin"]["store"]

    env["service"].list_receipts(session_store=store)
    env["service"].get_receipt(
        session_store=store,
        receipt_id=env["first"]["id"],
    )
    env["service"].list_movements(
        session_store=store,
        product_id=product_id,
    )
    env["service"].list_inventory(session_store=store)

    after = env["db"].execute(
        text("""
            SELECT stock, cost_price
            FROM products
            WHERE id = :id
        """),
        {"id": product_id},
    ).mappings().one()

    after_count = env["db"].execute(
        text("""
            SELECT COUNT(*)
            FROM stock_movements
            WHERE product_id = :id
        """),
        {"id": product_id},
    ).scalar_one()

    assert dict(before) == dict(after)
    assert before_count == after_count
