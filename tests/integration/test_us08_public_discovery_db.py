
"""Task 44 / US08: public product search on MariaDB test database."""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.product_management_service import ProductManagementService

NOW = datetime(2026, 11, 11, 10, 0)

PRIVATE_FIELDS = {
    "cost_price",
    "stock",
    "min_stock",
    "status",
    "updated_at",
    "updated_by",
}


@pytest.fixture
def ws(test_db: Connection):
    db = test_db

    assert db.execute(
        text("SELECT DATABASE()")
    ).scalar_one() == "phone_shop_test"

    token = token_hex(6)
    keyword = f"Task44-{token}"

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    def make_brand(suffix):
        result = db.execute(
            text("""
                INSERT INTO brands (name, created_at)
                VALUES (:name, :created_at)
            """),
            {
                "name": f"{keyword} {suffix}",
                "created_at": NOW,
            },
        )
        return int(result.lastrowid)

    alpha = make_brand("Alpha")
    beta = make_brand("Beta")

    specs = {
        "a": {
            "name": "Pixel 100%",
            "brand": alpha,
            "price": "10000000.00",
            "stock": 2,
            "status": "ACTIVE",
        },
        "b": {
            "name": "Pixel_Pro",
            "brand": alpha,
            "price": "15000000.00",
            "stock": 0,
            "status": "ACTIVE",
        },
        "c": {
            "name": "Galaxy S",
            "brand": beta,
            "price": "15000000.00",
            "stock": 4,
            "status": "ACTIVE",
        },
        "d": {
            "name": "Legacy Hidden",
            "brand": beta,
            "price": "4000000.00",
            "stock": 9,
            "status": "DISCONTINUED",
        },
        "e": {
            "name": "PixelAPro",
            "brand": alpha,
            "price": "20000000.00",
            "stock": 3,
            "status": "ACTIVE",
        },
    }

    product_ids = {}

    with factory() as session, session.begin():
        repository = ProductRepository(session)

        for key, spec in specs.items():
            product_ids[key] = repository.create(
                sku=f"T44-{token}-{key.upper()}",
                name=f"{keyword} {spec['name']}",
                brand_id=spec["brand"],
                storage="128GB",
                color="Black",
                sell_price=Decimal(spec["price"]),
                now_utc=NOW,
            )

    # Test fixture only. Production inventory changes must go
    # through the US07 inventory services.
    for key, spec in specs.items():
        db.execute(
            text("""
                UPDATE products
                SET
                    stock = :stock,
                    cost_price = :cost_price,
                    status = :status
                WHERE id = :product_id
            """),
            {
                "stock": spec["stock"],
                "cost_price": Decimal("8000000.00"),
                "status": spec["status"],
                "product_id": product_ids[key],
            },
        )

    return {
        "db": db,
        "keyword": keyword,
        "alpha": alpha,
        "beta": beta,
        "ids": product_ids,
        "service": ProductManagementService(
            session_factory=factory
        ),
    }


def search(ws, **kwargs):
    return ws["service"].search_public(
        keyword=ws["keyword"],
        **kwargs,
    )


def test_public_lists_only_active_products_and_safe_fields(ws):
    page = search(ws)

    ids = {
        item["id"]
        for item in page["items"]
    }

    assert page["total"] == 4
    assert ids == {
        ws["ids"]["a"],
        ws["ids"]["b"],
        ws["ids"]["c"],
        ws["ids"]["e"],
    }

    for row in page["items"]:
        assert not (set(row) & PRIVATE_FIELDS)
        assert "sell_price" in row
        assert "in_stock" in row


def test_public_detail_is_safe_and_uses_active_product(ws):
    product = ws["service"].get_public_detail(
        product_id=ws["ids"]["a"]
    )

    assert product["id"] == ws["ids"]["a"]
    assert product["sku"].startswith("T44-")
    assert product["brand_name"].endswith("Alpha")
    assert product["sell_price"] == Decimal("10000000.00")
    assert bool(product["in_stock"]) is True
    assert not (set(product) & PRIVATE_FIELDS)


def test_discontinued_product_is_hidden_from_public_detail(ws):
    with pytest.raises(AppError) as caught:
        ws["service"].get_public_detail(
            product_id=ws["ids"]["d"]
        )

    assert caught.value.error_code == "NOT_FOUND"


def test_combined_brand_price_and_in_stock_filters(ws):
    page = search(
        ws,
        brand_id=ws["alpha"],
        min_price="10000000.00",
        max_price="15000000.00",
        only_in_stock=True,
    )

    assert page["total"] == 1
    assert [
        item["id"] for item in page["items"]
    ] == [ws["ids"]["a"]]


def test_price_sort_is_stable_across_pages(ws):
    first = search(
        ws,
        sort_by="price_asc",
        limit=2,
        offset=0,
    )
    second = search(
        ws,
        sort_by="price_asc",
        limit=2,
        offset=2,
    )

    assert first["total"] == 4
    assert second["total"] == 4

    assert [
        item["id"] for item in first["items"]
    ] == [
        ws["ids"]["a"],
        ws["ids"]["c"],
    ]

    assert [
        item["id"] for item in second["items"]
    ] == [
        ws["ids"]["b"],
        ws["ids"]["e"],
    ]


def test_only_in_stock_excludes_zero_stock(ws):
    page = search(
        ws,
        only_in_stock=True,
    )

    assert {
        item["id"]
        for item in page["items"]
    } == {
        ws["ids"]["a"],
        ws["ids"]["c"],
        ws["ids"]["e"],
    }

    assert page["total"] == 3


def test_literal_percent_does_not_act_as_wildcard(ws):
    page = ws["service"].search_public(
        keyword=f"{ws['keyword']} Pixel 100%"
    )

    assert page["total"] == 1
    assert page["items"][0]["id"] == ws["ids"]["a"]


def test_literal_underscore_does_not_act_as_wildcard(ws):
    page = ws["service"].search_public(
        keyword=f"{ws['keyword']} Pixel_Pro"
    )

    assert page["total"] == 1
    assert page["items"][0]["id"] == ws["ids"]["b"]


def test_injection_shaped_keyword_is_plain_search_text(ws):
    page = ws["service"].search_public(
        keyword="' OR 1=1 --"
    )

    assert page["total"] == 0
    assert page["items"] == []


def test_out_of_range_pagination_keeps_total(ws):
    page = search(
        ws,
        limit=2,
        offset=99,
    )

    assert page["total"] == 4
    assert page["items"] == []
    assert page["limit"] == 2
    assert page["offset"] == 99
