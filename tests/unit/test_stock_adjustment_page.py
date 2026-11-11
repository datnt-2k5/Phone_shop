
"""Task 43: Flet count form tests, without database mutations."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from ui.pages.stock_adjustment_page import StockAdjustmentPanel


class FakePage:
    def __init__(self):
        self.session = SimpleNamespace(store=object())
        self.updates = 0
        self.dialogs = []
        self.pops = 0
        self.routes = []

    def update(self):
        self.updates += 1

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.pops += 1

    def navigate(self, route):
        self.routes.append(route)


class FakeProducts:
    def __init__(self):
        self.calls = []
        self.rows = [
            {
                "id": 3,
                "sku": "A-03",
                "name": "Máy A",
                "stock": 10,
                "cost_price": Decimal("100.00"),
                "status": "ACTIVE",
            },
            {
                "id": 4,
                "sku": "B-04",
                "name": "Máy B",
                "stock": 5,
                "cost_price": Decimal("200.00"),
                "status": "DISCONTINUED",
            },
        ]

    def search_admin(self, **kwargs):
        self.calls.append(kwargs)
        offset = kwargs["offset"]
        limit = kwargs["limit"]
        return {
            "items": self.rows[offset:offset + limit],
            "total": len(self.rows),
        }


class FakeService:
    def __init__(self):
        self.calls = []
        self.list_calls = []
        self.detail_calls = []
        self.error = None
        self.created = True

    def create_adjustment(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        if not self.created:
            return {
                "created": False,
                "id": None,
                "code": None,
                "changed_items": 0,
            }
        return {
            "created": True,
            "id": 11,
            "code": "ADJ00000011",
            "changed_items": len(kwargs["items"]),
        }

    def list_adjustments(self, **kwargs):
        self.list_calls.append(kwargs)
        return [
            {
                "id": 11,
                "code": "ADJ00000011",
                "reason": "Kiểm kê",
                "created_by_name": "Admin",
                "created_at": "2026-11-11",
                "changed_items": 1,
            }
        ]

    def get_adjustment(self, **kwargs):
        self.detail_calls.append(kwargs)
        return {
            "adjustment": {
                "id": 11,
                "code": "ADJ00000011",
                "reason": "Kiểm kê",
            },
            "items": [
                {
                    "sku": "A-03",
                    "product_name": "Máy A",
                    "old_quantity": 10,
                    "actual_quantity": 8,
                    "quantity_change": -2,
                    "stock_after": 8,
                }
            ],
        }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(
        "ui.pages.stock_adjustment_page.notify",
        lambda *args, **kwargs: None,
    )
    page = FakePage()
    products = FakeProducts()
    service = FakeService()

    panel = StockAdjustmentPanel(
        page,
        products=products,
        service=service,
    )
    panel.load(redraw=False)

    return SimpleNamespace(
        page=page,
        products=products,
        service=service,
        panel=panel,
    )


def add(env, *, product="3", actual="8"):
    env.panel.product.value = product
    env.panel.actual.value = actual
    env.panel.add_line()


def test_initial_read_is_authorized_and_never_writes(env):
    assert env.products.calls[0]["status"] == "ALL"
    assert (
        env.service.list_calls[0]["session_store"]
        is env.page.session.store
    )
    assert env.service.calls == []
    assert env.page.updates == 0


def test_discontinued_product_can_be_counted(env):
    add(env, product="4", actual="7")
    assert env.panel.lines[0]["actual_quantity"] == 7
    assert env.panel.lines[0]["stock_snapshot"] == 5


def test_product_search_resets_page_and_uses_keyword(env):
    env.panel.product_offset = 20
    env.panel.keyword.value = "A-03"
    env.panel.search_changed()

    assert env.panel.product_offset == 0
    assert env.products.calls[-1]["keyword"] == "A-03"


def test_add_line_is_only_draft(env):
    add(env)
    assert env.panel.lines[0]["actual_quantity"] == 8
    assert env.service.calls == []
    assert (
        env.panel.lines[0]["cost_snapshot"]
        == Decimal("100.00")
    )


def test_zero_quantity_is_accepted_for_counting(env):
    add(env, actual="0")
    assert env.panel.lines[0]["actual_quantity"] == 0


@pytest.mark.parametrize(
    "raw",
    ["-1", "1.2", "abc", "", "2147483648"],
)
def test_invalid_actual_quantity_is_rejected(env, raw):
    add(env, actual=raw)
    assert env.panel.lines == []
    assert env.service.calls == []


def test_duplicate_line_is_rejected(env):
    add(env)
    add(env)

    assert len(env.panel.lines) == 1
    assert "đã có" in env.panel.error.value


def test_remove_line(env):
    add(env)
    env.panel.remove_line(3)
    assert env.panel.lines == []


def test_confirm_needs_lines_and_reason(env):
    env.panel.ask_confirm()
    assert env.page.dialogs == []

    add(env)
    env.panel.ask_confirm()
    assert env.page.dialogs == []


def test_open_dialog_never_writes(env):
    add(env)
    env.panel.reason.value = "Kiểm kê"
    env.panel.ask_confirm()
    env.panel.ask_confirm()

    assert len(env.page.dialogs) == 1
    assert env.service.calls == []


def test_cancel_keeps_draft(env):
    add(env)
    env.panel.reason.value = "Kiểm kê"
    env.panel.ask_confirm()

    dialog = env.page.dialogs[-1]
    dialog.actions[0].on_click(None)
    dialog.on_dismiss(None)

    assert env.service.calls == []
    assert len(env.panel.lines) == 1


def test_confirm_submits_only_after_dismiss_and_only_once(env):
    add(env)
    env.panel.reason.value = "  Kiểm kê  "
    env.panel.ask_confirm()

    dialog = env.page.dialogs[-1]
    dialog.actions[1].on_click(None)
    assert env.service.calls == []

    dialog.on_dismiss(None)
    dialog.on_dismiss(None)

    assert len(env.service.calls) == 1
    assert env.service.calls[0]["items"] == [
        {
            "product_id": 3,
            "actual_quantity": 8,
        }
    ]
    assert env.service.calls[0]["reason"] == "Kiểm kê"
    assert env.panel.lines == []
    assert "ADJ00000011" in env.panel.success.value


def test_no_difference_returns_no_document_and_clears_draft(env):
    env.service.created = False
    add(env, actual="10")
    env.panel.reason.value = "Kiểm kê"
    env.panel.save()

    assert len(env.service.calls) == 1
    assert env.panel.lines == []
    assert "không tạo phiếu" in env.panel.success.value


def test_business_error_preserves_draft(env):
    env.service.error = AppError(
        "VALIDATION_ERROR",
        "Không hợp lệ",
    )
    add(env)
    env.panel.reason.value = "Kiểm kê"
    env.panel.save()

    assert len(env.panel.lines) == 1
    assert "Không hợp lệ" in env.panel.error.value


def test_unknown_error_warns_to_check_history_before_retry(env):
    env.service.error = RuntimeError("connection failed")
    add(env)
    env.panel.reason.value = "Kiểm kê"
    env.panel.save()

    assert len(env.panel.lines) == 1
    assert "lịch sử" in env.panel.error.value


def test_busy_blocks_duplicate_submission(env):
    add(env)
    env.panel.busy = True
    env.panel.save()
    assert env.service.calls == []


def test_details_use_authenticated_service(env):
    env.panel.show_detail(11)
    assert (
        env.service.detail_calls[-1]["adjustment_id"] == 11
    )
    assert env.panel.detail_holder.visible
    assert env.service.calls == []


def test_unauthorized_hides_history_and_navigates(env):
    env.panel.handle_error(
        AppError("UNAUTHORIZED", "Hết phiên")
    )
    assert env.panel.history_holder.controls == []
    assert env.page.routes == ["/login"]


def test_navigation_routes_exist_for_admin_only():
    from ui.navigation import route_available

    assert route_available("ADMIN", "/admin/adjustments")
    assert route_available(
        "SUPER_ADMIN",
        "/admin/adjustments",
    )
    assert not route_available(
        "CUSTOMER",
        "/admin/adjustments",
    )
    assert not route_available(
        "GUEST",
        "/admin/adjustments",
    )

    source = Path("main.py").read_text(encoding="utf-8")
    assert 'if route == "/admin/adjustments":' in source
    assert "return build_stock_adjustment_page(page)" in source
