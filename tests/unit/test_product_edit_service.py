
"""Task 28: Unit Test sửa thông tin sản phẩm và bảo vệ tồn kho."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.permissions import Permission
from services.product_edit_service import ProductEditService
from utils.time_utils import FixedClock

FIXED_TIME = datetime(2026, 11, 10, 2, 0, tzinfo=UTC)


class FakeStore:
    pass


class FakeAuth:
    def __init__(self, user_id=7):
        self.user_id = user_id
        self.calls = 0

    def require_user(self, *, session_store):
        self.calls += 1
        return SimpleNamespace(user_id=self.user_id)


class FakeGuard:
    def __init__(self):
        self.error_code = None
        self.calls = []
        self.session = object()

    def run_allowed(self, *, session_store, permission, action):
        self.calls.append(permission)

        if self.error_code is not None:
            raise AppError(
                self.error_code,
                "Không được thực hiện thao tác.",
            )

        return action(self.session)


class FakeRepo:
    def __init__(self):
        self.row = {
            "id": 11,
            "sku": "PHONE-001",
            "brand_id": 3,
            "name": "Phone A",
            "storage": "128GB",
            "color": "Black",
            "description": "Original",
            "image_url": "/images/old.png",
            "sell_price": Decimal("1000000.00"),
            "cost_price": Decimal("800000.00"),
            "stock": 12,
            "min_stock": 2,
            "status": "ACTIVE",
            "updated_by": 1,
            "updated_at": None,
        }
        self.duplicate = False
        self.sql_error = None
        self.calls = []
        self.updates = []

    def get_by_id(self, product_id, *, for_update=False):
        self.calls.append(("get", product_id, for_update))
        if product_id != self.row["id"]:
            return None
        return dict(self.row)

    def find_variant(
        self,
        *,
        brand_id,
        name,
        storage,
        color,
        exclude_id=None,
    ):
        self.calls.append(
            ("variant", brand_id, name, storage, color, exclude_id)
        )
        return {"id": 99} if self.duplicate else None

    def update_details(self, **values):
        self.updates.append(values)

        if self.sql_error is not None:
            raise self.sql_error

        if values["product_id"] != self.row["id"]:
            return False

        for field in (
            "name",
            "description",
            "sell_price",
            "image_url",
            "min_stock",
            "updated_by",
        ):
            self.row[field] = values[field]

        self.row["updated_at"] = values["now_utc"]
        return True


@pytest.fixture
def environment():
    repo = FakeRepo()
    guard = FakeGuard()
    auth = FakeAuth()
    store = FakeStore()

    service = ProductEditService(
        clock=FixedClock(FIXED_TIME),
        auth_service=auth,
        protected_actions=guard,
        repository_factory=lambda session: repo,
    )

    return {
        "service": service,
        "repo": repo,
        "guard": guard,
        "auth": auth,
        "store": store,
    }


def valid_input(environment, **changes):
    return {
        "session_store": environment["store"],
        "product_id": 11,
        "name": "Phone Premium",
        "description": "Thông tin mới",
        "sell_price": Decimal("1200000.00"),
        "image_url": "/images/new.png",
        "min_stock": 5,
    } | changes


def test_admin_edit_updates_only_allowed_fields(environment):
    e = environment
    before = dict(e["repo"].row)

    result = e["service"].update_details(
        **valid_input(e)
    )

    assert result["name"] == "Phone Premium"
    assert result["sell_price"] == Decimal("1200000.00")
    assert result["min_stock"] == 5
    assert result["description"] == "Thông tin mới"
    assert result["image_url"] == "/images/new.png"
    assert result["updated_by"] == 7

    for field in (
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
        "status",
    ):
        assert result[field] == before[field]

    assert e["guard"].calls == [
        Permission.MANAGE_PRODUCTS
    ]
    assert e["auth"].calls == 1
    assert e["repo"].calls[0] == ("get", 11, True)

    update = e["repo"].updates[0]

    assert "stock" not in update
    assert "cost_price" not in update
    assert "sku" not in update
    assert update["updated_by"] == 7
    assert update["now_utc"] == FIXED_TIME.replace(tzinfo=None)


def test_edit_with_same_name_is_allowed(environment):
    e = environment

    result = e["service"].update_details(
        **valid_input(e, name="Phone A")
    )

    assert result["name"] == "Phone A"


def test_duplicate_rename_is_rejected_without_writing(environment):
    e = environment
    e["repo"].duplicate = True

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e)
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert e["repo"].updates == []


def test_missing_product_is_not_found(environment):
    e = environment

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e, product_id=999)
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "error_code",
    ["FORBIDDEN", "ACCOUNT_LOCKED", "UNAUTHORIZED"],
)
def test_denied_user_never_reaches_repository(
    environment,
    error_code,
):
    e = environment
    e["guard"].error_code = error_code

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e)
        )

    assert caught.value.error_code == error_code
    assert e["repo"].calls == []
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "invalid",
    [
        "0",
        "-100",
        "NaN",
        "Infinity",
        "1.234",
        "abc",
        True,
        1.5,
    ],
)
def test_invalid_price_is_rejected_without_writing(
    environment,
    invalid,
):
    e = environment

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e, sell_price=invalid)
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "sell_price" in caught.value.errors
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "invalid",
    [-1, True, "2", 1.5, 2_147_483_648],
)
def test_invalid_min_stock_is_rejected(
    environment,
    invalid,
):
    e = environment

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e, min_stock=invalid)
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "min_stock" in caught.value.errors
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "invalid",
    [42, "A" * 4001],
)
def test_invalid_description_is_rejected(
    environment,
    invalid,
):
    e = environment

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e, description=invalid)
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "description" in caught.value.errors
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "invalid",
    [
        "javascript:alert(1)",
        "//example.com/photo.png",
        "/../secrets.txt",
        "ftp://example.com/a.png",
        "a" * 256,
        "/images/photo name.png",
    ],
)
def test_invalid_image_path_is_rejected(
    environment,
    invalid,
):
    e = environment

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e, image_url=invalid)
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "image_url" in caught.value.errors
    assert e["repo"].updates == []


@pytest.mark.parametrize(
    "blocked_field,blocked_value",
    [
        ("stock", 1000),
        ("cost_price", Decimal("1.00")),
        ("sku", "FORGED-SKU"),
        ("brand_id", 999),
        ("storage", "1TB"),
        ("color", "Gold"),
        ("updated_by", 999),
    ],
)
def test_edit_api_rejects_immutable_or_forged_fields(
    environment,
    blocked_field,
    blocked_value,
):
    e = environment

    with pytest.raises(TypeError):
        e["service"].update_details(
            **valid_input(e),
            **{blocked_field: blocked_value},
        )

    assert e["repo"].updates == []


def test_empty_description_and_image_clear_fields(environment):
    e = environment

    result = e["service"].update_details(
        **valid_input(
            e,
            description="   ",
            image_url="  ",
        )
    )

    assert result["description"] is None
    assert result["image_url"] is None


def test_web_image_url_and_price_string_are_accepted(environment):
    e = environment

    result = e["service"].update_details(
        **valid_input(
            e,
            sell_price="1250000.50",
            image_url="https://example.com/images/phone.png",
        )
    )

    assert result["sell_price"] == Decimal("1250000.50")
    assert result["image_url"].startswith("https://")


def test_unique_database_error_maps_to_product_exists(environment):
    e = environment
    e["repo"].sql_error = IntegrityError(
        "UPDATE products ...",
        {},
        Exception(
            1062,
            "Duplicate entry 'secret' for key 'uq_products_variant'",
        ),
    )

    with pytest.raises(AppError) as caught:
        e["service"].update_details(
            **valid_input(e)
        )

    assert caught.value.error_code == "PRODUCT_EXISTS"
    assert "secret" not in caught.value.message
