
"""Task 48 / US09-T01: cart UI and product-detail add button."""

from decimal import Decimal
from pathlib import Path

import flet as ft
import pytest

from models.app_error import AppError
from services.cart_session import CartSession
from ui.pages.cart_page import CartPanel
from ui.pages.public_product_detail_page import PublicProductDetailPanel


class FakeStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


class FakePage:
    def __init__(self):
        self.routes = []
        self.updates = 0

    def navigate(self, route):
        self.routes.append(route)

    def update(self):
        self.updates += 1


class FakeProducts:
    def __init__(self):
        self.calls = []
        self.error = None
        self.rows = {
            1: self.make_product(
                1,
                Decimal("1250000.50"),
            ),
            2: self.make_product(
                2,
                Decimal("2000000.00"),
                in_stock=False,
            ),
        }

    @staticmethod
    def make_product(
        product_id,
        price,
        in_stock=True,
    ):
        return {
            "id": product_id,
            "sku": f"SKU-{product_id}",
            "name": f"Phone {product_id}",
            "brand_id": 1,
            "brand_name": "Demo Brand",
            "storage": "128GB",
            "color": "Black",
            "description": "Demo phone",
            "image_url": None,
            "sell_price": price,
            "in_stock": in_stock,
            # Injected private data must never be rendered.
            "cost_price": Decimal("9876543.21"),
            "stock": 17,
            "min_stock": 3,
        }

    def get_public_detail(self, *, product_id):
        self.calls.append(product_id)

        if self.error is not None:
            raise self.error

        if product_id not in self.rows:
            raise AppError(
                "NOT_FOUND",
                "Product not found",
            )

        return dict(self.rows[product_id])


def all_text(control):
    values = []

    if isinstance(control, ft.Text):
        values.append(str(control.value or ""))

    for child in getattr(control, "controls", None) or []:
        values.extend(all_text(child))

    content = getattr(control, "content", None)
    if content is not None:
        values.extend(all_text(content))

    return values


@pytest.fixture
def env():
    store = FakeStore()
    cart = CartSession(store)
    products = FakeProducts()
    page = FakePage()

    def authorize():
        return None

    panel = CartPanel(
        page,
        cart=cart,
        products=products,
        authorize=authorize,
    )

    return panel, page, cart, products, store


def test_empty_cart_shows_message_and_zero_total(env):
    panel, _, _, _, _ = env

    panel.load()

    rendered = " ".join(all_text(panel.root))

    assert "Giỏ hàng đang trống" in rendered
    assert "0/20 dòng sản phẩm" in rendered
    assert "0 ₫" in panel.total_text.value
    assert panel.total == Decimal(0)


def test_cart_calculates_total_using_decimal(env):
    panel, _, cart, products, _ = env

    cart.add(1, 2)
    cart.add(2, 1)

    panel.load()

    assert products.calls == [1, 2]
    assert panel.total == Decimal("4500001.00")
    assert "4.500.001 ₫" in panel.total_text.value


def test_cart_renders_sku_quantity_and_line_total(env):
    panel, _, cart, _, _ = env

    cart.add(1, 2)
    panel.load()

    rendered = " ".join(all_text(panel.root))

    assert "Phone 1" in rendered
    assert "SKU-1" in rendered
    assert "1.250.001 ₫" in rendered
    assert "2.500.001 ₫" in rendered


def test_out_of_stock_product_stays_visible(env):
    panel, _, cart, _, _ = env

    cart.add(2)
    panel.load()

    rendered = " ".join(all_text(panel.root))

    assert "Phone 2" in rendered
    assert "Tạm hết hàng" in rendered


def test_discontinued_product_can_be_removed(env):
    panel, _, cart, _, _ = env

    cart.add(9)
    panel.load()

    rendered = " ".join(all_text(panel.root))

    assert "không còn kinh doanh" in rendered
    assert panel.total == Decimal(0)

    panel.remove_product(9)

    assert cart.items() == []


def test_update_quantity_changes_total(env):
    panel, page, cart, _, _ = env

    cart.add(1)
    panel.load()

    panel.update_quantity(1, "3")

    assert cart.items() == [
        {"product_id": 1, "quantity": 3}
    ]
    assert panel.total == Decimal("3750001.50")
    assert page.updates == 1


def test_remove_one_line_updates_remaining_total(env):
    panel, _, cart, _, _ = env

    cart.add(1)
    cart.add(2)

    panel.load()
    panel.remove_product(1)

    assert cart.line_count() == 1
    assert cart.has_product(2)
    assert panel.total == Decimal("2000000.00")


