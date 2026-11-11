
"""Task 40: ImportPanel UI tests without MariaDB writes."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from ui.pages.import_page import ImportPanel


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


class FakeCatalog:
    def __init__(self):
        self.calls = []
        self.rows = [{"id": 5, "name": "NCC Test"}]

    def list_suppliers(self, **kwargs):
        self.calls.append(kwargs)
        start = kwargs["offset"]
        end = start + kwargs["limit"]
        return self.rows[start:end]


class FakeProducts:
    def __init__(self):
        self.calls = []
        self.rows = [
            {
                "id": 10,
                "sku": "IP-TEST",
                "name": "Điện thoại Test",
            },
            {
                "id": 11,
                "sku": "SS-TEST",
                "name": "Điện thoại khác",
            },
        ]

    def search_admin(self, **kwargs):
        self.calls.append(kwargs)
        start = kwargs["offset"]
        end = start + kwargs["limit"]
        return {
            "items": self.rows[start:end],
            "total": len(self.rows),
        }


class FakeImporter:
    def __init__(self):
        self.calls = []
        self.error = None

    def create_import(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {
            "id": 42,
            "code": "PN00000042",
            "total_amount": Decimal("201.00"),
        }


class FakeQueries:
    def __init__(self):
        self.history_calls = []
        self.detail_calls = []

    def list_receipts(self, **kwargs):
        self.history_calls.append(kwargs)
        return [{
            "id": 42,
            "code": "PN00000042",
            "supplier_name": "NCC Test",
            "total_amount": Decimal("201.00"),
            "created_by_name": "Admin Test",
        }]

    def get_receipt(self, **kwargs):
        self.detail_calls.append(kwargs)
        return {
            "receipt": {
                "id": 42,
                "code": "PN00000042",
                "supplier_name": "NCC Test",
                "total_amount": Decimal("201.00"),
                "note": None,
            },
            "items": [{
                "product_id": 10,
                "sku": "IP-TEST",
                "product_name": "Điện thoại Test",
                "quantity": 2,
                "import_price": Decimal("100.50"),
                "line_total": Decimal("201.00"),
            }],
        }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(
        "ui.pages.import_page.notify",
        lambda *args, **kwargs: None,
    )
    page = FakePage()
    catalog = FakeCatalog()
    products = FakeProducts()
    importer = FakeImporter()
    queries = FakeQueries()

    panel = ImportPanel(
        page,
        importer=importer,
        catalog=catalog,
        products=products,
        queries=queries,
    )
    panel.load(redraw=False)
    return SimpleNamespace(
        page=page,
        panel=panel,
        catalog=catalog,
        products=products,
        importer=importer,
        queries=queries,
    )


def choose_line(env, *, product="10", quantity="2", price="100.50"):
    panel = env.panel
    panel.product.value = product
    panel.quantity.value = quantity
    panel.price.value = price
    panel.add_item()


def test_initial_load_does_not_write_database(env):
    assert env.importer.calls == []
    assert env.page.updates == 0
    assert env.catalog.calls[0]["is_active"] is True
    assert env.products.calls[0]["status"] == "ACTIVE"


def test_supplier_options_are_loaded(env):
    assert len(env.panel.supplier.options) == 1
    assert env.panel.supplier.options[0].key == "5"


def test_product_search_uses_admin_service(env):
    env.panel.keyword.value = "IP-TEST"
    env.panel.apply_product_search()
    assert env.products.calls[-1]["keyword"] == "IP-TEST"
    assert env.products.calls[-1]["status"] == "ACTIVE"


def test_add_line_updates_draft_without_importing(env):
    choose_line(env)
    assert len(env.panel.lines) == 1
    assert env.panel.lines[0]["product_id"] == 10
    assert env.importer.calls == []
    assert "201" in env.panel.total_text.value


def test_duplicate_product_is_rejected(env):
    choose_line(env)
    choose_line(env)
    assert len(env.panel.lines) == 1
    assert "đã có" in env.panel.message.value


@pytest.mark.parametrize(
    "quantity,price",
    [
        ("0", "100.00"),
        ("-1", "100.00"),
        ("1.5", "100.00"),
        ("abc", "100.00"),
        ("2", "0"),
        ("2", "-10"),
        ("2", "1.234"),
        ("2", "abc"),
    ],
)
def test_invalid_line_is_not_added(env, quantity, price):
    choose_line(env, quantity=quantity, price=price)
    assert env.panel.lines == []
    assert env.importer.calls == []


def test_remove_line(env):
    choose_line(env)
    env.panel.remove_item(10)
    assert env.panel.lines == []
    assert env.panel.total_text.value == "Tổng tiền: 0 ₫"


def test_confirmation_requires_supplier_and_items(env):
    env.panel.ask_confirm()
    assert env.page.dialogs == []
    choose_line(env)
    env.panel.ask_confirm()
    assert env.page.dialogs == []


def test_open_confirmation_does_not_save_immediately(env):
    env.panel.supplier.value = "5"
    choose_line(env)
    env.panel.ask_confirm()
    assert len(env.page.dialogs) == 1
    assert env.importer.calls == []


def test_cancel_confirmation_keeps_draft(env):
    env.panel.supplier.value = "5"
    choose_line(env)
    env.panel.ask_confirm()
    dialog = env.page.dialogs[-1]
    dialog.actions[0].on_click(None)
    dialog.on_dismiss(None)

    assert env.importer.calls == []
    assert len(env.panel.lines) == 1
    assert env.page.pops == 1


def test_confirm_saves_only_after_dialog_dismiss(env):
    env.panel.supplier.value = "5"
    choose_line(env)
    env.panel.ask_confirm()
    dialog = env.page.dialogs[-1]

    dialog.actions[1].on_click(None)
    assert env.importer.calls == []

    dialog.on_dismiss(None)
    assert len(env.importer.calls) == 1
    assert env.importer.calls[0]["supplier_id"] == 5
    assert env.importer.calls[0]["items"] == [{
        "product_id": 10,
        "quantity": 2,
        "import_price": "100.50",
    }]
    assert env.panel.lines == []
    assert "PN00000042" in env.panel.success.value


def test_dismiss_event_twice_does_not_create_twice(env):
    env.panel.supplier.value = "5"
    choose_line(env)
    env.panel.ask_confirm()
    dialog = env.page.dialogs[-1]
    dialog.actions[1].on_click(None)
    dialog.on_dismiss(None)
    dialog.on_dismiss(None)
    assert len(env.importer.calls) == 1


def test_import_error_preserves_unsaved_draft(env):
    env.panel.supplier.value = "5"
    choose_line(env)
    env.importer.error = AppError(
        "SUPPLIER_INACTIVE",
        "Nhà cung cấp ngừng hợp tác.",
    )
    env.panel.save_import()
    assert len(env.panel.lines) == 1
    assert "ngừng hợp tác" in env.panel.message.value


def test_busy_flag_blocks_duplicate_save(env):
    env.panel.busy = True
    env.panel.save_import()
    assert env.importer.calls == []


def test_history_reads_without_write(env):
    env.panel.load_history()
    assert env.queries.history_calls
    assert env.importer.calls == []


def test_receipt_detail_is_read_only(env):
    env.panel.show_receipt(42)
    assert env.panel.detail_holder.visible
    assert env.queries.detail_calls[-1]["receipt_id"] == 42
    assert env.importer.calls == []


def test_unauthorized_clears_sensitive_history(env):
    env.panel.handle_error(
        AppError("UNAUTHORIZED", "Phiên không hợp lệ.")
    )
    assert env.panel.history_holder.controls == []
    assert env.page.routes == ["/login"]
