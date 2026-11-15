
"""Task 53: Customer order Flet UI unit tests."""

from datetime import datetime
from decimal import Decimal

from models.app_error import AppError
from ui.pages.customer_orders_page import (
    CustomerOrdersPanel,
    build_customer_order_detail_page,
    format_order_time,
)

NOW = datetime(2026, 11, 15, 5, 0)


class FakePage:
    def __init__(self):
        self.routes = []
        self.updates = 0

    def navigate(self, route):
        self.routes.append(route)

    def update(self):
        self.updates += 1


class FakeService:
    def __init__(self):
        self.calls = []
        self.error = None

    def list_orders(
        self,
        *,
        session_store,
        page,
        page_size,
    ):
        self.calls.append(
            ("list", page, page_size)
        )

        if self.error is not None:
            raise self.error

        return {
            "items": [
                {
                    "id": page,
                    "code": f"DH{page:08d}",
                    "status": "PENDING",
                    "total_amount": Decimal("12000000.00"),
                    "created_at": NOW,
                }
            ],
            "page": page,
            "page_size": page_size,
            "total": 20,
            "total_pages": 2,
        }

    def get_order(self, *, session_store, order_id):
        self.calls.append(("detail", order_id))

        if self.error is not None:
            raise self.error

        return {
            "id": order_id,
            "code": f"DH{order_id:08d}",
            "status": "PENDING",
            "total_amount": Decimal("12000000.00"),
            "created_at": NOW,
            "receiver_name": "Nguyen Van A",
            "receiver_phone": "0912345678",
            "receiver_address": "Da Nang",
            "note": "",
            "items": [
                {
                    "product_id": 5,
                    "product_name": "Demo Phone",
                    "brand_name": "Demo Brand",
                    "quantity": 1,
                    "unit_price": Decimal("12000000.00"),
                }
            ],
        }


def test_utc_timestamp_displays_vietnam_time():
    assert format_order_time(NOW) == "15/11/2026 12:00"


def test_invalid_timestamp_has_safe_fallback():
    assert format_order_time(None) == "Không xác định"


def test_customer_order_list_loads_first_page():
    page = FakePage()
    service = FakeService()

    panel = CustomerOrdersPanel(
        page,
        session_store=object(),
        service=service,
    )

    panel.load()

    assert ("list", 1, 10) in service.calls
    assert len(panel.rows.controls) == 1
    assert panel.previous_button.disabled is True
    assert panel.next_button.disabled is False


def test_customer_order_list_next_and_previous():
    page = FakePage()
    service = FakeService()

    panel = CustomerOrdersPanel(
        page,
        session_store=object(),
        service=service,
    )
    panel.load()

    panel.next_page()

    assert panel.page_number == 2
    assert panel.next_button.disabled is True
    assert panel.previous_button.disabled is False

    panel.previous_page()

    assert panel.page_number == 1
    assert page.updates == 2


def test_order_list_business_error_is_safe():
    page = FakePage()
    service = FakeService()
    service.error = AppError(
        "UNAUTHORIZED",
        "Vui lòng đăng nhập.",
    )

    panel = CustomerOrdersPanel(
        page,
        session_store=object(),
        service=service,
    )
    panel.load()

    assert panel.error.value == "Vui lòng đăng nhập."
    assert panel.next_button.disabled is True


def test_order_detail_displays_code_and_total():
    page = FakePage()
    service = FakeService()

    content = build_customer_order_detail_page(
        page,
        order_id=42,
        session_store=object(),
        service=service,
    )

    visible_texts = [
        control.value
        for control in content.controls
        if hasattr(control, "value")
    ]

    assert any("DH00000042" in text for text in visible_texts)
    assert any("12.000.000" in text for text in visible_texts)
    assert ("detail", 42) in service.calls


def test_other_customer_detail_displays_404():
    page = FakePage()
    service = FakeService()
    service.error = AppError(
        "NOT_FOUND",
        "Không tìm thấy đơn hàng.",
    )

    content = build_customer_order_detail_page(
        page,
        order_id=42,
        session_store=object(),
        service=service,
    )

    assert "404" in content.controls[0].value


def test_unauthorized_order_detail_displays_safe_error():
    page = FakePage()
    service = FakeService()
    service.error = AppError(
        "FORBIDDEN",
        "Không có quyền truy cập.",
    )

    content = build_customer_order_detail_page(
        page,
        order_id=42,
        session_store=object(),
        service=service,
    )

    assert "Không có quyền" in content.controls[0].value
