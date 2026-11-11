
"""Task 45 / US08-T03: public home and listing UI tests."""

from decimal import Decimal
from pathlib import Path

import flet as ft
import pytest

from models.app_error import AppError
from ui.pages.public_products_page import (
    HOME_SIZE,
    PAGE_SIZE,
    PublicProductsPanel,
)


class FakePage:
    def __init__(self):
        self.updates = 0
        self.routes = []

    def update(self):
        self.updates += 1

    def navigate(self, route):
        self.routes.append(route)


def make_product(product_id):
    return {
        "id": product_id,
        "sku": f"SKU-{product_id}",
        "name": f"Phone {product_id}",
        "brand_id": 1,
        "brand_name": "Test Brand",
        "storage": "128GB",
        "color": "Black",
        "description": "Public phone",
        "image_url": None,
        "sell_price": Decimal("12000000.00"),
        "in_stock": product_id % 3 != 0,
        # Deliberately injected private data.
        "cost_price": Decimal("9876543.21"),
        "stock": 17,
        "min_stock": 5,
        "updated_by": 99,
    }


class FakeProducts:
    def __init__(self):
        self.items = [
            make_product(i)
            for i in range(1, 17)
        ]
        self.calls = []
        self.error = None

    def search_public(self, **kwargs):
        self.calls.append(kwargs)

        if self.error is not None:
            raise self.error

        if kwargs.get("keyword") == "no results":
            filtered = []
        else:
            filtered = self.items

        offset = kwargs["offset"]
        limit = kwargs["limit"]

        return {
            "items": filtered[offset:offset + limit],
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
        }


class FakeCatalog:
    def __init__(self):
        self.calls = []
        self.error = None

    def list_brands(self, *, limit, offset):
        self.calls.append({
            "limit": limit,
            "offset": offset,
        })

        if self.error is not None:
            raise self.error

        return [
            {"id": 1, "name": "Test Brand"},
            {"id": 2, "name": "Another Brand"},
        ]


@pytest.fixture
def env():
    page = FakePage()
    products = FakeProducts()
    catalog = FakeCatalog()

    panel = PublicProductsPanel(
        page,
        products=products,
        catalog=catalog,
    )

    panel.load()

    return panel, page, products, catalog


@pytest.fixture
def home_env():
    page = FakePage()
    products = FakeProducts()
    catalog = FakeCatalog()

    panel = PublicProductsPanel(
        page,
        products=products,
        catalog=catalog,
        home=True,
    )

    panel.load()

    return panel, page, products, catalog


def text_values(control):
    """Collect visible Text control values recursively."""
    values = []

    if isinstance(control, ft.Text):
        values.append(str(control.value or ""))

    children = getattr(control, "controls", None)
    if children is not None:
        for child in children:
            values.extend(text_values(child))

    content = getattr(control, "content", None)
    if content is not None:
        values.extend(text_values(content))

    return values


def test_home_loads_six_newest_products(home_env):
    panel, _, products, catalog = home_env

    assert panel.home is True
    assert panel.page_size == HOME_SIZE
    assert products.calls[0] == {
        "sort_by": "newest",
        "limit": 6,
        "offset": 0,
    }
    assert len(panel.cards.controls) == 6
    assert catalog.calls == []


def test_home_opens_products_route(home_env):
    panel, page, _, _ = home_env

    panel.open_products()

    assert page.routes == ["/products"]


def test_listing_loads_brand_options(env):
    panel, _, _, catalog = env

    assert catalog.calls == [
        {"limit": 100, "offset": 0}
    ]
    assert len(panel.brand.options) == 3
    assert panel.brand.options[0].key == "ALL"
    assert panel.brand.options[1].key == "1"
    assert panel.brand.options[2].key == "2"


def test_listing_loads_first_page(env):
    panel, _, products, _ = env

    assert panel.home is False
    assert panel.page_size == PAGE_SIZE
    assert products.calls[0]["limit"] == 12
    assert products.calls[0]["offset"] == 0
    assert panel.total == 16
    assert len(panel.cards.controls) == 12
    assert panel.page_label.value == "Trang 1/2"
    assert panel.previous_button.disabled is True
    assert panel.next_button.disabled is False


def test_search_passes_all_public_filters(env):
    panel, _, products, _ = env

    panel.keyword.value = "  iPhone  "
    panel.brand.value = "2"
    panel.min_price.value = " 1000000 "
    panel.max_price.value = " 20000000 "
    panel.only_in_stock.value = True
    panel.sort.value = "price_desc"

    panel.apply_filters()

    params = products.calls[-1]

    assert params["keyword"] == "  iPhone  "
    assert params["brand_id"] == 2
    assert params["min_price"] == "1000000"
    assert params["max_price"] == "20000000"
    assert params["only_in_stock"] is True
    assert params["sort_by"] == "price_desc"
    assert params["limit"] == 12
    assert params["offset"] == 0


def test_search_resets_pagination(env):
    panel, _, products, _ = env

    panel.next_page()
    assert panel.offset == 12

    panel.keyword.value = "Phone"
    panel.apply_filters()

    assert panel.offset == 0
    assert products.calls[-1]["offset"] == 0


