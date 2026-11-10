
"""US05 Task 29: status, search, low-stock and access on phone_shop_test."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.product_management_service import ProductManagementService
from utils.time_utils import FixedClock

PASSWORD = "MatKhau123!"
CREATED = datetime(2026, 11, 10, 1, 0)
CHANGED = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


@pytest.fixture
def ws(test_db: Connection):
    """Every write is in the rollback transaction of phone_shop_test."""

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    brand = test_db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :now)
        """),
        {
            "name": f"Task29 Brand {token_hex(5)}",
            "now": CREATED,
        },
    )

    auth = AuthService(session_factory=factory)
    accounts = {}

    for role in ("admin", "customer"):
        email = (
            f"t29_{role}_{token_hex(8)}@example.test"
        )

        user = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task29 {role}",
            phone="0912345678",
        )

        accounts[role] = {
            "id": user.user_id,
            "email": email,
            "store": Store(),
        }

    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": accounts["admin"]["id"]},
    )

    for account in accounts.values():
        auth.login(
            email=account["email"],
            password=PASSWORD,
            session_store=account["store"],
        )

    return {
        "db": test_db,
        "factory": factory,
        "brand_id": int(brand.lastrowid),
        "admin": accounts["admin"],
        "customer": accounts["customer"],
        "service": ProductManagementService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(CHANGED),
        ),
    }


def create(
    ws,
    name,
    *,
    price=10000000,
    stock=0,
    minimum=2,
    status="ACTIVE",
):
    """Test-only stock/status setup, never run against phone_shop."""

    with ws["factory"]() as session, session.begin():
        product_id = ProductRepository(session).create(
            sku=f"T29-{token_hex(6)}",
            name=name,
            brand_id=ws["brand_id"],
            storage="128GB",
            color="Black",
            sell_price=Decimal(str(price)),
            min_stock=minimum,
            now_utc=CREATED,
            updated_by=None,
        )

    # Only test_db; production stock changes belong to US07.
    ws["db"].execute(
        text("""
            UPDATE products
            SET stock = :stock,
                status = :status
            WHERE id = :id
        """),
        {
            "stock": stock,
            "status": status,
            "id": product_id,
        },
    )

    return product_id


def read(ws, product_id):
    with ws["factory"]() as session:
        return ProductRepository(session).get_by_id(
            product_id
        )


def admin_search(ws, **kwargs):
    return ws["service"].search_admin(
        session_store=ws["admin"]["store"],
        **kwargs,
    )


def test_public_only_active_and_hides_cost_and_stock(ws):
    visible = create(
        ws,
        "Phone Public",
        stock=2,
    )
    hidden = create(
        ws,
        "Phone Hidden",
        status="DISCONTINUED",
    )

    page = ws["service"].search_public()

    ids = {
        item["id"]
        for item in page["items"]
    }

    assert visible in ids
    assert hidden not in ids
    assert page["total"] == 1

    assert all(
        "cost_price" not in item
        for item in page["items"]
    )

    assert all(
        "stock" not in item
        for item in page["items"]
    )

    assert "in_stock" in page["items"][0]


def test_public_search_matches_name_sku_and_brand(ws):
    product_id = create(
        ws,
        "Phone Alpha",
        stock=1,
    )

    sku = read(ws, product_id)["sku"]

    for keyword in (
        "Alpha",
        sku,
        "Task29 Brand",
    ):
        page = ws["service"].search_public(
            keyword=keyword
        )

        assert page["total"] == 1
        assert page["items"][0]["id"] == product_id


def test_percent_sign_in_keyword_is_literal(ws):
    special = create(
        ws,
        "Phone 100%",
        stock=1,
    )

    create(
        ws,
        "Phone 100A",
        stock=1,
    )

    page = ws["service"].search_public(
        keyword="100%"
    )

    assert [
        item["id"]
        for item in page["items"]
    ] == [special]


def test_public_brand_price_and_in_stock_filters(ws):
    inside = create(
        ws,
        "Budget Phone",
        price=11000000,
        stock=2,
    )

    create(
        ws,
        "Cheap Empty",
        price=9000000,
        stock=0,
    )

    create(
        ws,
        "Expensive Phone",
        price=20000000,
        stock=3,
    )

    page = ws["service"].search_public(
        brand_id=ws["brand_id"],
        min_price="10000000",
        max_price="15000000",
        only_in_stock=True,
    )

    assert [
        item["id"]
        for item in page["items"]
    ] == [inside]

    assert page["total"] == 1


def test_admin_can_filter_discontinued_and_see_inventory(ws):
    active = create(
        ws,
        "Active Phone",
        stock=4,
    )

    hidden = create(
        ws,
        "Old Phone",
        status="DISCONTINUED",
    )

    all_page = admin_search(ws)

    assert {
        item["id"]
        for item in all_page["items"]
    } == {active, hidden}

    assert "cost_price" in all_page["items"][0]
    assert "stock" in all_page["items"][0]
    assert "is_low_stock" in all_page["items"][0]

    page = admin_search(
        ws,
        status="DISCONTINUED",
    )

    assert [
        item["id"]
        for item in page["items"]
    ] == [hidden]


