
"""Task 30: Unit Tests for authorized product creation."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.permissions import Permission
from services.product_create_service import ProductCreateService
from utils.time_utils import FixedClock

NOW = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)


class FakeResult:
    def scalar_one_or_none(self):
        return 3

    def mappings(self):
        return self

    def all(self):
        return [{"id": 3, "name": "Demo Brand"}]


class FakeSession:
    def execute(self, statement, params=None):
        return FakeResult()


class FakeAuth:
    def require_user(self, *, session_store):
        return SimpleNamespace(user_id=7)


class FakeGuard:
    def __init__(self):
        self.permission = None
        self.error = None

    def run_allowed(
        self,
        *,
        session_store,
        permission,
        action,
    ):
        self.permission = permission
        if self.error:
            raise AppError(self.error, "Không đủ quyền.")
        return action(FakeSession())


class FakeRepository:
    def __init__(self):
        self.saved = None
        self.duplicate_sku = False
        self.duplicate_variant = False
        self.integrity_error = None

    def get_by_sku(self, sku):
        if self.duplicate_sku:
            return {"id": 2, "sku": sku}
        return None

    def find_variant(self, **kwargs):
        if self.duplicate_variant:
            return {"id": 2}
        return None

    def create(self, **kwargs):
        if self.integrity_error:
            raise self.integrity_error
        self.saved = kwargs
        return 11

    def get_by_id(self, product_id):
        return {
            "id": product_id,
            "sku": self.saved["sku"],
            "name": self.saved["name"],
            "stock": 0,
            "cost_price": Decimal("0.00"),
            "status": "ACTIVE",
            "updated_by": self.saved["updated_by"],
        }


@pytest.fixture
def env():
    repo = FakeRepository()
    guard = FakeGuard()
    service = ProductCreateService(
        clock=FixedClock(NOW),
        auth_service=FakeAuth(),
        protected_actions=guard,
        repository_factory=lambda session: repo,
    )
    return service, repo, guard


def inputs(**changes):
    return {
        "session_store": object(),
        "sku": "SKU-30",
        "name": "Phone 30",
        "brand_id": 3,
        "storage": "256GB",
        "color": "Black",
        "sell_price": "15000000.00",
        "min_stock": 2,
        "description": "Demo",
        "image_url": "/images/demo.png",
    } | changes


def test_create_uses_permission_and_verified_actor(env):
    service, repo, guard = env
    result = service.create(**inputs())

    assert guard.permission == Permission.MANAGE_PRODUCTS
    assert result["id"] == 11
    assert result["updated_by"] == 7
    assert result["stock"] == 0
    assert result["cost_price"] == Decimal("0.00")
    assert repo.saved["sell_price"] == Decimal("15000000.00")
    assert repo.saved["now_utc"] == NOW.replace(tzinfo=None)
    assert "stock" not in repo.saved
    assert "cost_price" not in repo.saved


def test_brand_list_is_authorized(env):
    service, _, guard = env
    result = service.list_brands(session_store=object())
    assert result == [{"id": 3, "name": "Demo Brand"}]
    assert guard.permission == Permission.MANAGE_PRODUCTS


@pytest.mark.parametrize(
    "code",
    ["FORBIDDEN", "ACCOUNT_LOCKED", "UNAUTHORIZED"],
)
def test_denied_account_cannot_create(env, code):
    service, repo, guard = env
    guard.error = code

    with pytest.raises(AppError) as caught:
        service.create(**inputs())

    assert caught.value.error_code == code
    assert repo.saved is None


def test_duplicate_sku_is_blocked(env):
    service, repo, _ = env
    repo.duplicate_sku = True

    with pytest.raises(AppError) as caught:
        service.create(**inputs())

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert repo.saved is None


def test_duplicate_variant_is_blocked(env):
    service, repo, _ = env
    repo.duplicate_variant = True

    with pytest.raises(AppError) as caught:
        service.create(**inputs())

    assert caught.value.error_code == "PRODUCT_EXISTS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sell_price", "0"),
        ("sell_price", "NaN"),
        ("sell_price", "1.234"),
        ("min_stock", -1),
        ("brand_id", 0),
        ("sku", ""),
        ("name", ""),
        ("storage", ""),
        ("color", ""),
    ],
)
def test_invalid_create_input_is_rejected(env, field, value):
    service, repo, _ = env

    with pytest.raises(AppError) as caught:
        service.create(**inputs(**{field: value}))

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert repo.saved is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("stock", 100),
        ("cost_price", Decimal("10.00")),
        ("status", "DISCONTINUED"),
        ("updated_by", 999),
    ],
)
def test_client_cannot_supply_protected_columns(
    env, field, value
):
    service, repo, _ = env

    with pytest.raises(TypeError):
        service.create(**inputs(), **{field: value})

    assert repo.saved is None


def test_duplicate_database_error_is_mapped(env):
    service, repo, _ = env
    repo.integrity_error = IntegrityError(
        "INSERT ...",
        {},
        Exception(
            1062,
            "Duplicate entry 'x' for key 'uq_products_sku'",
        ),
    )

    with pytest.raises(AppError) as caught:
        service.create(**inputs())

    assert caught.value.error_code == "PRODUCT_EXISTS"
