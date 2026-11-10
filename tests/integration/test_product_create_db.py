
"""Task 30: authorized ProductCreateService with isolated MariaDB."""

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
from services.product_create_service import ProductCreateService
from utils.time_utils import FixedClock

PASSWORD = "MatKhau123!"
NOW = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)


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
    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    brand = test_db.execute(
        text("""
            INSERT INTO brands (name, created_at)
            VALUES (:name, :created_at)
        """),
        {
            "name": f"Task30 Brand {token_hex(6)}",
            "created_at": NOW.replace(tzinfo=None),
        },
    )

    auth = AuthService(session_factory=factory)
    accounts = {}

    for role in ("admin", "customer"):
        email = f"t30_{role}_{token_hex(8)}@example.test"
        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task30 {role}",
            phone="0912345678",
        )
        accounts[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    test_db.execute(
        text("""
            UPDATE users SET role = 'ADMIN'
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
        "service": ProductCreateService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def values(ws, actor="admin", **changes):
    return {
        "session_store": ws[actor]["store"],
        "sku": f"T30-{token_hex(6)}",
        "name": f"Phone {token_hex(6)}",
        "brand_id": ws["brand_id"],
        "storage": "128GB",
        "color": "Black",
        "sell_price": "15900000",
        "min_stock": 2,
        "description": "Demo",
        "image_url": None,
    } | changes


def test_admin_creates_product_with_zero_inventory(ws):
    created = ws["service"].create(**values(ws))

    assert created["status"] == "ACTIVE"
    assert created["stock"] == 0
    assert created["cost_price"] == Decimal("0.00")
    assert created["updated_by"] == ws["admin"]["id"]
    assert created["brand_id"] == ws["brand_id"]

    with ws["factory"]() as session:
        saved = ProductRepository(session).get_by_id(
            created["id"]
        )

    assert saved["sku"] == created["sku"]


def test_customer_cannot_create_product(ws):
    data = values(ws, actor="customer")

    with pytest.raises(AppError) as caught:
        ws["service"].create(**data)

    assert caught.value.error_code == "FORBIDDEN"

    with ws["factory"]() as session:
        assert (
            ProductRepository(session).get_by_sku(data["sku"])
            is None
        )


def test_super_admin_can_create_product(ws):
    ws["db"].execute(
        text("""
            UPDATE users SET role = 'SUPER_ADMIN'
            WHERE id = :user_id
        """),
        {"user_id": ws["customer"]["id"]},
    )

    created = ws["service"].create(
        **values(ws, actor="customer")
    )

    assert created["updated_by"] == ws["customer"]["id"]


def test_duplicate_sku_does_not_create_second_product(ws):
    first = values(ws, sku=f"T30-DUP-{token_hex(5)}")
    ws["service"].create(**first)

    second = values(ws, sku=first["sku"])

    with pytest.raises(AppError) as caught:
        ws["service"].create(**second)

    assert caught.value.error_code == "PRODUCT_EXISTS"


def test_duplicate_variant_does_not_create_second_product(ws):
    first = values(ws, name="Phone Same")
    ws["service"].create(**first)

    second = values(ws, name="Phone Same")

    with pytest.raises(AppError) as caught:
        ws["service"].create(**second)

    assert caught.value.error_code == "PRODUCT_EXISTS"


def test_nonexistent_brand_is_rejected(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].create(
            **values(ws, brand_id=999999999999)
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_locked_admin_cannot_create_product(ws):
    ws["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task30 test'
            WHERE id = :user_id
        """),
        {"user_id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        ws["service"].create(**values(ws))

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert ws["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None


def test_list_brands_requires_admin(ws):
    brands = ws["service"].list_brands(
        session_store=ws["admin"]["store"]
    )

    assert any(
        item["id"] == ws["brand_id"]
        for item in brands
    )

    with pytest.raises(AppError) as caught:
        ws["service"].list_brands(
            session_store=ws["customer"]["store"]
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_missing_session_cannot_create(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].create(
            **values(ws, session_store=Store())
        )

    assert caught.value.error_code == "UNAUTHORIZED"
