
"""Task 52: checkout Flet page and receipt unit tests."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from models.app_error import AppError
from services.cart_session import CartSession
from services.checkout_order_service import CheckoutOrderResult
from ui.pages.checkout_page import (
    CheckoutPanel,
    build_order_receipt_page,
)


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
    def __init__(self, store):
        self.session = SimpleNamespace(store=store)
        self.routes = []
        self.dialogs = []
        self.updates = 0

    def update(self):
        self.updates += 1

    def navigate(self, route):
        self.routes.append(route)

    async def push_route(self, route):
        if getattr(self, "fail_push_route", False):
            raise RuntimeError("route failed")

        self.navigate(route)

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)


class FakeProducts:
    def get_public_detail(self, *, product_id):
        return {
            "id": product_id,
            "name": "Demo Phone",
            "sell_price": Decimal("1000000.00"),
            "in_stock": True,
        }


class FakeService:
    def __init__(self):
        self.calls = []
        self.error = None

    def create(self, *, session_store, checkout_request):
        self.calls.append(checkout_request)

        if self.error is not None:
            raise self.error

        return CheckoutOrderResult(
            outcome="CREATED",
            order={
                "id": 42,
                "code": "DH00000042",
                "status": "PENDING",
                "total_amount": Decimal("1000000.00"),
            },
            message="Đơn hàng đã được tiếp nhận.",
        )


def build_panel():
    store = FakeStore()
    cart = CartSession(store)
    cart.add(5, 1)

    page = FakePage(store)
    service = FakeService()

    panel = CheckoutPanel(
        page,
        authorize=lambda: None,
        cart=cart,
        products=FakeProducts(),
        service=service,
    )

    panel.receiver_name.value = "Nguyen Van A"
    panel.receiver_phone.value = "0912345678"
    panel.receiver_address.value = "Cao Lanh, Dong Thap"
    panel.note.value = ""

    panel.load()

    return page, cart, service, panel


def test_checkout_page_loads_cart_summary():
    _page, _cart, _service, panel = build_panel()

    assert panel.submit_button.disabled is False
    assert len(panel.summary.controls) == 1
    assert "1.000.000" in panel.estimated_total.value


def test_success_navigates_to_created_order():
    page, cart, service, panel = build_panel()

    asyncio.run(panel.place_order())

    assert page.routes == ["/my-orders/42"]
    assert cart.items() == []
    assert len(service.calls) == 1
    assert panel.busy is False


def test_business_error_keeps_cart_and_current_page():
    page, cart, service, panel = build_panel()

    service.error = AppError(
        "PRODUCT_UNAVAILABLE",
        "Sản phẩm không khả dụng.",
    )

    asyncio.run(panel.place_order())

    assert page.routes == []
    assert cart.line_count() == 1
    assert panel.busy is False
    assert panel.submit_button.disabled is False
    assert len(page.dialogs) == 1


def test_invalid_receiver_does_not_call_service():
    page, cart, service, panel = build_panel()
    panel.receiver_phone.value = ""

    asyncio.run(panel.place_order())

    assert service.calls == []
    assert cart.line_count() == 1
    assert page.routes == []


def test_busy_checkout_ignores_duplicate_click():
    page, cart, service, panel = build_panel()
    panel.busy = True

    asyncio.run(panel.place_order())

    assert service.calls == []
    assert cart.line_count() == 1
    assert page.routes == []


def test_empty_cart_disables_checkout_button():
    _page, cart, _service, panel = build_panel()

    cart.clear()
    panel.load()

    assert panel.submit_button.disabled is True
    assert "Giỏ hàng đang trống" in (
        panel.summary.controls[0].value
    )


def test_receipt_rejects_other_customer_order(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOrders:
        def __init__(self, session):
            self.session = session

        def get_by_id(self, order_id):
            assert order_id == 42
            return {
                "id": 42,
                "customer_id": 7,
                "code": "DH00000042",
                "status": "PENDING",
                "total_amount": Decimal("1000000.00"),
            }

        def list_items(self, order_id):
            return []

    monkeypatch.setattr(
        "ui.pages.checkout_page.SessionLocal",
        FakeSession,
    )
    monkeypatch.setattr(
        "ui.pages.checkout_page.OrderRepository",
        FakeOrders,
    )

    page = FakePage(FakeStore())

    result = build_order_receipt_page(
        page,
        order_id=42,
        customer_id=8,
        authorize=lambda: None,
    )

    assert "404" in result.controls[0].value


def test_receipt_shows_only_owned_order(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOrders:
        def __init__(self, session):
            self.session = session

        def get_by_id(self, order_id):
            return {
                "id": order_id,
                "customer_id": 7,
                "code": "DH00000042",
                "status": "PENDING",
                "total_amount": Decimal("1000000.00"),
            }

        def list_items(self, order_id):
            return []

    monkeypatch.setattr(
        "ui.pages.checkout_page.SessionLocal",
        FakeSession,
    )
    monkeypatch.setattr(
        "ui.pages.checkout_page.OrderRepository",
        FakeOrders,
    )

    page = FakePage(FakeStore())

    result = build_order_receipt_page(
        page,
        order_id=42,
        customer_id=7,
        authorize=lambda: None,
    )

    values = [
        control.value
        for control in result.controls
        if hasattr(control, "value")
    ]

    assert any("DH00000042" in value for value in values)
    assert any("PENDING" in value for value in values)


def test_navigation_failure_after_success_prevents_duplicate():
    page, cart, service, panel = build_panel()
    page.fail_push_route = True

    asyncio.run(panel.place_order())

    # Backend already confirmed the order.
    assert len(service.calls) == 1
    assert panel.confirmed_order_id == 42

    # No additional order can be submitted from this screen.
    assert panel.submit_button.disabled is True
    assert cart.items() == []

    assert "DH00000042" in panel.error.value

    # Repeated click must not call the backend again.
    asyncio.run(panel.place_order())

    assert len(service.calls) == 1