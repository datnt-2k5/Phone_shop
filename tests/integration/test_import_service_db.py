
"""Task 38: atomic warehouse import against isolated phone_shop_test."""

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
from repositories.stock_movement_repository import StockMovementRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.auth_service import AuthService
from services.import_service import ImportService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
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
    credentials = {}

    for role in ("admin", "customer"):
        email = f"t38_{role}_{token_hex(7)}@example.test"

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task 38 {role}",
            phone="0912345678",
        )

        credentials[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    # Chỉ thay role trong database kiểm thử.
    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": credentials["admin"]["id"]},
    )

    for user in credentials.values():
        auth.login(
            email=user["email"],
            password=PASSWORD,
            session_store=user["store"],
        )

    # Tạo hãng, nhà cung cấp và hai sản phẩm kiểm thử.
    with factory() as session, session.begin():
        brand_id = BrandRepository(session).create(
            name=f"T38 Brand {token_hex(7)}",
            now_utc=DB_NOW,
        )

        supplier_id = SupplierRepository(session).create(
            name=f"T38 Supplier {token_hex(7)}",
        )

        product_ids = []

        for i in range(2):
            product_id = ProductRepository(session).create(
                sku=f"T38-{token_hex(6)}",
                name=f"T38 Phone {i} {token_hex(5)}",
                brand_id=brand_id,
                storage="128GB",
                color="Black",
                sell_price=Decimal("8000000.00"),
                now_utc=DB_NOW,
            )

            product_ids.append(product_id)

    return {
        "db": test_db,
        "factory": factory,
        "auth": auth,
        "admin": credentials["admin"],
        "customer": credentials["customer"],
        "supplier_id": supplier_id,
        "products": product_ids,
        "service": ImportService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def line(product_id, quantity, price):
    return {
        "product_id": product_id,
        "quantity": quantity,
        "import_price": price,
    }


def do_import(
    env,
    items,
    *,
    supplier_id=None,
    actor="admin",
    service=None,
):
    return (service or env["service"]).create_import(
        session_store=env[actor]["store"],
        supplier_id=supplier_id or env["supplier_id"],
        items=items,
    )


def product(env, product_id):
    return env["db"].execute(
        text("""
            SELECT stock, cost_price
            FROM products
            WHERE id = :id
        """),
        {"id": product_id},
    ).mappings().one()


def movements(env, product_id):
    return env["db"].execute(
        text("""
            SELECT
                type,
                ref_type,
                ref_id,
                operation_key,
                quantity_change,
                stock_after,
                created_by
            FROM stock_movements
            WHERE product_id = :id
            ORDER BY id
        """),
        {"id": product_id},
    ).mappings().all()


def test_two_products_update_stock_cost_and_history_atomically(env):
    a, b = env["products"]

    receipt = do_import(
        env,
        [
            line(b, 3, "5500000.00"),
            line(a, 2, "5000000.00"),
        ],
    )

    assert receipt["code"] == f"PN{receipt['id']:08d}"

    assert receipt["total_amount"] == Decimal(
        "26500000.00"
    )

    saved = env["db"].execute(
        text("""
            SELECT code, total_amount, created_by
            FROM import_receipts
            WHERE id = :id
        """),
        {"id": receipt["id"]},
    ).mappings().one()

    assert saved["code"] == receipt["code"]
    assert saved["total_amount"] == receipt["total_amount"]
    assert saved["created_by"] == env["admin"]["id"]

    assert product(env, a)["stock"] == 2
    assert product(env, b)["stock"] == 3

    assert product(env, a)["cost_price"] == Decimal(
        "5000000.00"
    )
    assert product(env, b)["cost_price"] == Decimal(
        "5500000.00"
    )

    for pid, qty in ((a, 2), (b, 3)):
        history = movements(env, pid)

        assert len(history) == 1
        assert history[0]["type"] == "IMPORT"
        assert history[0]["quantity_change"] == qty
        assert history[0]["stock_after"] == qty

        assert history[0]["operation_key"] == (
            f"IMPORT:{receipt['id']}:{pid}"
        )


def test_second_import_calculates_weighted_average(env):
    a = env["products"][0]

    do_import(
        env,
        [line(a, 10, "5000000.00")],
    )

    do_import(
        env,
        [line(a, 5, "5500000.00")],
    )

    assert product(env, a)["stock"] == 15
    assert product(env, a)["cost_price"] == Decimal(
        "5166666.67"
    )

    assert [
        m["stock_after"]
        for m in movements(env, a)
    ] == [10, 15]


def test_customer_is_denied_without_mutations(env):
    a = env["products"][0]

    with pytest.raises(AppError) as caught:
        do_import(
            env,
            [line(a, 2, "100.00")],
            actor="customer",
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert product(env, a)["stock"] == 0
    assert movements(env, a) == []


def test_inactive_supplier_is_blocked(env):
    a = env["products"][0]

    with env["factory"]() as session, session.begin():
        assert SupplierStatusRepository(session).deactivate(
            supplier_id=env["supplier_id"]
        )

    with pytest.raises(AppError) as caught:
        do_import(
            env,
            [line(a, 1, "100.00")],
        )

    assert caught.value.error_code == "SUPPLIER_INACTIVE"
    assert product(env, a)["stock"] == 0
    assert movements(env, a) == []


def test_late_write_failure_rolls_back_receipt_items_stock_and_movement(env):
    a = env["products"][0]

    class FailingMovementRepository(StockMovementRepository):
        def record_import(self, **kwargs):
            super().record_import(**kwargs)

            raise RuntimeError("simulate movement failure")

    broken = ImportService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        movement_repository_factory=FailingMovementRepository,
    )

    before = env["db"].execute(
        text("SELECT COUNT(*) FROM import_receipts")
    ).scalar_one()

    with pytest.raises(
        RuntimeError,
        match="simulate movement failure",
    ):
        do_import(
            env,
            [line(a, 2, "123.45")],
            service=broken,
        )

    after = env["db"].execute(
        text("SELECT COUNT(*) FROM import_receipts")
    ).scalar_one()

    assert after == before
    assert product(env, a)["stock"] == 0
    assert product(env, a)["cost_price"] == Decimal("0.00")
    assert movements(env, a) == []


def test_import_rejects_missing_product_without_receipt(env):
    before = env["db"].execute(
        text("SELECT COUNT(*) FROM import_receipts")
    ).scalar_one()

    with pytest.raises(AppError) as caught:
        do_import(
            env,
            [line(2_147_483_647, 1, "100.00")],
        )

    assert caught.value.error_code == "NOT_FOUND"

    after = env["db"].execute(
        text("SELECT COUNT(*) FROM import_receipts")
    ).scalar_one()

    assert after == before


def test_operation_key_has_unique_constraint(env):
    a = env["products"][0]

    receipt = do_import(
        env,
        [line(a, 1, "100.00")],
    )

    assert movements(env, a)[0]["operation_key"] == (
        f"IMPORT:{receipt['id']}:{a}"
    )

    assert len(movements(env, a)) == 1
