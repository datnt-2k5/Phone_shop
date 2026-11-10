
"""Task 34: Catalog Service integration on phone_shop_test."""

from datetime import UTC, datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.catalog_service import CatalogService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
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
def ws(test_db: Connection):
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
        email = f"t34_{role}_{token_hex(7)}@example.test"

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Task34 {role}",
            phone="0912345678",
        )

        users[role] = {
            "id": registered.user_id,
            "email": email,
            "store": Store(),
        }

    test_db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
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
        "catalog": CatalogService(
            session_factory=factory,
            auth_service=auth,
            clock=FixedClock(NOW),
        ),
    }


def brand_name():
    return f"Task34 Brand {token_hex(7)}"


def supplier_name():
    return f"Task34 Supplier {token_hex(7)}"


def create_brand(ws, *, name=None, actor="admin"):
    return ws["catalog"].save_brand(
        session_store=ws[actor]["store"],
        name=name or brand_name(),
    )


def create_supplier(ws, *, name=None, actor="admin"):
    return ws["catalog"].save_supplier(
        session_store=ws[actor]["store"],
        name=name or supplier_name(),
        phone="0912345678",
        email="test@example.com",
        address="Địa chỉ kiểm thử",
    )


def stop(ws, supplier_id, *, actor="admin"):
    return ws["catalog"].discontinue_supplier(
        session_store=ws[actor]["store"],
        supplier_id=supplier_id,
    )


def read_supplier(ws, supplier_id):
    with ws["factory"]() as session:
        return SupplierRepository(session).get_by_id(
            supplier_id
        )


def test_admin_can_create_and_list_brand(ws):
    created = create_brand(ws)

    assert created["created_at"] == DB_TIME

    listed = ws["catalog"].list_brands()
    assert any(
        item["id"] == created["id"]
        for item in listed
    )

    detail = ws["catalog"].get_brand(
        brand_id=created["id"]
    )
    assert detail == created


def test_brand_name_is_unique_ignoring_case(ws):
    name = brand_name()
    create_brand(ws, name=name)

    with pytest.raises(AppError) as caught:
        create_brand(ws, name=name.lower())

    assert caught.value.error_code == "BRAND_EXISTS"
    assert "name" in caught.value.errors


def test_brand_rename_does_not_break_product_fk(ws):
    original_name = brand_name()
    brand = create_brand(ws, name=original_name)

    with ws["factory"]() as session, session.begin():
        product_id = ProductRepository(session).create(
            sku=f"T34-{token_hex(6)}",
            name=f"Phone {token_hex(6)}",
            brand_id=brand["id"],
            storage="128GB",
            color="Black",
            sell_price=Decimal("12000000.00"),
            now_utc=DB_TIME,
            updated_by=None,
        )

    renamed = ws["catalog"].save_brand(
        session_store=ws["admin"]["store"],
        brand_id=brand["id"],
        name=original_name + " Updated",
    )

    assert renamed["id"] == brand["id"]

    with ws["factory"]() as session:
        product = ProductRepository(session).get_by_id(
            product_id
        )

    assert product["brand_id"] == brand["id"]
    assert product["stock"] == 0


def test_rename_to_existing_brand_is_rejected(ws):
    first = create_brand(ws)
    second = create_brand(ws)

    with pytest.raises(AppError) as caught:
        ws["catalog"].save_brand(
            session_store=ws["admin"]["store"],
            brand_id=first["id"],
            name=second["name"],
        )

    assert caught.value.error_code == "BRAND_EXISTS"
    assert ws["catalog"].get_brand(
        brand_id=first["id"]
    )["name"] == first["name"]