def test_low_stock_includes_equal_threshold(ws):
    low = create(
        ws,
        "Low Phone",
        stock=1,
        minimum=3,
    )

    equal = create(
        ws,
        "Equal Phone",
        stock=3,
        minimum=3,
    )

    create(
        ws,
        "Good Phone",
        stock=4,
        minimum=3,
    )

    page = admin_search(
        ws,
        status="ACTIVE",
        low_stock=True,
    )

    assert {
        item["id"]
        for item in page["items"]
    } == {low, equal}

    assert page["total"] == 2

    assert all(
        bool(item["is_low_stock"])
        for item in page["items"]
    )


def test_discontinue_and_restore_preserve_product_history(ws):
    product_id = create(
        ws,
        "Life Phone",
        stock=5,
        minimum=2,
    )

    before = read(ws, product_id)

    discontinued = ws["service"].set_status(
        session_store=ws["admin"]["store"],
        product_id=product_id,
        status="DISCONTINUED",
    )

    assert discontinued["status"] == "DISCONTINUED"
    assert discontinued["updated_by"] == ws["admin"]["id"]

    assert (
        discontinued["updated_at"]
        == CHANGED.replace(tzinfo=None)
    )

    for field in (
        "id",
        "sku",
        "brand_id",
        "stock",
        "cost_price",
        "sell_price",
    ):
        assert discontinued[field] == before[field]

    assert ws["service"].search_public(
        keyword="Life Phone"
    )["total"] == 0

    restored = ws["service"].set_status(
        session_store=ws["admin"]["store"],
        product_id=product_id,
        status="ACTIVE",
    )

    assert restored["status"] == "ACTIVE"

    assert ws["service"].search_public(
        keyword="Life Phone"
    )["total"] == 1


def test_repeated_status_is_idempotent(ws):
    product_id = create(
        ws,
        "Same Status",
    )

    before = read(ws, product_id)

    result = ws["service"].set_status(
        session_store=ws["admin"]["store"],
        product_id=product_id,
        status="ACTIVE",
    )

    assert result == before


def test_customer_cannot_search_admin_inventory_or_change_status(
    ws,
):
    product_id = create(
        ws,
        "Private Phone",
    )

    store = ws["customer"]["store"]

    with pytest.raises(AppError) as caught:
        ws["service"].search_admin(
            session_store=store
        )

    assert caught.value.error_code == "FORBIDDEN"

    before = read(ws, product_id)

    with pytest.raises(AppError) as caught:
        ws["service"].set_status(
            session_store=store,
            product_id=product_id,
            status="DISCONTINUED",
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert read(ws, product_id) == before


def test_locked_admin_cannot_change_status(ws):
    product_id = create(
        ws,
        "Locked Owner Phone",
    )

    before = read(ws, product_id)

    ws["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task29 test'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        ws["service"].set_status(
            session_store=ws["admin"]["store"],
            product_id=product_id,
            status="DISCONTINUED",
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    assert ws["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None

    assert read(ws, product_id) == before


def test_super_admin_can_change_status(ws):
    product_id = create(
        ws,
        "Super Admin Phone",
    )

    ws["db"].execute(
        text("""
            UPDATE users
            SET role = 'SUPER_ADMIN'
            WHERE id = :id
        """),
        {"id": ws["customer"]["id"]},
    )

    result = ws["service"].set_status(
        session_store=ws["customer"]["store"],
        product_id=product_id,
        status="DISCONTINUED",
    )

    assert result["status"] == "DISCONTINUED"
    assert result["updated_by"] == ws["customer"]["id"]


def test_not_found_and_bad_filters_do_not_modify_data(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].set_status(
            session_store=ws["admin"]["store"],
            product_id=999999999,
            status="DISCONTINUED",
        )

    assert caught.value.error_code == "NOT_FOUND"

    with pytest.raises(AppError) as caught:
        admin_search(
            ws,
            status="DELETED",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_sale_precheck_rejects_discontinued(ws):
    product_id = create(
        ws,
        "Do Not Sell",
        status="DISCONTINUED",
    )

    with (
        ws["factory"]() as session,
        session.begin(),
        pytest.raises(AppError) as caught,
    ):
        ProductManagementService.require_active_for_sale(
            repository=ProductRepository(session),
            product_id=product_id,
        )

    assert caught.value.error_code == "PRODUCT_DISCONTINUED"


def test_pagination_and_price_sort(ws):
    a = create(
        ws,
        "Low Price",
        price=9000000,
        stock=1,
    )

    b = create(
        ws,
        "High Price",
        price=20000000,
        stock=1,
    )

    first = ws["service"].search_public(
        sort_by="price_asc",
        limit=1,
        offset=0,
    )

    second = ws["service"].search_public(
        sort_by="price_asc",
        limit=1,
        offset=1,
    )

    assert first["total"] == 2
    assert second["total"] == 2
    assert first["items"][0]["id"] == a
    assert second["items"][0]["id"] == b
