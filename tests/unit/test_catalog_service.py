
"""Task 34: Unit Test CatalogService, validation and permissions."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.catalog_service import CatalogService
from services.permissions import Permission
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
DB_TIME = NOW.replace(tzinfo=None)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeGuard:
    def __init__(self):
        self.permissions = []
        self.deny = None

    def run_allowed(self, *, session_store, permission, action):
        self.permissions.append(permission)
        if self.deny:
            raise AppError(self.deny, "Không có quyền.")
        return action(FakeSession())


class FakeBrands:
    def __init__(self):
        self.data = {
            1: {
                "id": 1,
                "name": "Apple",
                "created_at": DB_TIME,
            }
        }
        self.created = []
        self.renamed = []
        self.force_error = None
        self.locked = False

    def list_brands(self, *, limit=100, offset=0):
        return list(self.data.values())[offset:offset + limit]

    def get_by_id(self, brand_id, *, for_update=False):
        # Ghi nhận đã từng yêu cầu khóa trong lần thao tác này.
        # Lần đọc lại không khóa sẽ không xóa trạng thái ghi nhận.
        self.locked = self.locked or for_update

        row = self.data.get(brand_id)
        return dict(row) if row else None

    def find_by_name(self, name, *, exclude_id=None):
        for row in self.data.values():
            if (
                row["name"].casefold() == name.casefold()
                and row["id"] != exclude_id
            ):
                return dict(row)
        return None

    def create(self, *, name, now_utc):
        if self.force_error is not None:
            raise self.force_error
        brand_id = max(self.data) + 1
        self.data[brand_id] = {
            "id": brand_id,
            "name": name,
            "created_at": now_utc,
        }
        self.created.append(name)
        return brand_id

    def update_name(self, *, brand_id, name):
        self.data[brand_id]["name"] = name
        self.renamed.append((brand_id, name))
        return True


class FakeSuppliers:
    def __init__(self):
        self.data = {
            5: {
                "id": 5,
                "name": "NCC Một",
                "phone": "0912345678",
                "email": "one@example.test",
                "address": "Hà Nội",
                "is_active": True,
            }
        }
        self.created = []
        self.edited = []
        self.locked = False

    def list_suppliers(
        self, *, is_active=None, limit=100, offset=0
    ):
        rows = list(self.data.values())
        if is_active is not None:
            rows = [
                row for row in rows
                if bool(row["is_active"]) == is_active
            ]
        return rows[offset:offset + limit]

    def get_by_id(self, supplier_id, *, for_update=False):
        # Giữ bằng chứng đã gọi FOR UPDATE.
        self.locked = self.locked or for_update

        row = self.data.get(supplier_id)
        return dict(row) if row else None

    def create(self, **values):
        supplier_id = max(self.data) + 1
        self.data[supplier_id] = {
            "id": supplier_id,
            **values,
            "is_active": True,
        }
        self.created.append(values)
        return supplier_id

    def update_details(self, *, supplier_id, **values):
        self.data[supplier_id].update(values)
        self.edited.append(values)
        return True


class FakeSupplierStatus:
    def __init__(self, suppliers):
        self.suppliers = suppliers
        self.calls = []

    def deactivate(self, *, supplier_id):
        self.calls.append(supplier_id)
        self.suppliers.data[supplier_id]["is_active"] = False
        return True


@pytest.fixture
def env():
    brands = FakeBrands()
    suppliers = FakeSuppliers()
    statuses = FakeSupplierStatus(suppliers)
    guard = FakeGuard()
    store = object()

    service = CatalogService(
        session_factory=FakeSession,
        clock=FixedClock(NOW),
        protected_actions=guard,
        brand_repository_factory=lambda session: brands,
        supplier_repository_factory=lambda session: suppliers,
        status_repository_factory=lambda session: statuses,
    )

    return SimpleNamespace(
        service=service,
        brands=brands,
        suppliers=suppliers,
        statuses=statuses,
        guard=guard,
        store=store,
    )


def test_public_brand_list_does_not_require_admin(env):
    rows = env.service.list_brands()
    assert rows[0]["name"] == "Apple"
    assert env.guard.permissions == []


def test_public_get_brand(env):
    assert env.service.get_brand(brand_id=1)["name"] == "Apple"


@pytest.mark.parametrize("brand_id", [0, -1, True, "1"])
def test_get_brand_rejects_invalid_id(env, brand_id):
    with pytest.raises(AppError) as caught:
        env.service.get_brand(brand_id=brand_id)
    assert caught.value.error_code == "VALIDATION_ERROR"


def test_get_missing_brand_returns_not_found(env):
    with pytest.raises(AppError) as caught:
        env.service.get_brand(brand_id=999)
    assert caught.value.error_code == "NOT_FOUND"


@pytest.mark.parametrize(
    "values",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"offset": "1"},
    ],
)
def test_brand_pagination_rejects_invalid_inputs(env, values):
    with pytest.raises(AppError) as caught:
        env.service.list_brands(**values)
    assert caught.value.error_code == "VALIDATION_ERROR"


def test_create_brand_normalizes_name_and_uses_clock(env):
    row = env.service.save_brand(
        session_store=env.store,
        name="  Sam   Sung  ",
    )
    assert row["name"] == "Sam Sung"
    assert row["created_at"] == DB_TIME
    assert env.guard.permissions == [Permission.MANAGE_BRANDS]


def test_create_duplicate_brand_is_rejected(env):
    with pytest.raises(AppError) as caught:
        env.service.save_brand(
            session_store=env.store,
            name="apple",
        )
    assert caught.value.error_code == "BRAND_EXISTS"
    assert env.brands.created == []


def test_rename_brand_checks_duplicate(env):
    env.brands.create(name="Samsung", now_utc=DB_TIME)

    with pytest.raises(AppError) as caught:
        env.service.save_brand(
            session_store=env.store,
            brand_id=1,
            name="Samsung",
        )

    assert caught.value.error_code == "BRAND_EXISTS"
    assert env.brands.data[1]["name"] == "Apple"


def test_rename_brand_locks_row(env):
    result = env.service.save_brand(
        session_store=env.store,
        brand_id=1,
        name="Apple Premium",
    )
    assert result["name"] == "Apple Premium"
    assert env.brands.locked
    assert env.brands.renamed == [(1, "Apple Premium")]


def test_same_brand_name_does_not_write_again(env):
    result = env.service.save_brand(
        session_store=env.store,
        brand_id=1,
        name="Apple",
    )
    assert result["name"] == "Apple"
    assert env.brands.renamed == []


@pytest.mark.parametrize("name", [None, "", "   ", 123, "X" * 101])
def test_brand_name_validation(env, name):
    with pytest.raises(AppError) as caught:
        env.service.save_brand(
            session_store=env.store,
            name=name,
        )
    assert caught.value.error_code == "VALIDATION_ERROR"


def test_unique_database_error_is_mapped(env):
    env.brands.force_error = IntegrityError(
        "INSERT brands",
        {},
        Exception(
            1062,
            "Duplicate entry 'secret' for key 'uq_brands_name'",
        ),
    )

    with pytest.raises(AppError) as caught:
        env.service.save_brand(
            session_store=env.store,
            name="New Brand",
        )

    assert caught.value.error_code == "BRAND_EXISTS"
    assert "secret" not in caught.value.message


def test_other_integrity_error_is_not_mislabeled(env):
    env.brands.force_error = IntegrityError(
        "INSERT brands",
        {},
        Exception(1452, "Foreign key fails"),
    )

    with pytest.raises(IntegrityError):
        env.service.save_brand(
            session_store=env.store,
            name="Brand Other",
        )


def test_create_supplier_normalizes_contact_fields(env):
    row = env.service.save_supplier(
        session_store=env.store,
        name="  NCC   Hai ",
        phone=" 0987654321 ",
        email="  TEST@EXAMPLE.COM ",
        address="  TP   Hồ Chí Minh  ",
    )
    assert row["name"] == "NCC Hai"
    assert row["phone"] == "0987654321"
    assert row["email"] == "test@example.com"
    assert row["address"] == "TP Hồ Chí Minh"
    assert bool(row["is_active"])
    assert env.guard.permissions == [Permission.MANAGE_SUPPLIERS]


def test_update_supplier_preserves_inactive_state(env):
    env.suppliers.data[5]["is_active"] = False
    row = env.service.save_supplier(
        session_store=env.store,
        supplier_id=5,
        name="NCC Đổi Tên",
        phone=None,
        email=None,
        address=None,
    )
    assert row["name"] == "NCC Đổi Tên"
    assert not row["is_active"]
    assert env.suppliers.locked


def test_list_supplier_requires_permission(env):
    rows = env.service.list_suppliers(
        session_store=env.store,
        is_active=True,
    )
    assert rows[0]["id"] == 5
    assert env.guard.permissions == [Permission.MANAGE_SUPPLIERS]


def test_get_supplier_requires_permission(env):
    row = env.service.get_supplier(
        session_store=env.store,
        supplier_id=5,
    )
    assert row["name"] == "NCC Một"
    assert env.guard.permissions == [Permission.MANAGE_SUPPLIERS]


@pytest.mark.parametrize("status", [1, 0, "true", []])
def test_supplier_status_filter_rejects_wrong_type(env, status):
    with pytest.raises(AppError) as caught:
        env.service.list_suppliers(
            session_store=env.store,
            is_active=status,
        )
    assert caught.value.error_code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", "X" * 151),
        ("phone", "123"),
        ("phone", "012345678a"),
        ("phone", 123),
        ("email", "not-an-email"),
        ("email", "a" * 101),
        ("address", "X" * 256),
    ],
)
def test_invalid_supplier_fields_are_rejected(
    env, field, value
):
    values = {
        "name": "NCC Hợp Lệ",
        "phone": "0912345678",
        "email": "ok@example.test",
        "address": "Hà Nội",
    }
    values[field] = value

    with pytest.raises(AppError) as caught:
        env.service.save_supplier(
            session_store=env.store,
            **values,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert env.suppliers.created == []


def test_discontinue_supplier_preserves_contact_data(env):
    before = dict(env.suppliers.data[5])

    row = env.service.discontinue_supplier(
        session_store=env.store,
        supplier_id=5,
    )

    assert row["is_active"] is False
    assert env.suppliers.locked
    assert env.statuses.calls == [5]

    for field in ("id", "name", "phone", "email", "address"):
        assert row[field] == before[field]


def test_discontinue_is_idempotent(env):
    env.service.discontinue_supplier(
        session_store=env.store,
        supplier_id=5,
    )
    env.service.discontinue_supplier(
        session_store=env.store,
        supplier_id=5,
    )
    assert env.statuses.calls == [5]


def test_discontinue_missing_supplier_returns_not_found(env):
    with pytest.raises(AppError) as caught:
        env.service.discontinue_supplier(
            session_store=env.store,
            supplier_id=999,
        )
    assert caught.value.error_code == "NOT_FOUND"


@pytest.mark.parametrize(
    "error_code",
    ["FORBIDDEN", "UNAUTHORIZED", "ACCOUNT_LOCKED"],
)
def test_denied_account_cannot_change_supplier(env, error_code):
    env.guard.deny = error_code

    with pytest.raises(AppError) as caught:
        env.service.discontinue_supplier(
            session_store=env.store,
            supplier_id=5,
        )

    assert caught.value.error_code == error_code
    assert env.statuses.calls == []


def test_import_precheck_accepts_active_supplier(env):
    row = CatalogService.require_active_for_import(
        repository=env.suppliers,
        supplier_id=5,
    )
    assert row["is_active"]
    assert env.suppliers.locked


def test_import_precheck_rejects_inactive_supplier(env):
    env.suppliers.data[5]["is_active"] = False

    with pytest.raises(AppError) as caught:
        CatalogService.require_active_for_import(
            repository=env.suppliers,
            supplier_id=5,
        )

    assert caught.value.error_code == "SUPPLIER_INACTIVE"


def test_import_precheck_rejects_missing_supplier(env):
    with pytest.raises(AppError) as caught:
        CatalogService.require_active_for_import(
            repository=env.suppliers,
            supplier_id=999,
        )
    assert caught.value.error_code == "NOT_FOUND"
