
"""Task 29: unit checks for SQL safety, product status and filtering."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from repositories.product_search_repository import ProductSearchRepository
from services.permissions import Permission
from services.product_management_service import ProductManagementService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)


class SqlResult:
    def __init__(self, rows=None, total=0):
        self.rows = rows or []
        self.total = total

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.total


class SqlSession:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params):
        sql = statement.text
        self.calls.append((sql, dict(params)))

        if "COUNT(*)" in sql:
            return SqlResult(total=1)

        return SqlResult(rows=[{"id": 7, "sku": "SKU"}])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeAuth:
    def __init__(self):
        self.calls = 0

    def require_user(self, *, session_store):
        self.calls += 1
        return SimpleNamespace(user_id=23)


class FakeGuard:
    def __init__(self):
        self.calls = []
        self.error = None
        self.session = object()

    def run_allowed(
        self,
        *,
        session_store,
        permission,
        action,
    ):
        self.calls.append(permission)

        if self.error:
            raise AppError(
                self.error,
                "Không có quyền",
            )

        return action(self.session)


class FakeProducts:
    def __init__(self):
        self.row = {
            "id": 7,
            "sku": "SKU",
            "status": "ACTIVE",
            "stock": 4,
            "cost_price": Decimal("100.00"),
            "updated_at": None,
            "updated_by": None,
        }
        self.calls = []

    def get_by_id(
        self,
        product_id,
        *,
        for_update=False,
    ):
        self.calls.append(
            ("get", product_id, for_update)
        )

        return (
            dict(self.row)
            if product_id == 7
            else None
        )

    def set_status(self, **kwargs):
        self.calls.append(("set", kwargs))
        self.row["status"] = kwargs["status"]
        self.row["updated_at"] = kwargs["now_utc"]
        self.row["updated_by"] = kwargs["updated_by"]
        return True


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search_public(self, **kwargs):
        self.calls.append(("public", kwargs))

        return {
            "items": [{"id": 7}],
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }

    def search_admin(self, **kwargs):
        self.calls.append(("admin", kwargs))

        return {
            "items": [{"id": 7}],
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }


@pytest.fixture
def env():
    products = FakeProducts()
    search = FakeSearch()
    auth = FakeAuth()
    guard = FakeGuard()

    service = ProductManagementService(
        session_factory=SqlSession,
        clock=FixedClock(NOW),
        auth_service=auth,
        protected_actions=guard,
        product_repository_factory=(
            lambda session: products
        ),
        search_repository_factory=(
            lambda session: search
        ),
    )

    return service, products, search, guard, auth


def test_public_sql_never_selects_cost_exact_stock_or_discontinued():
    session = SqlSession()

    result = ProductSearchRepository(
        session
    ).search_public(only_in_stock=True)

    sql, params = session.calls[0]

    assert "p.status = 'ACTIVE'" in sql
    assert "p.stock > 0" in sql
    assert "p.cost_price" not in sql
    assert "p.stock," not in sql
    assert "(p.stock > 0) AS in_stock" in sql
    assert params["limit"] == 50
    assert result["total"] == 1
    assert len(session.calls) == 2


def test_admin_sql_includes_stock_cost_low_stock_and_status():
    session = SqlSession()

    ProductSearchRepository(session).search_admin(
        status="DISCONTINUED",
        low_stock=True,
        brand_id=6,
        sort_by="price_asc",
        limit=5,
        offset=2,
    )

    sql, params = session.calls[0]

    assert "p.cost_price" in sql
    assert "p.stock" in sql
    assert "p.stock <= p.min_stock" in sql
    assert "p.status = :status" in sql
    assert "ORDER BY p.sell_price ASC, p.id DESC" in sql
    assert params["status"] == "DISCONTINUED"
    assert params["brand_id"] == 6
    assert params["limit"] == 5
    assert params["offset"] == 2
    assert session.calls[1][1]["status"] == "DISCONTINUED"


def test_keyword_wildcards_are_escaped_and_parameterized():
    session = SqlSession()

    ProductSearchRepository(
        session
    ).search_public(keyword="100%_!")

    sql, params = session.calls[0]

    assert "LIKE :keyword ESCAPE '!'" in sql
    assert "100%_!" not in sql
    assert params["keyword"] == "%100!%!_!!%"


def test_admin_all_statuses_have_no_status_filter():
    session = SqlSession()

    ProductSearchRepository(
        session
    ).search_admin()

    sql, params = session.calls[0]

    assert "p.status =" not in sql
    assert "status" not in params


def test_repository_rejects_unknown_sort_without_running_sql():
    session = SqlSession()

    with pytest.raises(ValueError):
        ProductSearchRepository(
            session
        ).search_public(
            sort_by="sku; DROP TABLE products"
        )

    assert session.calls == []


def test_public_search_requires_no_login(env):
    service, _, search, guard, auth = env

    result = service.search_public(
        keyword="  Phone   A  ",
        only_in_stock=True,
    )

    assert result["total"] == 1
    assert search.calls[0][1]["keyword"] == "Phone A"
    assert search.calls[0][1]["only_in_stock"] is True
    assert guard.calls == []
    assert auth.calls == 0


def test_admin_search_requires_manage_products_permission(env):
    service, _, search, guard, _ = env

    service.search_admin(
        session_store=object(),
        status="ACTIVE",
        low_stock=True,
    )

    assert guard.calls == [
        Permission.MANAGE_PRODUCTS
    ]
    assert search.calls[0][0] == "admin"
    assert search.calls[0][1]["status"] == "ACTIVE"
    assert search.calls[0][1]["low_stock"] is True


def test_admin_search_all_status_is_unfiltered(env):
    service, _, search, _, _ = env

    service.search_admin(
        session_store=object(),
    )

    assert search.calls[0][1]["status"] is None


def test_denied_search_never_calls_repository(env):
    service, _, search, guard, _ = env
    guard.error = "FORBIDDEN"

    with pytest.raises(AppError) as caught:
        service.search_admin(
            session_store=object(),
            low_stock=True,
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert search.calls == []


def test_status_change_updates_audit_only(env):
    service, products, _, guard, auth = env

    result = service.set_status(
        session_store=object(),
        product_id=7,
        status="DISCONTINUED",
    )

    assert result["status"] == "DISCONTINUED"
    assert result["stock"] == 4
    assert result["cost_price"] == Decimal("100.00")
    assert result["updated_by"] == 23
    assert (
        result["updated_at"]
        == NOW.replace(tzinfo=None)
    )
    assert products.calls[0] == ("get", 7, True)
    assert guard.calls == [
        Permission.MANAGE_PRODUCTS
    ]
    assert auth.calls == 1


def test_repeating_same_status_is_idempotent(env):
    service, products, _, _, auth = env

    service.set_status(
        session_store=object(),
        product_id=7,
        status="ACTIVE",
    )

    assert not any(
        call[0] == "set"
        for call in products.calls
    )
    assert auth.calls == 0


def test_restore_to_active(env):
    service, products, _, _, _ = env
    products.row["status"] = "DISCONTINUED"

    result = service.set_status(
        session_store=object(),
        product_id=7,
        status="ACTIVE",
    )

    assert result["status"] == "ACTIVE"


def test_status_change_missing_product_is_not_found(env):
    service, products, _, _, _ = env

    with pytest.raises(AppError) as caught:
        service.set_status(
            session_store=object(),
            product_id=999,
            status="DISCONTINUED",
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert not any(
        call[0] == "set"
        for call in products.calls
    )


def test_denied_status_change_never_calls_repository(env):
    service, products, _, guard, _ = env
    guard.error = "ACCOUNT_LOCKED"

    with pytest.raises(AppError) as caught:
        service.set_status(
            session_store=object(),
            product_id=7,
            status="DISCONTINUED",
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert products.calls == []


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "7"],
)
def test_invalid_product_id_fails_before_sql(
    env,
    bad_id,
):
    service, products, _, _, _ = env

    with pytest.raises(AppError) as caught:
        service.set_status(
            session_store=object(),
            product_id=bad_id,
            status="ACTIVE",
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert products.calls == []


@pytest.mark.parametrize(
    "status",
    ["", "DELETED", "ALL", None],
)
def test_invalid_target_status_fails(env, status):
    service, products, _, _, _ = env

    with pytest.raises(AppError) as caught:
        service.set_status(
            session_store=object(),
            product_id=7,
            status=status,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert products.calls == []


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"keyword": "X" * 101}, "keyword"),
        ({"brand_id": 0}, "brand_id"),
        ({"min_price": "-1"}, "min_price"),
        ({"max_price": "NaN"}, "max_price"),
        (
            {"min_price": "500", "max_price": "100"},
            "max_price",
        ),
        ({"sort_by": "unsafe"}, "sort_by"),
        ({"limit": 0}, "limit"),
        ({"offset": -1}, "offset"),
        (
            {"only_in_stock": "yes"},
            "only_in_stock",
        ),
    ],
)
def test_invalid_public_search_filters_fail(
    env,
    kwargs,
    field,
):
    service, _, search, _, _ = env

    with pytest.raises(AppError) as caught:
        service.search_public(**kwargs)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert search.calls == []


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"status": "DELETED"}, "status"),
        ({"low_stock": "yes"}, "low_stock"),
    ],
)
def test_invalid_admin_filters_fail(
    env,
    kwargs,
    field,
):
    service, _, search, _, _ = env

    with pytest.raises(AppError) as caught:
        service.search_admin(
            session_store=object(),
            **kwargs,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert search.calls == []


def test_sales_guard_requires_active_with_row_lock(env):
    _, products, _, _, _ = env

    item = ProductManagementService.require_active_for_sale(
        repository=products,
        product_id=7,
    )

    assert item["status"] == "ACTIVE"
    assert products.calls[0] == ("get", 7, True)


def test_sales_guard_rejects_discontinued(env):
    _, products, _, _, _ = env
    products.row["status"] = "DISCONTINUED"

    with pytest.raises(AppError) as caught:
        ProductManagementService.require_active_for_sale(
            repository=products,
            product_id=7,
        )

    assert caught.value.error_code == "PRODUCT_DISCONTINUED"


def test_sales_guard_rejects_missing_product(env):
    _, products, _, _, _ = env

    with pytest.raises(AppError) as caught:
        ProductManagementService.require_active_for_sale(
            repository=products,
            product_id=99,
        )

    assert caught.value.error_code == "NOT_FOUND"
