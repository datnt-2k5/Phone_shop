
"""Task 42: stock adjustment integration on phone_shop_test only."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.brand_repository import BrandRepository
from repositories.product_repository import ProductRepository
from repositories.stock_adjustment_repository import StockAdjustmentRepository
from repositories.supplier_repository import SupplierRepository
from services.auth_service import AuthService
from services.import_service import ImportService
from services.stock_adjustment_service import StockAdjustmentService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 11, 4, 0, tzinfo=UTC)
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


def counted(product_id, actual):
    return {
        "product_id": product_id,
        "actual_quantity": actual,
    }


@pytest.fixture
def env(test_db: Connection):
    db = test_db

    assert db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    required = {
        "stock_adjustments",
        "stock_adjustment_items",
    }

    rows = db.execute(
        text("""
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME IN (
                  'stock_adjustments',
                  'stock_adjustment_items'
              )
        """)
    ).scalars().all()

    if not required.issubset(set(rows)):
        pytest.fail(
            "Chưa chạy migration Task 42 trên phone_shop_test."
        )

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)
    people = {}

    for role in ("admin", "customer"):
        email = f"t42_{role}_{token_hex(7)}@example.test"

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task42 {role}",
            phone="0912345678",
        )
        people[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
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
            name=f"T42 Brand {token_hex(7)}",
            now_utc=DB_NOW,
        )
        supplier_id = SupplierRepository(session).create(
            name=f"T42 Supplier {token_hex(7)}",
        )

        products = {}

        for key in ("a", "b", "c"):
            products[key] = ProductRepository(session).create(
                sku=f"T42-{token_hex(6)}",
                name=f"T42 Phone {key} {token_hex(5)}",
                brand_id=brand_id,
                storage="128GB",
                color="Black",
                sell_price=Decimal("1000000.00"),
                now_utc=DB_NOW,
            )

    importer = ImportService(
        session_factory=factory,
        auth_service=auth,
        clock=FixedClock(NOW),
    )

    importer.create_import(
        session_store=people["admin"]["store"],
        supplier_id=supplier_id,
        items=[
            {
                "product_id": products["a"],
                "quantity": 10,
                "import_price": "100.00",
            },
            {
                "product_id": products["b"],
                "quantity": 5,
                "import_price": "200.00",
            },
            {
                "product_id": products["c"],
                "quantity": 3,
                "import_price": "300.00",
            },
        ],
    )

    return {
        "db": db,
        "factory": factory,
        "auth": auth,
        "people": people,
        "products": products,
        "service": StockAdjustmentService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def run_adjustment(
    env,
    lines,
    *,
    reason="Kiểm kê Task 42",
    actor="admin",
    service=None,
):
    return (service or env["service"]).create_adjustment(
        session_store=env["people"][actor]["store"],
        reason=reason,
        items=lines,
    )


def stock(env, product_id):
    return env["db"].execute(
        text("""
            SELECT stock, cost_price
            FROM products
            WHERE id = :product_id
        """),
        {"product_id": product_id},
    ).mappings().one()


def movements(env, product_id):
    return env["db"].execute(
        text("""
            SELECT
                type, quantity_change, stock_after,
                ref_type, ref_id, operation_key, reason
            FROM stock_movements
            WHERE product_id = :product_id
              AND type = 'ADJUST'
            ORDER BY id
        """),
        {"product_id": product_id},
    ).mappings().all()


def adjustment_count(env):
    return env["db"].execute(
        text("SELECT COUNT(*) FROM stock_adjustments")
    ).scalar_one()


def adjustment_items(env, adjustment_id):
    return env["db"].execute(
        text("""
            SELECT
                product_id, old_quantity, actual_quantity,
                quantity_change, stock_after
            FROM stock_adjustment_items
            WHERE adjustment_id = :adjustment_id
            ORDER BY product_id
        """),
        {"adjustment_id": adjustment_id},
    ).mappings().all()


def test_positive_negative_and_zero_are_recorded_correctly(env):
    a, b, c = (
        env["products"]["a"],
        env["products"]["b"],
        env["products"]["c"],
    )

    result = run_adjustment(
        env,
        [
            counted(b, 7),
            counted(c, 3),
            counted(a, 8),
        ],
    )

    assert result["created"] is True
    assert result["code"] == f"ADJ{result['id']:08d}"
    assert result["changed_items"] == 2

    assert stock(env, a)["stock"] == 8
    assert stock(env, b)["stock"] == 7
    assert stock(env, c)["stock"] == 3

    assert stock(env, a)["cost_price"] == Decimal("100.00")
    assert stock(env, b)["cost_price"] == Decimal("200.00")
    assert stock(env, c)["cost_price"] == Decimal("300.00")

    items = adjustment_items(env, result["id"])
    assert [
        (
            item["product_id"],
            item["old_quantity"],
            item["actual_quantity"],
            item["quantity_change"],
        )
        for item in items
    ] == [
        (a, 10, 8, -2),
        (b, 5, 7, 2),
    ]

    assert movements(env, a)[0]["quantity_change"] == -2
    assert movements(env, b)[0]["quantity_change"] == 2
    assert movements(env, c) == []

    for product_id in (a, b):
        history = movements(env, product_id)
        assert len(history) == 1
        assert history[0]["ref_id"] == result["id"]
        assert history[0]["ref_type"] == "STOCK_ADJUSTMENT"
        assert history[0]["operation_key"] == (
            f"ADJUST:{result['id']}:{product_id}"
        )


def test_all_unchanged_does_not_create_adjustment(env):
    a = env["products"]["a"]
    b = env["products"]["b"]

    before = adjustment_count(env)

    result = run_adjustment(
        env,
        [counted(a, 10), counted(b, 5)],
    )

    assert result == {
        "created": False,
        "id": None,
        "code": None,
        "changed_items": 0,
    }
    assert adjustment_count(env) == before
    assert movements(env, a) == []
    assert movements(env, b) == []


def test_mixed_zero_and_changed_only_writes_changed_item(env):
    a = env["products"]["a"]
    b = env["products"]["b"]

    result = run_adjustment(
        env,
        [counted(a, 10), counted(b, 4)],
    )

    items = adjustment_items(env, result["id"])
    assert len(items) == 1
    assert items[0]["product_id"] == b
    assert items[0]["quantity_change"] == -1

    assert movements(env, a) == []
    assert len(movements(env, b)) == 1


def test_adjusting_to_zero_preserves_cost_price(env):
    a = env["products"]["a"]

    result = run_adjustment(
        env,
        [counted(a, 0)],
    )

    assert result["created"] is True
    assert stock(env, a)["stock"] == 0
    assert stock(env, a)["cost_price"] == Decimal("100.00")
    assert movements(env, a)[0]["quantity_change"] == -10
    assert movements(env, a)[0]["stock_after"] == 0


def test_customer_is_denied_without_changes(env):
    a = env["products"]["a"]
    before = adjustment_count(env)

    with pytest.raises(AppError) as caught:
        run_adjustment(
            env,
            [counted(a, 8)],
            actor="customer",
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert adjustment_count(env) == before
    assert stock(env, a)["stock"] == 10
    assert movements(env, a) == []


def test_invalid_reason_is_rejected_before_write(env):
    a = env["products"]["a"]
    before = adjustment_count(env)

    with pytest.raises(AppError) as caught:
        run_adjustment(
            env,
            [counted(a, 8)],
            reason="   ",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert adjustment_count(env) == before
    assert stock(env, a)["stock"] == 10


def test_missing_product_prevents_all_writes(env):
    a = env["products"]["a"]
    before = adjustment_count(env)

    with pytest.raises(AppError) as caught:
        run_adjustment(
            env,
            [
                counted(a, 8),
                counted(2_147_483_647, 1),
            ],
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert adjustment_count(env) == before
    assert stock(env, a)["stock"] == 10
    assert movements(env, a) == []


def test_second_movement_failure_rolls_back_everything(env):
    a = env["products"]["a"]
    b = env["products"]["b"]

    class FailSecondMovement(StockAdjustmentRepository):
        def __init__(self, session):
            super().__init__(session)
            self.calls = 0

        def record_movement(self, **kwargs):
            movement_id = super().record_movement(**kwargs)
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("simulate second ADJUST failure")
            return movement_id

    broken = StockAdjustmentService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        adjustment_repository_factory=FailSecondMovement,
    )

    before = adjustment_count(env)

    with pytest.raises(
        RuntimeError,
        match="second ADJUST failure",
    ):
        run_adjustment(
            env,
            [counted(a, 8), counted(b, 7)],
            service=broken,
        )

    assert adjustment_count(env) == before
    assert stock(env, a)["stock"] == 10
    assert stock(env, b)["stock"] == 5
    assert stock(env, a)["cost_price"] == Decimal("100.00")
    assert stock(env, b)["cost_price"] == Decimal("200.00")
    assert movements(env, a) == []
    assert movements(env, b) == []


def test_failed_code_update_rolls_back_header(env):
    a = env["products"]["a"]

    class FailCodeRepository(StockAdjustmentRepository):
        def update_code(self, *, adjustment_id, code):
            raise RuntimeError("simulate ADJUST code failure")

    broken = StockAdjustmentService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        adjustment_repository_factory=FailCodeRepository,
    )

    before = adjustment_count(env)

    with pytest.raises(RuntimeError, match="code failure"):
        run_adjustment(
            env,
            [counted(a, 8)],
            service=broken,
        )

    assert adjustment_count(env) == before
    assert stock(env, a)["stock"] == 10
    assert movements(env, a) == []


def test_duplicate_adjustment_operation_key_is_rejected(env):
    a = env["products"]["a"]

    result = run_adjustment(
        env,
        [counted(a, 8)],
    )

    with (
        env["factory"]() as session,
        session.begin(),
        pytest.raises(IntegrityError),
        session.begin_nested(),
    ):
        StockAdjustmentRepository(session).record_movement(
            adjustment_id=result["id"],
            product_id=a,
            quantity_change=-2,
            stock_after=8,
            reason="Trùng operation key",
            created_by=env["people"]["admin"]["id"],
            created_at=NOW,
        )

    assert len(movements(env, a)) == 1
    assert stock(env, a)["stock"] == 8


def test_check_constraint_rejects_inconsistent_delta(env):
    a = env["products"]["a"]
    c = env["products"]["c"]

    result = run_adjustment(
        env,
        [counted(a, 8)],
    )

    # Product C has no item yet in the adjustment.
    # Wrong arithmetic: old=3, actual=4, delta=2.
    with pytest.raises(DBAPIError), env["db"].begin_nested():
        env["db"].execute(
            text("""
                INSERT INTO stock_adjustment_items (
                    adjustment_id, product_id,
                    old_quantity, actual_quantity,
                    quantity_change, stock_after
                )
                VALUES (
                    :adjustment_id, :product_id,
                    3, 4, 2, 4
                )
            """),
            {
                "adjustment_id": result["id"],
                "product_id": c,
            },
        )

    assert len(adjustment_items(env, result["id"])) == 1
    assert stock(env, c)["stock"] == 3
