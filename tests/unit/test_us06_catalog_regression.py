
"""Task 36: US06 security, validation and immutable-history contracts."""

from inspect import signature

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from repositories.brand_repository import BrandRepository
from repositories.supplier_repository import SupplierRepository
from repositories.supplier_status_repository import SupplierStatusRepository
from services.catalog_service import CatalogService
from services.permissions import PERMISSION_MATRIX, Access, Permission, Role
from ui.route_guard import RouteStatus, check_route_access


class SqlResult:
    def __init__(self, *, row=None, rowcount=1, lastrowid=17):
        self.row = row
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def mappings(self):
        return self

    def first(self):
        return self.row


class SqlSession:
    def __init__(self, result=None):
        self.result = result if result is not None else SqlResult()
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((statement.text, dict(params)))
        return self.result


@pytest.mark.parametrize(
    "permission",
    [Permission.MANAGE_BRANDS, Permission.MANAGE_SUPPLIERS],
)
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.GUEST, Access.DENY),
        (Role.CUSTOMER, Access.DENY),
        (Role.ADMIN, Access.ALLOW),
        (Role.SUPER_ADMIN, Access.ALLOW),
    ],
)
def test_catalog_permissions_match_roles(permission, role, expected):
    assert PERMISSION_MATRIX[permission][role] == expected


@pytest.mark.parametrize(
    ("role", "status", "destination"),
    [
        ("GUEST", RouteStatus.LOGIN_REQUIRED, "/login"),
        ("CUSTOMER", RouteStatus.FORBIDDEN, None),
        ("ADMIN", RouteStatus.ALLOW, None),
        ("SUPER_ADMIN", RouteStatus.ALLOW, None),
    ],
)
def test_direct_catalog_url_is_guarded(role, status, destination):
    decision = check_route_access(route="/admin/catalog", role=role)
    assert decision.status == status
    assert decision.redirect_to == destination


def test_no_public_catalog_method_can_change_status_or_identity():
    supplier_params = signature(CatalogService.save_supplier).parameters
    assert "is_active" not in supplier_params
    assert "updated_by" not in supplier_params
    assert "role" not in supplier_params
    assert "session_store" in supplier_params
    assert "session_store" in signature(
        CatalogService.discontinue_supplier
    ).parameters
    assert not hasattr(CatalogService, "delete_supplier")
    assert not hasattr(CatalogService, "delete_brand")


def test_brand_name_normalization_is_consistent():
    assert CatalogService._required_text(
        "  Sam   Sung \n", field="name", max_length=100
    ) == "Sam Sung"


@pytest.mark.parametrize("name", [None, "", " \t ", 123, "X" * 101])
def test_invalid_brand_names_are_rejected(name):
    with pytest.raises(AppError) as caught:
        CatalogService._required_text(name, field="name", max_length=100)
    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "name" in caught.value.errors


@pytest.mark.parametrize(
    ("phone", "expected"),
    [(None, None), (" 0912345678 ", "0912345678")],
)
def test_valid_optional_supplier_phone(phone, expected):
    assert CatalogService._phone(phone) == expected


@pytest.mark.parametrize(
    "phone",
    ["123", "012345678a", "０１２３４５６７８９", 123],
)
def test_invalid_supplier_phone(phone):
    with pytest.raises(AppError) as caught:
        CatalogService._phone(phone)
    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "phone" in caught.value.errors


def test_supplier_email_is_normalized():
    assert CatalogService._email(" Admin@Example.COM ") == "admin@example.com"


@pytest.mark.parametrize(
    "email",
    ["no-at-sign", "a@b", "bad address@example.com", "x" * 101],
)
def test_invalid_supplier_email(email):
    with pytest.raises(AppError) as caught:
        CatalogService._email(email)
    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "email" in caught.value.errors


@pytest.mark.parametrize("key", ["uq_brands_name", "UQ_BRANDS_NAME"])
def test_brand_unique_constraint_is_recognized_without_leaking_data(key):
    error = IntegrityError(
        "INSERT INTO brands ...",
        {},
        Exception(1062, f"Duplicate entry 'private' for key '{key}'"),
    )
    assert CatalogService._is_brand_unique_error(error)
    mapped = CatalogService._brand_exists()
    assert mapped.error_code == "BRAND_EXISTS"
    assert "private" not in mapped.message
    assert "name" in mapped.errors


@pytest.mark.parametrize(
    ("code", "key"),
    [
        (1062, "uq_products_sku"),
        (1452, "uq_brands_name"),
        (1048, "uq_brands_name"),
    ],
)
def test_other_sql_errors_are_not_mislabeled_brand_duplicate(code, key):
    error = IntegrityError(
        "SQL ...", {}, Exception(code, f"database error on {key}")
    )
    assert not CatalogService._is_brand_unique_error(error)


def test_brand_duplicate_lookup_excludes_its_own_id():
    session = SqlSession(SqlResult(row={"id": 8, "name": "Apple"}))
    row = BrandRepository(session).find_by_name("Apple", exclude_id=7)
    assert row["id"] == 8
    sql, params = session.calls[0]
    assert "id <> :exclude_id" in sql
    assert params == {"name": "Apple", "exclude_id": 7}


def test_supplier_create_is_active_by_default_not_client_override():
    session = SqlSession()
    assert SupplierRepository(session).create(name="NCC A") == 17
    sql, params = session.calls[0]
    assert "is_active" in sql and ":address, 1" in sql
    assert "is_active" not in params
    assert "DELETE" not in sql.upper()


def test_regular_supplier_edit_cannot_reactivate():
    session = SqlSession()
    SupplierRepository(session).update_details(
        supplier_id=5,
        name="NCC A",
        phone=None,
        email=None,
        address=None,
    )
    sql, params = session.calls[0]
    assert "UPDATE suppliers" in sql
    assert "is_active" not in sql
    assert "DELETE" not in sql.upper()
    assert params["supplier_id"] == 5


@pytest.mark.parametrize(
    ("rowcount", "expected"),
    [(1, True), (0, False)],
)
def test_discontinue_sql_updates_only_active_flag(rowcount, expected):
    session = SqlSession(SqlResult(rowcount=rowcount))
    assert (
        SupplierStatusRepository(session).deactivate(supplier_id=5)
        is expected
    )
    sql, params = session.calls[0]
    assert "SET is_active = 0" in sql
    assert "AND is_active = 1" in sql
    assert "DELETE" not in sql.upper()
    assert "name =" not in sql
    assert params == {"supplier_id": 5}


class SupplierReader:
    def __init__(self, row):
        self.row = row
        self.locked = False

    def get_by_id(self, supplier_id, *, for_update=False):
        self.locked = for_update
        return self.row


@pytest.mark.parametrize(
    ("row", "error_code"),
    [
        ({"id": 5, "is_active": True}, None),
        ({"id": 5, "is_active": False}, "SUPPLIER_INACTIVE"),
        (None, "NOT_FOUND"),
    ],
)
def test_import_precheck_uses_row_lock(row, error_code):
    repo = SupplierReader(row)

    if error_code is None:
        result = CatalogService.require_active_for_import(
            repository=repo,
            supplier_id=5,
        )
        assert result == row
    else:
        with pytest.raises(AppError) as caught:
            CatalogService.require_active_for_import(
                repository=repo,
                supplier_id=5,
            )
        assert caught.value.error_code == error_code

    assert repo.locked is True
