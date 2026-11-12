
"""Task 47 / US08-T05: integrated public catalog journey on MariaDB."""

from datetime import datetime
from decimal import Decimal
from secrets import token_hex

import flet as ft
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.product_management_service import ProductManagementService
from ui.pages.public_product_detail_page import PublicProductDetailPanel
from ui.pages.public_products_page import PublicProductsPanel
from ui.route_guard import RouteStatus, check_route_access

NOW = datetime(2026, 11, 12, 0, 0)

PUBLIC_FIELDS = set(ProductManagementService._PUBLIC_FIELDS)

PRIVATE_FIELDS = {
    "cost_price",
    "stock",
    "min_stock",
    "status",
    "updated_by",
    "updated_at",
}


class FakePage:
    def __init__(self):
        self.routes = []
        self.updates = 0

    def navigate(self, route):
        self.routes.append(route)

    def update(self):
        self.updates += 1


class FakeCatalog:
    def __init__(self, brands):
        self.brands = brands

    def list_brands(self, *, limit, offset):
        return self.brands[offset:offset + limit]


def visible_text(control):
    """Collect text rendered by nested Flet controls."""
    values = []

    if isinstance(control, ft.Text):
        values.append(str(control.value or ""))

    for child in getattr(control, "controls", None) or []:
        values.extend(visible_text(child))

    content = getattr(control, "content", None)

    if content is not None:
        values.extend(visible_text(content))

    return values


@pytest.fixture
def env(test_db: Connection):
    """Create 16 isolated products in the MariaDB test database."""
    db = test_db

    assert (
        db.execute(text("SELECT DATABASE()")).scalar_one()
        == "phone_shop_test"
    )

    token = token_hex(6)
    prefix = f"Task47-{token}"

    def factory():
        return Session(
            bind=db,
            join_transaction_mode="create_savepoint",
        )

    def add_brand(label):
        result = db.execute(
            text("""
                INSERT INTO brands (name, created_at)
                VALUES (:name, :created_at)
            """),
            {
                "name": f"{prefix} {label}",
                "created_at": NOW,
            },
        )

        return int(result.lastrowid)

    alpha = add_brand("Alpha")
    beta = add_brand("Beta")

    ids = {}
    prices = {}

    with factory() as session, session.begin():
        repo = ProductRepository(session)

        for index in range(1, 17):
            price = Decimal(
                "10000000.00"
                if index <= 5
                else "15000000.00"
                if index <= 14
                else "20000000.00"
            )

            prices[index] = price

            ids[index] = repo.create(
                sku=f"T47-{token}-{index:02d}",
                name=f"{prefix} Model {index:02d}",
                brand_id=alpha if index <= 8 else beta,
                storage="128GB",
                color="Black",
                sell_price=price,
                now_utc=NOW,
            )

    # Fixture data only.
    # Never directly update real-store inventory.
    for index, product_id in ids.items():
        db.execute(
            text("""
                UPDATE products
                SET
                    stock = :stock,
                    cost_price = :cost,
                    status = :status
                WHERE id = :product_id
            """),
            {
                "stock": (
                    0 if index in {3, 10, 14} else 7
                ),
                "cost": Decimal("8765432.10"),
                "status": (
                    "DISCONTINUED"
                    if index == 16
                    else "ACTIVE"
                ),
                "product_id": product_id,
            },
        )

    service = ProductManagementService(
        session_factory=factory
    )

    brands = FakeCatalog(
        [
            {
                "id": alpha,
                "name": f"{prefix} Alpha",
            },
            {
                "id": beta,
                "name": f"{prefix} Beta",
            },
        ]
    )

    return {
        "db": db,
        "prefix": prefix,
        "token": token,
        "ids": ids,
        "prices": prices,
        "alpha": alpha,
        "beta": beta,
        "service": service,
        "catalog": brands,
    }


def listing(env):
    """Open listing with data restricted to this test fixture."""
    page = FakePage()

    panel = PublicProductsPanel(
        page,
        products=env["service"],
        catalog=env["catalog"],
    )

    panel.keyword.value = env["prefix"]
    panel.load()

    assert panel.error.value in (None, "")

    return panel, page


def scoped_search(env, **kwargs):
    """Search products belonging to the current test fixture."""
    return env["service"].search_public(
        keyword=env["prefix"],
        **kwargs,
    )


# ============================================================
# TEST 01
# Pagination: 15 ACTIVE products -> 12 + 3.
# ============================================================