def test_clear_cart(env):
    panel, _, cart, _, _ = env

    cart.add(1)
    cart.add(2)

    panel.clear_cart()

    assert cart.items() == []
    assert panel.total == Decimal(0)
    assert "0 ₫" in panel.total_text.value


@pytest.mark.parametrize(
    "bad_quantity",
    ["", "0", "-1", "abc", "1.5", None],
)
def test_invalid_quantity_is_rejected(env, bad_quantity):
    panel, _, cart, _, _ = env

    cart.add(1)
    panel.load()

    panel.update_quantity(1, bad_quantity)

    assert cart.items()[0]["quantity"] == 1
    assert panel.error.value


def test_authorization_failure_prevents_quantity_change(env):
    _, page, cart, products, _ = env

    cart.add(1)

    def deny():
        raise AppError(
            "FORBIDDEN",
            "Không có quyền sử dụng giỏ hàng.",
        )

    panel = CartPanel(
        page,
        cart=cart,
        products=products,
        authorize=deny,
    )

    panel.load()
    panel.update_quantity(1, "5")

    assert cart.items()[0]["quantity"] == 1
    assert "Không có quyền" in panel.error.value


def test_authorization_failure_prevents_deletion(env):
    _, page, cart, products, _ = env

    cart.add(1)

    def deny():
        raise AppError(
            "FORBIDDEN",
            "Không có quyền.",
        )

    panel = CartPanel(
        page,
        cart=cart,
        products=products,
        authorize=deny,
    )

    panel.remove_product(1)

    assert cart.line_count() == 1


def test_unexpected_service_error_is_not_exposed(env):
    panel, _, cart, products, _ = env

    cart.add(1)
    products.error = RuntimeError(
        "private database password"
    )

    panel.load()

    assert "password" not in panel.error.value
    assert "Không thể tải" in panel.error.value
    assert panel.total == Decimal(0)


def test_private_product_data_is_never_rendered(env):
    panel, _, cart, _, _ = env

    cart.add(1)
    panel.load()

    rendered = " ".join(all_text(panel.root))

    assert "9.876.543" not in rendered
    assert "cost_price" not in rendered
    assert "min_stock" not in rendered
    assert "17 chiếc" not in rendered


def test_cart_uses_updated_public_price(env):
    panel, _, cart, products, _ = env

    cart.add(1)
    panel.load()

    assert panel.total == Decimal("1250000.50")

    products.rows[1]["sell_price"] = Decimal("1500000.00")
    panel.load()

    assert panel.total == Decimal("1500000.00")
    assert "1.500.000 ₫" in panel.total_text.value


def test_continue_shopping_opens_public_products(env):
    panel, page, _, _, _ = env

    panel.continue_shopping()

    assert page.routes == ["/products"]


def test_cart_state_survives_page_reconstruction(env):
    panel, page, cart, products, _ = env

    cart.add(1, 2)
    panel.load()

    second_panel = CartPanel(
        page,
        cart=cart,
        products=products,
        authorize=lambda: None,
    )

    second_panel.load()

    assert second_panel.total == Decimal("2500001.00")
    assert second_panel.counter.value == "1/20 dòng sản phẩm"


def test_customer_detail_has_add_button():
    page = FakePage()
    products = FakeProducts()
    selected = []

    panel = PublicProductDetailPanel(
        page,
        product_id=1,
        products=products,
        on_add=selected.append,
    )

    panel.load()

    assert panel.add_button is not None
    assert panel.add_button.disabled is False

    panel.add_to_cart()

    assert selected == [1]


def test_guest_detail_does_not_expose_add_button():
    panel = PublicProductDetailPanel(
        FakePage(),
        product_id=1,
        products=FakeProducts(),
    )

    panel.load()

    assert panel.add_button is None


def test_out_of_stock_detail_cannot_add():
    selected = []

    panel = PublicProductDetailPanel(
        FakePage(),
        product_id=2,
        products=FakeProducts(),
        on_add=selected.append,
    )

    panel.load()
    panel.add_to_cart()

    assert panel.add_button.disabled is True
    assert selected == []


def test_missing_detail_cannot_add():
    selected = []

    panel = PublicProductDetailPanel(
        FakePage(),
        product_id=99,
        products=FakeProducts(),
        on_add=selected.append,
    )

    panel.load()
    panel.add_to_cart()

    assert panel.add_button.disabled is True
    assert selected == []


def test_main_connects_cart_route_and_customer_guard():
    source = Path("main.py").read_text(encoding="utf-8")

    assert 'if route == "/cart":' in source
    assert "build_cart_page(" in source
    assert "authorize=require_customer" in source
    assert "add_product_to_cart" in source
    assert "CartSession(page.session.store)" in source
