
"""Task 36: Catalog duplicate/role/history regression using phone_shop_test."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.brand_repository import BrandRepository
from repositories.product_repository import ProductRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.catalog_service import CatalogService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
DB_TIME = NOW.replace(tzinfo=None)
PASSWORD = "MatKhau123!"


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
def env(test_db: Connection):
    """Existing test_db fixture rolls back all writes on phone_shop_test."""
    assert test_db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    def factory():
        return Session(
            bind=test_db,
            join_transaction_mode="create_savepoint",
        )

    auth = AuthService(session_factory=factory)
    users = {}

    for role in ("admin", "customer"):
        email = f"us06t36_{role}_{token_hex(7)}@example.test"
        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task36 {role}",
            phone="0912345678",
        )
        users[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    test_db.execute(
        text("UPDATE users SET role = 'ADMIN' WHERE id = :id"),
        {"id": users["admin"]["id"]},
    )

    for user in users.values():
        auth.login(
            email=user["email"],
            password=PASSWORD,
            session_store=user["store"],
        )

    return {
        "db": test_db,
        "factory": factory,
        "auth": auth,
        "admin": users["admin"],
        "customer": users["customer"],
        "service": CatalogService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def fresh_name(prefix):
    return f"T36 {prefix} {token_hex(7)}"


def create_brand(env, *, name=None, actor="admin"):
    return env["service"].save_brand(
        session_store=env[actor]["store"],
        name=name or fresh_name("Brand"),
    )


def create_supplier(env, *, name=None, actor="admin"):
    return env["service"].save_supplier(
        session_store=env[actor]["store"],
        name=name or fresh_name("Supplier"),
        phone="0912345678",
        email="test@example.com",
        address="Địa chỉ kiểm thử Task 36",
    )


def read_supplier(env, supplier_id):
    with env["factory"]() as session:
        return SupplierRepository(session).get_by_id(supplier_id)


def stop(env, supplier_id, *, actor="admin"):
    return env["service"].discontinue_supplier(
        session_store=env[actor]["store"],
        supplier_id=supplier_id,
    )


@pytest.mark.parametrize(
    "variant",
    ["exact", "lower", "spaces"],
)
def test_duplicate_brand_name_never_creates_second_row(env, variant):
    name = fresh_name("Brand")
    original = create_brand(env, name=name)

    duplicate = {
        "exact": name,
        "lower": name.lower(),
        "spaces": f"  {name.replace(' ', '   ')}  ",
    }[variant]

    with pytest.raises(AppError) as caught:
        create_brand(env, name=duplicate)

    assert caught.value.error_code == "BRAND_EXISTS"
    assert "name" in caught.value.errors

    with env["factory"]() as session:
        matches = session.execute(
            text("SELECT id FROM brands WHERE name = :name"),
            {"name": name},
        ).all()

    assert len(matches) == 1
    assert matches[0][0] == original["id"]


@pytest.mark.parametrize("variant", ["exact", "lower"])
def test_duplicate_brand_rename_preserves_original(env, variant):
    original = create_brand(env)
    target = create_brand(env)

    duplicate = (
        target["name"]
        if variant == "exact"
        else target["name"].lower()
    )

    with pytest.raises(AppError) as caught:
        env["service"].save_brand(
            session_store=env["admin"]["store"],
            brand_id=original["id"],
            name=duplicate,
        )

    assert caught.value.error_code == "BRAND_EXISTS"
    assert env["service"].get_brand(
        brand_id=original["id"]
    ) == original


def test_database_unique_constraint_stops_bypass_of_service(env):
    brand = create_brand(env)

    with (
        pytest.raises(IntegrityError),
        env["factory"]() as session,
        session.begin(),
    ):
        BrandRepository(session).create(
            name=brand["name"],
            now_utc=DB_TIME,
        )

    with env["factory"]() as session:
        row = BrandRepository(session).get_by_id(brand["id"])

    assert row == brand


def test_renaming_brand_preserves_product_foreign_key(env):
    brand = create_brand(env)

    with env["factory"]() as session, session.begin():
        product_id = ProductRepository(session).create(
            sku=f"T36-{token_hex(7)}",
            name=fresh_name("Phone"),
            brand_id=brand["id"],
            storage="128GB",
            color="Black",
            sell_price=Decimal("15000000.00"),
            now_utc=DB_TIME,
            updated_by=None,
        )

    edited = env["service"].save_brand(
        session_store=env["admin"]["store"],
        brand_id=brand["id"],
        name=fresh_name("Renamed"),
    )

    with env["factory"]() as session:
        product = ProductRepository(session).get_by_id(
            product_id
        )

    assert edited["id"] == brand["id"]
    assert product["brand_id"] == brand["id"]
    assert product["stock"] == 0


@pytest.mark.parametrize(
    "action",
    [
        "create_brand",
        "edit_brand",
        "create_supplier",
        "edit_supplier",
        "list_suppliers",
        "get_supplier",
        "stop_supplier",
    ],
)
def test_customer_is_denied_every_admin_catalog_action(env, action):
    brand = create_brand(env)
    supplier = create_supplier(env)
    customer = env["customer"]["store"]
    service = env["service"]

    operations = {
        "create_brand": lambda: service.save_brand(
            session_store=customer,
            name=fresh_name("Forbidden Brand"),
        ),
        "edit_brand": lambda: service.save_brand(
            session_store=customer,
            brand_id=brand["id"],
            name=fresh_name("Forbidden Rename"),
        ),
        "create_supplier": lambda: service.save_supplier(
            session_store=customer,
            name=fresh_name("Forbidden Supplier"),
        ),
        "edit_supplier": lambda: service.save_supplier(
            session_store=customer,
            supplier_id=supplier["id"],
            name="Forbidden Change",
        ),
        "list_suppliers": lambda: service.list_suppliers(
            session_store=customer,
        ),
        "get_supplier": lambda: service.get_supplier(
            session_store=customer,
            supplier_id=supplier["id"],
        ),
        "stop_supplier": lambda: service.discontinue_supplier(
            session_store=customer,
            supplier_id=supplier["id"],
        ),
    }

    with pytest.raises(AppError) as caught:
        operations[action]()

    assert caught.value.error_code == "FORBIDDEN"
    assert service.get_brand(brand_id=brand["id"]) == brand
    assert read_supplier(env, supplier["id"]) == supplier


@pytest.mark.parametrize("action", ["brand", "supplier"])
def test_guest_cannot_write_catalog(env, action):
    guest = Store()

    if action == "brand":
        execute = lambda: env["service"].save_brand(
            session_store=guest,
            name=fresh_name("Guest"),
        )
    else:
        execute = lambda: env["service"].save_supplier(
            session_store=guest,
            name=fresh_name("Guest"),
        )

    with pytest.raises(AppError) as caught:
        execute()

    assert caught.value.error_code == "UNAUTHORIZED"


def test_admin_demotion_is_enforced_without_relogin(env):
    supplier = create_supplier(env)

    env["db"].execute(
        text("UPDATE users SET role = 'CUSTOMER' WHERE id = :id"),
        {"id": env["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        stop(env, supplier["id"])

    assert caught.value.error_code == "FORBIDDEN"
    assert read_supplier(env, supplier["id"]) == supplier


def test_locked_admin_loses_session_and_cannot_stop(env):
    supplier = create_supplier(env)

    env["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task36'
            WHERE id = :id
        """),
        {"id": env["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        stop(env, supplier["id"])

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert env["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None
    assert read_supplier(env, supplier["id"]) == supplier


def test_super_admin_can_manage_both_catalog_categories(env):
    env["db"].execute(
        text("UPDATE users SET role = 'SUPER_ADMIN' WHERE id = :id"),
        {"id": env["customer"]["id"]},
    )

    brand = create_brand(env, actor="customer")
    supplier = create_supplier(env, actor="customer")
    result = stop(
        env,
        supplier["id"],
        actor="customer",
    )

    assert brand["id"] > 0
    assert not bool(result["is_active"])
    assert read_supplier(
        env, supplier["id"]
    )["id"] == supplier["id"]


def test_discontinue_preserves_old_receipt_and_supplier_details(env):
    supplier = create_supplier(env)
    receipt_code = f"T36-RC-{token_hex(7)}"

    receipt = env["db"].execute(
        text("""
            INSERT INTO import_receipts (
                code, supplier_id, import_date, total_amount,
                note, created_by, created_at
            ) VALUES (
                :code, :supplier_id, :now, :amount,
                :note, :actor, :now
            )
        """),
        {
            "code": receipt_code,
            "supplier_id": supplier["id"],
            "now": DB_TIME,
            "amount": Decimal("700000.00"),
            "note": "History test Task36",
            "actor": env["admin"]["id"],
        },
    )

    receipt_id = int(receipt.lastrowid)
    stopped = stop(env, supplier["id"])

    assert not bool(stopped["is_active"])

    for field in (
        "id", "name", "phone", "email", "address"
    ):
        assert stopped[field] == supplier[field]

    existing = env["db"].execute(
        text("""
            SELECT code, supplier_id, total_amount
            FROM import_receipts
            WHERE id = :id
        """),
        {"id": receipt_id},
    ).mappings().one()

    assert existing["code"] == receipt_code
    assert existing["supplier_id"] == supplier["id"]
    assert existing["total_amount"] == Decimal("700000.00")
    assert read_supplier(
        env, supplier["id"]
    )["id"] == supplier["id"]


def test_inactive_supplier_blocks_new_import_but_history_remains(env):
    supplier = create_supplier(env)
    stop(env, supplier["id"])

    with (
        pytest.raises(AppError) as caught,
        env["factory"]() as session,
        session.begin(),
    ):
        CatalogService.require_active_for_import(
            repository=SupplierRepository(session),
            supplier_id=supplier["id"],
        )

    assert caught.value.error_code == "SUPPLIER_INACTIVE"
    assert read_supplier(
        env, supplier["id"]
    )["id"] == supplier["id"]


def test_discontinue_is_idempotent_and_supplier_can_still_be_edited(env):
    supplier = create_supplier(env)

    first = stop(env, supplier["id"])
    second = stop(env, supplier["id"])

    assert first == second

    renamed = env["service"].save_supplier(
        session_store=env["admin"]["store"],
        supplier_id=supplier["id"],
        name="T36 Supplier Edited",
        phone=None,
        email=None,
        address=None,
    )

    assert renamed["id"] == supplier["id"]
    assert not bool(renamed["is_active"])
    assert not bool(
        read_supplier(env, supplier["id"])["is_active"]
    )


def test_deactivation_error_rolls_back_and_keeps_history(env):
    supplier = create_supplier(env)

    class FailingStatusRepository(SupplierStatusRepository):
        def deactivate(self, *, supplier_id):
            super().deactivate(supplier_id=supplier_id)
            raise RuntimeError("forced rollback")

    service = CatalogService(
        session_factory=env["factory"],
        auth_service=env["auth"],
        clock=FixedClock(NOW),
        status_repository_factory=FailingStatusRepository,
    )

    with pytest.raises(RuntimeError, match="forced rollback"):
        service.discontinue_supplier(
            session_store=env["admin"]["store"],
            supplier_id=supplier["id"],
        )

    assert read_supplier(env, supplier["id"]) == supplier


def test_supplier_active_filter_keeps_inactive_records_queryable(env):
    active = create_supplier(env)
    inactive = create_supplier(env)
    stop(env, inactive["id"])

    active_rows = env["service"].list_suppliers(
        session_store=env["admin"]["store"],
        is_active=True,
    )
    inactive_rows = env["service"].list_suppliers(
        session_store=env["admin"]["store"],
        is_active=False,
    )

    assert active["id"] in {
        r["id"] for r in active_rows
    }
    assert inactive["id"] not in {
        r["id"] for r in active_rows
    }
    assert inactive["id"] in {
        r["id"] for r in inactive_rows
    }


def test_supplier_names_are_not_falsely_treated_as_unique(env):
    name = fresh_name("Supplier")

    a = create_supplier(env, name=name)
    b = create_supplier(env, name=name)

    assert a["id"] != b["id"]