def test_public_listing_has_two_pages_without_repeats(env):
    panel, _ = listing(env)

    first = [
        row["id"]
        for row in panel.items
    ]

    assert panel.total == 15
    assert len(first) == 12
    assert panel.page_label.value == "Trang 1/2"

    assert panel.previous_button.disabled
    assert not panel.next_button.disabled

    panel.next_page()

    second = [
        row["id"]
        for row in panel.items
    ]

    assert len(second) == 3
    assert panel.page_label.value == "Trang 2/2"
    assert panel.next_button.disabled

    assert len(set(first + second)) == 15

    # Product 16 is DISCONTINUED.
    assert env["ids"][16] not in first + second

    panel.previous_page()

    assert [
        row["id"]
        for row in panel.items
    ] == first


# ============================================================
# TEST 02
# Stable sorting when multiple products have equal prices.
# ============================================================

def test_equal_price_sort_is_stable_across_page_boundary(env):
    first = scoped_search(
        env,
        sort_by="price_asc",
        limit=4,
        offset=0,
    )

    second = scoped_search(
        env,
        sort_by="price_asc",
        limit=4,
        offset=4,
    )

    repeated = scoped_search(
        env,
        sort_by="price_asc",
        limit=4,
        offset=0,
    )

    assert first["total"] == second["total"] == 15

    assert [
        row["id"]
        for row in first["items"]
    ] == [
        env["ids"][i]
        for i in (5, 4, 3, 2)
    ]

    assert [
        row["id"]
        for row in second["items"]
    ] == [
        env["ids"][i]
        for i in (1, 14, 13, 12)
    ]

    assert repeated["items"] == first["items"]


# ============================================================
# TEST 03
# Combined filters: brand, price, availability, then reset.
# ============================================================

def test_ui_combined_filters_brand_price_stock_and_reset(env):
    panel, _ = listing(env)

    panel.brand.value = str(env["alpha"])
    panel.min_price.value = "10000000.00"
    panel.max_price.value = "15000000.00"
    panel.only_in_stock.value = True
    panel.sort.value = "price_asc"

    panel.apply_filters()

    assert panel.total == 7

    assert {
        row["id"]
        for row in panel.items
    } == {
        env["ids"][i]
        for i in (1, 2, 4, 5, 6, 7, 8)
    }

    assert len(panel.cards.controls) == 7

    panel.reset_filters()

    assert panel.offset == 0
    assert panel.brand.value == "ALL"
    assert panel.only_in_stock.value is False
    assert panel.sort.value == "newest"


# ============================================================
# TEST 04
# Search exact product SKU from public UI.
# ============================================================

def test_ui_keyword_by_sku_resolves_one_product(env):
    panel, _ = listing(env)

    panel.keyword.value = (
        f"T47-{env['token']}-11"
    )

    panel.apply_filters()

    assert panel.total == 1
    assert panel.items[0]["id"] == env["ids"][11]


# ============================================================
# TEST 05
# Search by brand name.
# ============================================================

def test_brand_name_search_filters_to_correct_products(env):
    result = env["service"].search_public(
        keyword=f"{env['prefix']} Alpha",
        limit=50,
    )

    assert result["total"] == 8

    assert {
        item["id"]
        for item in result["items"]
    } == {
        env["ids"][i]
        for i in range(1, 9)
    }


# ============================================================
# TEST 06
# Open detail from selected card, then go back.
# ============================================================

def test_public_detail_navigation_uses_selected_card_and_real_service(env):
    panel, page = listing(env)

    selected_id = panel.items[1]["id"]

    buttons = [
        child
        for child in (
            panel.cards.controls[1]
            .content.content.controls
        )
        if isinstance(child, ft.Button)
    ]

    assert len(buttons) == 1

    buttons[0].on_click(None)

    assert page.routes == [
        f"/products/{selected_id}"
    ]

    decision = check_route_access(
        route=page.routes[-1],
        role="GUEST",
    )

    assert decision.status == RouteStatus.ALLOW

    detail = PublicProductDetailPanel(
        page,
        product_id=selected_id,
        products=env["service"],
    )

    detail.load()

    assert detail.message.value in (None, "")
    assert len(detail.content.controls) == 1

    shown = " ".join(
        visible_text(detail.root)
    )

    assert (
        f"Mã sản phẩm: T47-{env['token']}-"
        in shown
    )

    assert "8.765.432" not in shown
    assert "min_stock" not in shown

    detail.back_to_products()

    assert page.routes[-1] == "/products"