def test_next_and_previous_page(env):
    panel, _, products, _ = env

    panel.next_page()

    assert panel.offset == 12
    assert len(panel.cards.controls) == 4
    assert panel.page_label.value == "Trang 2/2"
    assert panel.next_button.disabled is True
    assert panel.previous_button.disabled is False

    panel.previous_page()

    assert panel.offset == 0
    assert products.calls[-1]["offset"] == 0
    assert panel.page_label.value == "Trang 1/2"


def test_next_page_cannot_go_past_last_page(env):
    panel, _, products, _ = env

    panel.next_page()
    count = len(products.calls)

    panel.next_page()

    assert panel.offset == 12
    assert len(products.calls) == count


def test_previous_page_cannot_go_below_zero(env):
    panel, _, products, _ = env

    count = len(products.calls)
    panel.previous_page()

    assert panel.offset == 0
    assert len(products.calls) == count


def test_reset_filters_restores_defaults(env):
    panel, _, products, _ = env

    panel.keyword.value = "Phone"
    panel.brand.value = "2"
    panel.min_price.value = "100"
    panel.max_price.value = "200"
    panel.only_in_stock.value = True
    panel.sort.value = "price_asc"
    panel.offset = 12

    panel.reset_filters()

    assert panel.keyword.value == ""
    assert panel.brand.value == "ALL"
    assert panel.min_price.value == ""
    assert panel.max_price.value == ""
    assert panel.only_in_stock.value is False
    assert panel.sort.value == "newest"
    assert panel.offset == 0
    assert products.calls[-1]["brand_id"] is None


def test_no_results_shows_empty_state(env):
    panel, _, _, _ = env

    panel.keyword.value = "no results"
    panel.apply_filters()

    assert panel.total == 0
    assert panel.page_label.value == "Trang 1/1"
    assert panel.next_button.disabled is True
    assert panel.previous_button.disabled is True
    assert "Không có sản phẩm" in " ".join(
        text_values(panel.cards)
    )


def test_service_business_error_is_displayed(env):
    panel, _, products, _ = env

    products.error = AppError(
        "VALIDATION_ERROR",
        "Khoảng giá không hợp lệ.",
    )
    panel.apply_filters()

    assert panel.total == 0
    assert panel.items == []
    assert panel.cards.controls == []
    assert "Khoảng giá" in panel.error.value


def test_unexpected_error_does_not_leak_exception(env):
    panel, _, products, _ = env

    products.error = RuntimeError(
        "private database credentials"
    )
    panel.apply_filters()

    assert panel.error.value == (
        "Không tải được danh sách sản phẩm."
    )
    assert "credentials" not in panel.error.value
    assert panel.cards.controls == []


def test_invalid_brand_selection_is_rejected(env):
    panel, _, products, _ = env

    count = len(products.calls)
    panel.brand.value = "invalid"
    panel.apply_filters()

    assert len(products.calls) == count
    assert "Bộ lọc không hợp lệ" in panel.error.value


def test_brand_load_failure_does_not_search():
    page = FakePage()
    products = FakeProducts()
    catalog = FakeCatalog()
    catalog.error = RuntimeError("DB offline")

    panel = PublicProductsPanel(
        page,
        products=products,
        catalog=catalog,
    )
    panel.load()

    assert "Không thể tải" in panel.error.value
    assert products.calls == []


def test_public_card_formats_sell_price(env):
    panel, _, _, _ = env

    card = panel.cards.controls[0]
    rendered = " ".join(text_values(card))

    assert "12.000.000" in rendered
    assert "Test Brand" in rendered
    assert "128GB" in rendered


def test_public_card_does_not_render_private_fields(env):
    panel, _, _, _ = env

    card = panel.cards.controls[0]
    rendered = " ".join(text_values(card))

    assert "9.876.543" not in rendered
    assert "updated_by" not in rendered
    assert "min_stock" not in rendered
    assert "17 chiếc" not in rendered


def test_public_card_shows_in_stock_status():
    card = PublicProductsPanel.make_card(
        make_product(1)
    )
    rendered = " ".join(text_values(card))

    assert "Còn hàng" in rendered


def test_public_card_shows_out_of_stock_status():
    card = PublicProductsPanel.make_card(
        make_product(3)
    )
    rendered = " ".join(text_values(card))

    assert "Tạm hết hàng" in rendered


def test_public_card_without_image_has_placeholder():
    card = PublicProductsPanel.make_card(
        make_product(1)
    )
    rendered = " ".join(text_values(card))

    assert "Chưa có ảnh" in rendered


def test_public_card_with_image_uses_image_control():
    product = make_product(1)
    product["image_url"] = "https://example.test/phone.png"

    card = PublicProductsPanel.make_card(product)
    container = card.content
    column = container.content
    image = column.controls[0]

    assert isinstance(image, ft.Image)
    assert image.src == "https://example.test/phone.png"


def test_listing_never_requests_admin_search(env):
    _, _, products, _ = env

    assert products.calls
    assert all(
        "session_store" not in call
        and "status" not in call
        and "low_stock" not in call
        for call in products.calls
    )


def test_main_registers_both_public_pages():
    source = Path("main.py").read_text(
        encoding="utf-8"
    )

    assert 'if route == "/":' in source
    assert (
        "return build_public_home_page(page)"
        in source
    )
    assert 'if route == "/products":' in source
    assert (
        "return build_public_products_page(page)"
        in source
    )