def test_customer_cannot_create_or_rename_brand(ws):
    original = create_brand(ws)

    with pytest.raises(AppError) as caught:
        create_brand(ws, actor="customer")

    assert caught.value.error_code == "FORBIDDEN"

    with pytest.raises(AppError) as caught:
        ws["catalog"].save_brand(
            session_store=ws["customer"]["store"],
            brand_id=original["id"],
            name=brand_name(),
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_admin_can_create_and_update_supplier(ws):
    original = create_supplier(ws)

    assert bool(original["is_active"]) is True

    updated = ws["catalog"].save_supplier(
        session_store=ws["admin"]["store"],
        supplier_id=original["id"],
        name="  Nhà   Cung Cấp Mới ",
        phone="0987654321",
        email=" NEW@EXAMPLE.COM ",
        address="  Đồng   Tháp  ",
    )

    assert updated["id"] == original["id"]
    assert updated["name"] == "Nhà Cung Cấp Mới"
    assert updated["phone"] == "0987654321"
    assert updated["email"] == "new@example.com"
    assert updated["address"] == "Đồng Tháp"
    assert bool(updated["is_active"]) is True


def test_duplicate_supplier_names_are_allowed_by_schema(ws):
    name = supplier_name()
    first = create_supplier(ws, name=name)
    second = create_supplier(ws, name=name)

    assert first["id"] != second["id"]


def test_discontinue_supplier_keeps_history(ws):
    supplier = create_supplier(ws)

    code = f"T34-RC-{token_hex(6)}"

    # Tạo phiếu nhập lịch sử chỉ trong phone_shop_test.
    receipt = ws["db"].execute(
        text("""
            INSERT INTO import_receipts (
                code,
                supplier_id,
                import_date,
                total_amount,
                note,
                created_by,
                created_at
            )
            VALUES (
                :code,
                :supplier_id,
                :now,
                :amount,
                :note,
                :user_id,
                :now
            )
        """),
        {
            "code": code,
            "supplier_id": supplier["id"],
            "now": DB_TIME,
            "amount": Decimal("1000000.00"),
            "note": "Phiếu nhập kiểm thử Task34",
            "user_id": ws["admin"]["id"],
        },
    )

    receipt_id = int(receipt.lastrowid)
    before = read_supplier(ws, supplier["id"])

    stopped = stop(ws, supplier["id"])

    assert bool(stopped["is_active"]) is False

    for key in (
        "id", "name", "phone", "email", "address"
    ):
        assert stopped[key] == before[key]

    saved_receipt = ws["db"].execute(
        text("""
            SELECT supplier_id
            FROM import_receipts
            WHERE id = :id
        """),
        {"id": receipt_id},
    ).scalar_one()

    assert saved_receipt == supplier["id"]
    assert read_supplier(ws, supplier["id"]) is not None


def test_inactive_supplier_is_rejected_for_future_import(ws):
    supplier = create_supplier(ws)
    stop(ws, supplier["id"])

    with (
        pytest.raises(AppError) as caught,
        ws["factory"]() as session,
        session.begin(),
    ):
        CatalogService.require_active_for_import(
            repository=SupplierRepository(session),
            supplier_id=supplier["id"],
        )


    assert caught.value.error_code == "SUPPLIER_INACTIVE"


def test_active_supplier_is_accepted_for_import(ws):
    supplier = create_supplier(ws)

    with ws["factory"]() as session, session.begin():
        result = CatalogService.require_active_for_import(
            repository=SupplierRepository(session),
            supplier_id=supplier["id"],
        )

    assert result["id"] == supplier["id"]
    assert bool(result["is_active"]) is True


def test_discontinue_twice_is_safe(ws):
    supplier = create_supplier(ws)

    first = stop(ws, supplier["id"])
    second = stop(ws, supplier["id"])

    assert first == second
    assert read_supplier(ws, supplier["id"]) == first


def test_editing_inactive_supplier_does_not_reactivate(ws):
    supplier = create_supplier(ws)
    stop(ws, supplier["id"])

    result = ws["catalog"].save_supplier(
        session_store=ws["admin"]["store"],
        supplier_id=supplier["id"],
        name="Đã ngừng hợp tác",
        phone=None,
        email=None,
        address=None,
    )

    assert bool(result["is_active"]) is False


def test_customer_cannot_read_or_stop_supplier(ws):
    supplier = create_supplier(ws)

    with pytest.raises(AppError) as caught:
        ws["catalog"].list_suppliers(
            session_store=ws["customer"]["store"],
        )
    assert caught.value.error_code == "FORBIDDEN"

    with pytest.raises(AppError) as caught:
        ws["catalog"].get_supplier(
            session_store=ws["customer"]["store"],
            supplier_id=supplier["id"],
        )
    assert caught.value.error_code == "FORBIDDEN"

    with pytest.raises(AppError) as caught:
        stop(ws, supplier["id"], actor="customer")
    assert caught.value.error_code == "FORBIDDEN"

    assert bool(read_supplier(
        ws, supplier["id"]
    )["is_active"]) is True


def test_role_demotion_revokes_supplier_permission(ws):
    supplier = create_supplier(ws)

    ws["db"].execute(
        text("""
            UPDATE users
            SET role = 'CUSTOMER'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        stop(ws, supplier["id"])

    assert caught.value.error_code == "FORBIDDEN"
    assert bool(read_supplier(
        ws, supplier["id"]
    )["is_active"]) is True


def test_locked_admin_cannot_discontinue(ws):
    supplier = create_supplier(ws)

    ws["db"].execute(
        text("""
            UPDATE users
            SET status = 'LOCKED',
                lock_reason = 'Task34 test'
            WHERE id = :id
        """),
        {"id": ws["admin"]["id"]},
    )

    with pytest.raises(AppError) as caught:
        stop(ws, supplier["id"])

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert ws["admin"]["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None
    assert bool(read_supplier(
        ws, supplier["id"]
    )["is_active"]) is True


def test_super_admin_can_discontinue_supplier(ws):
    supplier = create_supplier(ws)

    ws["db"].execute(
        text("""
            UPDATE users
            SET role = 'SUPER_ADMIN'
            WHERE id = :id
        """),
        {"id": ws["customer"]["id"]},
    )

    result = stop(
        ws, supplier["id"], actor="customer"
    )

    assert bool(result["is_active"]) is False


def test_guest_cannot_discontinue_supplier(ws):
    supplier = create_supplier(ws)

    with pytest.raises(AppError) as caught:
        ws["catalog"].discontinue_supplier(
            session_store=Store(),
            supplier_id=supplier["id"],
        )

    assert caught.value.error_code == "UNAUTHORIZED"


def test_discontinue_database_failure_rolls_back(ws):
    supplier = create_supplier(ws)

    class BrokenStatusRepository(SupplierStatusRepository):
        def deactivate(self, *, supplier_id):
            super().deactivate(supplier_id=supplier_id)
            raise RuntimeError("Simulated SQL failure")

    service = CatalogService(
        session_factory=ws["factory"],
        auth_service=ws["auth"],
        clock=FixedClock(NOW),
        status_repository_factory=BrokenStatusRepository,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated SQL failure",
    ):
        service.discontinue_supplier(
            session_store=ws["admin"]["store"],
            supplier_id=supplier["id"],
        )

    assert bool(read_supplier(
        ws, supplier["id"]
    )["is_active"]) is True


def test_invalid_supplier_data_does_not_create_record(ws):
    name = supplier_name()

    with pytest.raises(AppError) as caught:
        ws["catalog"].save_supplier(
            session_store=ws["admin"]["store"],
            name=name,
            phone="123",
            email="invalid",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"

    rows = ws["catalog"].list_suppliers(
        session_store=ws["admin"]["store"],
    )
    assert all(row["name"] != name for row in rows)


def test_supplier_status_filter(ws):
    active = create_supplier(ws)
    inactive = create_supplier(ws)

    stop(ws, inactive["id"])

    active_rows = ws["catalog"].list_suppliers(
        session_store=ws["admin"]["store"],
        is_active=True,
    )
    inactive_rows = ws["catalog"].list_suppliers(
        session_store=ws["admin"]["store"],
        is_active=False,
    )

    active_ids = {row["id"] for row in active_rows}
    inactive_ids = {row["id"] for row in inactive_rows}

    assert active["id"] in active_ids
    assert inactive["id"] not in active_ids
    assert inactive["id"] in inactive_ids
    assert active["id"] not in inactive_ids