# ============================================================
# TEST 07
# Protect private fields in list and detail responses.
# ============================================================

def test_public_projection_prevents_private_fields_in_list_and_detail(env):
    result = scoped_search(
        env,
        limit=50,
    )

    assert result["total"] == 15

    for row in result["items"]:
        assert set(row) <= PUBLIC_FIELDS
        assert not (
            set(row) & PRIVATE_FIELDS
        )

    for index in (1, 3, 15):
        row = env["service"].get_public_detail(
            product_id=env["ids"][index]
        )

        assert set(row) <= PUBLIC_FIELDS
        assert not (
            set(row) & PRIVATE_FIELDS
        )


# ============================================================
# TEST 08
# Out-of-stock products remain visible.
# ============================================================

def test_out_of_stock_is_public_but_labeled_unavailable(env):
    row = env["service"].get_public_detail(
        product_id=env["ids"][3]
    )

    assert not bool(row["in_stock"])

    page = FakePage()

    panel = PublicProductDetailPanel(
        page,
        product_id=env["ids"][3],
        products=env["service"],
    )

    panel.load()

    rendered = " ".join(
        visible_text(panel.root)
    )

    assert "Tạm hết hàng" in rendered


# ============================================================
# TEST 09
# Hide discontinued products from all public endpoints.
# ============================================================

def test_discontinued_product_hidden_from_list_and_detail(env):
    result = scoped_search(
        env,
        limit=50,
    )

    visible_ids = {
        row["id"]
        for row in result["items"]
    }

    assert env["ids"][16] not in visible_ids

    with pytest.raises(AppError) as error:
        env["service"].get_public_detail(
            product_id=env["ids"][16]
        )

    assert error.value.error_code == "NOT_FOUND"


# ============================================================
# TEST 10
# Immediately hide products after status changes.
# ============================================================

def test_discontinuing_existing_product_invalidates_detail(env):
    product_id = env["ids"][1]

    # Product initially exists and is ACTIVE.
    assert env["service"].get_public_detail(
        product_id=product_id
    )

    # Direct DB change is limited to this test fixture.
    env["db"].execute(
        text("""
            UPDATE products
            SET status = 'DISCONTINUED'
            WHERE id = :id
        """),
        {
            "id": product_id,
        },
    )

    with pytest.raises(AppError) as error:
        env["service"].get_public_detail(
            product_id=product_id
        )

    assert error.value.error_code == "NOT_FOUND"

    assert scoped_search(
        env,
        limit=50,
    )["total"] == 14


# ============================================================
# TEST 11
# Reject invalid price range without exposing DB details.
# ============================================================

def test_invalid_price_range_is_handled_without_leaking_details(env):
    panel, _ = listing(env)

    panel.min_price.value = "20000000.00"
    panel.max_price.value = "10000000.00"

    panel.apply_filters()

    assert panel.items == []
    assert panel.cards.controls == []
    assert panel.total == 0

    assert "Khoảng giá" in panel.error.value


# ============================================================
# TEST 12
# Show empty state when no products match.
# ============================================================

def test_no_match_has_empty_state_and_no_detail_request(env):
    panel, _ = listing(env)

    panel.keyword.value = (
        f"{env['prefix']} non-existent-model"
    )

    panel.apply_filters()

    assert panel.total == 0

    assert panel.next_button.disabled
    assert panel.previous_button.disabled

    rendered = " ".join(
        visible_text(panel.cards)
    )

    assert "Không có sản phẩm" in rendered


# ============================================================
# TEST 13
# Public browsing must never change stock or cost.
# ============================================================

def test_public_browsing_does_not_change_stock_or_cost(env):
    db = env["db"]

    def snapshot():
        rows = db.execute(
            text("""
                SELECT
                    id,
                    stock,
                    cost_price
                FROM products
                WHERE sku LIKE :prefix
                ORDER BY id
            """),
            {
                "prefix": f"T47-{env['token']}-%",
            },
        ).mappings().all()

        return [
            dict(row)
            for row in rows
        ]

    before = snapshot()

    panel, _ = listing(env)
    panel.next_page()

    for product in panel.items:
        env["service"].get_public_detail(
            product_id=product["id"]
        )

    after = snapshot()

    assert len(before) == 16
    assert before == after
