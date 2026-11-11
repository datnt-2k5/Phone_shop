
"""Task 44 / US08: public product discovery and data isolation."""

from decimal import Decimal
from unittest.mock import Mock

import pytest

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.product_management_service import ProductManagementService

PUBLIC_ROW = {
    "id": 10,
    "sku": "T44-001",
    "name": "Phone Test",
    "brand_id": 2,
    "brand_name": "Test Brand",
    "storage": "128GB",
    "color": "Black",
    "description": "Public description",
    "image_url": None,
    "sell_price": Decimal("10000000.00"),
    "in_stock": True,
}

PRIVATE_ROW = {
    **PUBLIC_ROW,
    "cost_price": Decimal("8000000.00"),
    "stock": 7,
    "min_stock": 3,
    "status": "ACTIVE",
    "updated_by": 99,
    "updated_at": "2026-11-11",
}

SENSITIVE_FIELDS = {
    "cost_price",
    "stock",
    "min_stock",
    "status",
    "updated_by",
    "updated_at",
}


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSearch:
    def __init__(self):
        self.calls = []

    def search_public(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "items": [dict(PRIVATE_ROW)],
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }


class FakeProducts:
    def __init__(self):
        self.calls = []
        self.row = dict(PRIVATE_ROW)

    def get_public_by_id(self, product_id):
        self.calls.append(product_id)
        if product_id != 10:
            return None
        return dict(self.row)


class NoAuth:
    def require_user(self, **kwargs):
        raise AssertionError(
            "Public read must not authenticate"
        )


class NoProtectedActions:
    def run_allowed(self, **kwargs):
        raise AssertionError(
            "Public read must not use admin permissions"
        )


@pytest.fixture
def env():
    products = FakeProducts()
    search = FakeSearch()

    service = ProductManagementService(
        session_factory=FakeSession,
        auth_service=NoAuth(),
        protected_actions=NoProtectedActions(),
        product_repository_factory=lambda session: products,
        search_repository_factory=lambda session: search,
    )

    return service, products, search


def test_public_search_strips_private_fields(env):
    service, _, _ = env

    result = service.search_public(
        keyword="Phone",
        limit=10,
        offset=0,
    )

    assert result["total"] == 1
    assert result["limit"] == 10
    assert result["offset"] == 0
    assert result["items"] == [PUBLIC_ROW]

    assert not (
        set(result["items"][0]) & SENSITIVE_FIELDS
    )


def test_public_detail_strips_private_fields_without_login(env):
    service, products, _ = env

    product = service.get_public_detail(
        product_id=10
    )

    assert product == PUBLIC_ROW
    assert products.calls == [10]
    assert not (set(product) & SENSITIVE_FIELDS)


def test_missing_public_product_returns_not_found(env):
    service, products, _ = env

    with pytest.raises(AppError) as caught:
        service.get_public_detail(
            product_id=999
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert products.calls == [999]


def test_search_keyword_is_normalized(env):
    service, _, search = env

    service.search_public(
        keyword="  Phone    Test  "
    )

    assert search.calls[-1]["keyword"] == "Phone Test"


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "10", None, 1.5],
)
def test_invalid_detail_id_rejected_before_repository(
    env,
    bad_id,
):
    service, products, _ = env

    with pytest.raises(AppError) as caught:
        service.get_public_detail(
            product_id=bad_id
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert products.calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keyword": "X" * 101},
        {"brand_id": True},
        {"min_price": "-1"},
        {"min_price": "1.001"},
        {"max_price": "NaN"},
        {
            "min_price": "200",
            "max_price": "100",
        },
        {"only_in_stock": "yes"},
        {"sort_by": "price_asc; DROP TABLE products"},
        {"limit": 0},
        {"offset": -1},
    ],
)
def test_invalid_public_filters_do_not_call_repository(
    env,
    kwargs,
):
    service, _, search = env

    with pytest.raises(AppError) as caught:
        service.search_public(**kwargs)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert search.calls == []


def test_blank_keyword_is_treated_as_no_filter(env):
    service, _, search = env

    service.search_public(keyword=" \t ")

    assert search.calls[-1]["keyword"] is None


def test_valid_price_range_uses_decimal(env):
    service, _, search = env

    service.search_public(
        brand_id=2,
        min_price="10000000.00",
        max_price="20000000.00",
        only_in_stock=True,
        sort_by="price_asc",
        limit=12,
        offset=24,
    )

    params = search.calls[-1]

    assert params["brand_id"] == 2
    assert params["min_price"] == Decimal("10000000.00")
    assert params["max_price"] == Decimal("20000000.00")
    assert params["only_in_stock"] is True
    assert params["sort_by"] == "price_asc"
    assert params["limit"] == 12
    assert params["offset"] == 24


def test_public_detail_repository_query_excludes_private_data():
    session = Mock()

    (
        session.execute.return_value
        .mappings.return_value
        .first.return_value
    ) = dict(PUBLIC_ROW)

    result = ProductRepository(
        session
    ).get_public_by_id(10)

    statement, params = session.execute.call_args.args
    sql = statement.text

    assert result["id"] == 10
    assert params == {"product_id": 10}
    assert "p.status = 'ACTIVE'" in sql
    assert "p.cost_price" not in sql
    assert "p.stock," not in sql
    assert "p.min_stock" not in sql
    assert "p.updated_by" not in sql
    assert "(p.stock > 0) AS in_stock" in sql

    session.commit.assert_not_called()
