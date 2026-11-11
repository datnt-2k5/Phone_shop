
"""Task 46 / US08-T04: public product detail and dynamic route tests."""

from decimal import Decimal
from pathlib import Path

import flet as ft
import pytest

from models.app_error import AppError
from ui.pages.public_product_detail_page import PublicProductDetailPanel
from ui.pages.public_products_page import PublicProductsPanel
from ui.route_guard import (
    RouteStatus,
    check_route_access,
    public_product_id,
)


def product(product_id=7):
    return {
        "id": product_id,
        "sku": f"SKU-{product_id}",
        "name": f"Phone {product_id}",
        "brand_id": 1,
        "brand_name": "Test Brand",
        "storage": "128GB",
        "color": "Black",
        "description": "Điện thoại dùng để kiểm thử.",
        "image_url": None,
        "sell_price": Decimal("12000000.00"),
        "in_stock": True,
        # Deliberately injected private fields.
        "cost_price": Decimal("9876543.21"),
        "stock": 17,
        "min_stock": 5,
        "updated_by": 99,
    }


class FakePage:
    def __init__(self):
        self.updates = 0
        self.routes = []

    def update(self):
        self.updates += 1

    def navigate(self, route):
        self.routes.append(route)


class FakeProducts:
    def __init__(self):
        self.row = product()
        self.rows = [product(7), product(8)]
        self.detail_calls = []
        self.search_calls = []
        self.error = None

    def get_public_detail(self, *, product_id):
        self.detail_calls.append(product_id)

        if self.error is not None:
            raise self.error

        return dict(self.row)

    def search_public(self, **kwargs):
        self.search_calls.append(kwargs)

        return {
            "items": list(self.rows),
            "total": len(self.rows),
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
        }


class FakeCatalog:
    def list_brands(self, *, limit, offset):
        return []


def text_values(control):
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


def open_button(card):
    buttons = [
        control
        for control in card.content.content.controls
        if isinstance(control, ft.Button)
    ]
    assert len(buttons) == 1
    return buttons[0]


@pytest.fixture
def env():
    page = FakePage()
    products = FakeProducts()

    panel = PublicProductDetailPanel(
        page,
        product_id=7,
        products=products,
    )

    return panel, page, products


@pytest.fixture
def listing():
    page = FakePage()
    products = FakeProducts()

    panel = PublicProductsPanel(
        page,
        products=products,
        catalog=FakeCatalog(),
    )
    panel.load()

    return panel, page, products


@pytest.fixture
def home():
    page = FakePage()
    products = FakeProducts()

    panel = PublicProductsPanel(
        page,
        products=products,
        catalog=FakeCatalog(),
        home=True,
    )
    panel.load()

    return panel, page, products


@pytest.mark.parametrize(
    "route,expected",
    [
        ("/products/1", 1),
        ("/products/42", 42),
        (
            "/products/9223372036854775807",
            9_223_372_036_854_775_807,
        ),
    ],
)
def test_valid_product_detail_url(route, expected):
    assert public_product_id(route) == expected


@pytest.mark.parametrize(
    "route",
    [
        "",
        "/products",
        "/products/",
        "/products/0",
        "/products/01",
        "/products/-1",
        "/products/+1",
        "/products/1.5",
        "/products/abc",
        "/products/1/2",
        "/products/１",
        "/products/9223372036854775808",
        "/admin/products/1",
    ],
)
def test_invalid_product_detail_urls(route):
    assert public_product_id(route) is None

    if route != "/products":
        result = check_route_access(
            route=route,
            role="GUEST",
        )
        assert result.status == RouteStatus.NOT_FOUND


@pytest.mark.parametrize(
    "role",
    [
        "GUEST",
        "CUSTOMER",
        "ADMIN",
        "SUPER_ADMIN",
    ],
)
def test_detail_route_is_public_for_every_known_role(role):
    result = check_route_access(
        route="/products/7",
        role=role,
    )

    assert result.status == RouteStatus.ALLOW
    assert result.redirect_to is None


def test_unknown_role_cannot_open_detail():
    result = check_route_access(
        route="/products/7",
        role="FAKE_ADMIN",
    )

    assert result.status == RouteStatus.FORBIDDEN


def test_static_product_route_still_works():
    result = check_route_access(
        route="/products",
        role="GUEST",
    )

    assert result.status == RouteStatus.ALLOW


