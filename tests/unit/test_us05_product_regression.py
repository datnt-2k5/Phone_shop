
"""Task 31 - US05: regression tests for product validation and safety."""

from decimal import Decimal
from inspect import signature

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.product_create_service import ProductCreateService
from services.product_edit_service import ProductEditService
from services.product_management_service import ProductManagementService
from services.product_validation_service import ProductValidationService


class SpyRepository:
    """Repository giả để chứng minh dữ liệu sai không chạm DB."""

    def __init__(self):
        self.calls = []

    def get_by_sku(self, sku):
        self.calls.append(("sku", sku))

    def find_variant(self, **kwargs):
        self.calls.append(("variant", kwargs))


def identity(**changes):
    return {
        "sku": "T31-NEW",
        "brand_id": 3,
        "name": "Phone Task31",
        "storage": "128GB",
        "color": "Black",
    } | changes


@pytest.mark.parametrize(
    "price",
    [
        "-1",
        "-100",
        "0",
        0,
        -10,
        Decimal("-0.01"),
        "NaN",
        "Infinity",
        "1.234",
        True,
        1.5,
    ],
)
def test_invalid_sell_price_is_rejected(price):
    """Không chấp nhận giá <= 0, NaN, Infinity hoặc sai độ chính xác."""

    with pytest.raises(AppError) as caught:
        ProductEditService._validate_price(price)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "sell_price" in caught.value.errors


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", Decimal("1.00")),
        ("15000000", Decimal("15000000.00")),
        ("15000000.50", Decimal("15000000.50")),
        (Decimal("0.01"), Decimal("0.01")),
    ],
)
def test_valid_price_is_normalized(raw, expected):
    result = ProductEditService._validate_price(raw)
    assert result == expected
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "minimum",
    [-1, -100, True, "3", 1.5, 2_147_483_648],
)
def test_invalid_minimum_stock_is_rejected(minimum):
    with pytest.raises(AppError) as caught:
        ProductEditService._validate_min_stock(minimum)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "min_stock" in caught.value.errors


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sku", None),
        ("sku", ""),
        ("name", None),
        ("name", " "),
        ("brand_id", 0),
        ("brand_id", True),
        ("storage", None),
        ("color", ""),
    ],
)
def test_required_identity_fields_rejected_before_sql(
    field,
    value,
):
    repo = SpyRepository()

    with pytest.raises(AppError) as caught:
        ProductValidationService().validate_create(
            repo,
            **identity(**{field: value}),
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert field in caught.value.errors
    assert repo.calls == []


@pytest.mark.parametrize(
    "price",
    ["-1", "NaN", "Infinity", "1.234"],
)
def test_public_search_rejects_invalid_price_filter(price):
    with pytest.raises(AppError) as caught:
        ProductManagementService._search_args(
            keyword=None,
            brand_id=None,
            min_price=price,
            max_price=None,
            sort_by="newest",
            limit=10,
            offset=0,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "min_price" in caught.value.errors


def test_create_api_does_not_accept_inventory_or_cost():
    parameters = signature(
        ProductCreateService.create
    ).parameters

    forbidden = {
        "stock",
        "cost_price",
        "status",
        "updated_by",
    }

    assert forbidden.isdisjoint(parameters)
    assert "session_store" in parameters


def test_edit_api_does_not_accept_inventory_or_cost():
    parameters = signature(
        ProductEditService.update_details
    ).parameters

    forbidden = {
        "sku",
        "brand_id",
        "storage",
        "color",
        "stock",
        "cost_price",
        "status",
        "updated_by",
    }

    assert forbidden.isdisjoint(parameters)
    assert "session_store" in parameters


@pytest.mark.parametrize(
    ("constraint", "field"),
    [
        ("uq_products_sku", "sku"),
        ("uq_products_variant", "name"),
    ],
)
def test_unique_constraint_error_is_safe(
    constraint,
    field,
):
    raw = (
        "Duplicate entry 'PRIVATE-SKU' "
        f"for key '{constraint}'"
    )

    error = IntegrityError(
        "INSERT INTO products ...",
        {},
        Exception(1062, raw),
    )

    mapped = ProductValidationService.translate_unique_error(
        error
    )

    assert mapped is not None
    assert mapped.error_code == "PRODUCT_EXISTS"
    assert field in mapped.errors
    assert "PRIVATE-SKU" not in mapped.message


def test_foreign_key_error_is_not_mislabeled_duplicate():
    error = IntegrityError(
        "INSERT INTO products ...",
        {},
        Exception(1452, "Foreign key constraint fails"),
    )

    mapped = ProductValidationService.translate_unique_error(
        error
    )

    assert mapped is None


class SaleRepository:
    def __init__(self, status):
        self.status = status
        self.locked = False

    def get_by_id(self, product_id, *, for_update=False):
        self.locked = for_update
        return {
            "id": product_id,
            "status": self.status,
        }


def test_active_product_passes_sales_precheck():
    repo = SaleRepository("ACTIVE")

    product = ProductManagementService.require_active_for_sale(
        repository=repo,
        product_id=7,
    )

    assert product["status"] == "ACTIVE"
    assert repo.locked is True


def test_discontinued_product_fails_sales_precheck():
    repo = SaleRepository("DISCONTINUED")

    with pytest.raises(AppError) as caught:
        ProductManagementService.require_active_for_sale(
            repository=repo,
            product_id=7,
        )

    assert caught.value.error_code == "PRODUCT_DISCONTINUED"
    assert repo.locked is True