def test_detail_load_shows_public_fields_only(env):
    panel, _, products = env
    panel.load()

    assert products.detail_calls == [7]
    assert len(panel.content.controls) == 1

    rendered = " ".join(text_values(panel.root))

    assert "Phone 7" in rendered
    assert "SKU-7" in rendered
    assert "Test Brand" in rendered
    assert "128GB" in rendered
    assert "Black" in rendered
    assert "12.000.000" in rendered
    assert "Còn hàng" in rendered

    assert "9.876.543" not in rendered
    assert "updated_by" not in rendered
    assert "min_stock" not in rendered
    assert "17 chiếc" not in rendered


def test_missing_product_shows_404(env):
    panel, _, products = env
    products.error = AppError(
        "NOT_FOUND",
        "Product hidden",
    )

    panel.load()

    assert "404" in panel.message.value
    assert panel.content.controls == []


def test_invalid_product_id_error_is_safe(env):
    panel, _, products = env
    products.error = AppError(
        "VALIDATION_ERROR",
        "Invalid ID",
    )

    panel.load()

    assert "không hợp lệ" in panel.message.value
    assert panel.content.controls == []


def test_other_business_error_is_not_exposed(env):
    panel, _, products = env
    products.error = AppError(
        "DATABASE_ERROR",
        "private internal message",
    )

    panel.load()

    assert panel.message.value == (
        "Không thể tải chi tiết sản phẩm."
    )
    assert "private" not in panel.message.value


def test_unexpected_error_is_not_exposed(env):
    panel, _, products = env
    products.error = RuntimeError(
        "private database credential"
    )

    panel.load()

    assert panel.message.value == (
        "Không thể tải chi tiết sản phẩm."
    )
    assert panel.content.controls == []


def test_missing_image_shows_placeholder(env):
    panel, _, _ = env
    panel.load()

    view = panel.content.controls[0]
    picture = view.controls[0]

    assert isinstance(picture, ft.Container)
    assert "Chưa có ảnh" in " ".join(
        text_values(picture)
    )


def test_product_image_uses_public_image_url(env):
    panel, _, products = env
    products.row["image_url"] = (
        "https://example.test/phone.png"
    )

    panel.load()

    picture = panel.content.controls[0].controls[0]

    assert isinstance(picture, ft.Image)
    assert picture.src == (
        "https://example.test/phone.png"
    )


def test_out_of_stock_is_displayed(env):
    panel, _, products = env
    products.row["in_stock"] = False

    panel.load()

    rendered = " ".join(text_values(panel.root))

    assert "Tạm hết hàng" in rendered
    assert "Còn hàng" not in rendered


def test_missing_description_has_fallback(env):
    panel, _, products = env
    products.row["description"] = None

    panel.load()

    rendered = " ".join(text_values(panel.root))

    assert "Chưa có mô tả sản phẩm." in rendered


def test_back_button_opens_public_listing(env):
    panel, page, _ = env

    panel.back_to_products()

    assert page.routes == ["/products"]


def test_initial_detail_load_does_not_require_page_update(env):
    panel, page, _ = env

    panel.load(redraw=False)

    assert page.updates == 0

    panel.load(redraw=True)

    assert page.updates == 1


def test_listing_card_opens_selected_product(listing):
    panel, page, _ = listing

    button = open_button(panel.cards.controls[0])
    button.on_click(None)

    assert page.routes == ["/products/7"]


def test_home_card_also_opens_product_detail(home):
    panel, page, _ = home

    button = open_button(panel.cards.controls[0])
    button.on_click(None)

    assert page.routes == ["/products/7"]


def test_cards_keep_distinct_product_ids(listing):
    panel, page, _ = listing

    first = open_button(panel.cards.controls[0])
    second = open_button(panel.cards.controls[1])

    second.on_click(None)
    first.on_click(None)

    assert page.routes == [
        "/products/8",
        "/products/7",
    ]


def test_static_card_without_handler_stays_read_only():
    card = PublicProductsPanel.make_card(
        product(7)
    )

    buttons = [
        control
        for control in card.content.content.controls
        if isinstance(control, ft.Button)
    ]

    assert buttons == []


def test_main_connects_dynamic_detail_route():
    source = Path("main.py").read_text(
        encoding="utf-8"
    )

    assert "public_product_id(route)" in source
    assert "build_public_product_detail_page(" in source
    assert "permission_route" in source
    assert "product_id=detail_id" in source
