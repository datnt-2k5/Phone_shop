
"""Task 35: UI behaviors with fake CatalogService (no DB writes)."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from ui.pages.catalog_page import PAGE_SIZE, CatalogPanel


class FakePage:
    def __init__(self):
        self.session = SimpleNamespace(store=object())
        self.updates = 0
        self.routes = []
        self.dialogs = []
        self.pops = 0

    def update(self):
        self.updates += 1

    def navigate(self, route):
        self.routes.append(route)

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.pops += 1


class FakeCatalog:
    def __init__(self):
        self.brands = [
            {
                "id": 1,
                "name": "Apple",
                "created_at": datetime(2026, 1, 1),
            }
        ]

        self.suppliers = [
            {
                "id": 10,
                "name": "NCC A",
                "phone": "0912345678",
                "email": "one@example.test",
                "address": "Đà Nẵng",
                "is_active": True,
            },
            {
                "id": 11,
                "name": "NCC B",
                "phone": None,
                "email": None,
                "address": None,
                "is_active": False,
            },
        ]

        self.brand_reads = []
        self.supplier_reads = []
        self.brand_saves = []
        self.supplier_saves = []
        self.stops = []

        self.brand_error = None
        self.supplier_error = None
        self.list_error = None
        self.stop_error = None

    def list_brands(self, *, limit, offset):
        self.brand_reads.append(
            (limit, offset)
        )

        rows = sorted(
            self.brands,
            key=lambda row: row["name"],
        )

        return rows[offset:offset + limit]

    def list_suppliers(
        self,
        *,
        session_store,
        is_active,
        limit,
        offset,
    ):
        self.supplier_reads.append(
            (
                session_store,
                is_active,
                limit,
                offset,
            )
        )

        if self.list_error:
            raise AppError(
                self.list_error,
                "Access denied",
            )

        rows = sorted(
            self.suppliers,
            key=lambda row: row["name"],
        )

        if is_active is not None:
            rows = [
                row
                for row in rows
                if bool(row["is_active"]) == is_active
            ]

        return rows[offset:offset + limit]

    def save_brand(self, **kwargs):
        self.brand_saves.append(kwargs)

        if self.brand_error:
            raise AppError(
                self.brand_error,
                "Tên hãng đã tồn tại.",
            )

        if kwargs["brand_id"] is None:
            row = {
                "id": 50,
                "name": kwargs["name"],
                "created_at": datetime(2026, 1, 2),
            }
            self.brands.append(row)
        else:
            row = next(
                row
                for row in self.brands
                if row["id"] == kwargs["brand_id"]
            )
            row["name"] = kwargs["name"]

        return row

    def save_supplier(self, **kwargs):
        self.supplier_saves.append(kwargs)

        if self.supplier_error:
            raise AppError(
                self.supplier_error,
                "Thông tin không hợp lệ.",
            )

        values = {
            key: value
            for key, value in kwargs.items()
            if key not in {
                "session_store",
                "supplier_id",
            }
        }

        if kwargs["supplier_id"] is None:
            row = {
                "id": 51,
                **values,
                "is_active": True,
            }
            self.suppliers.append(row)
        else:
            row = next(
                row
                for row in self.suppliers
                if row["id"] == kwargs["supplier_id"]
            )
            row.update(values)

        return row

    def discontinue_supplier(self, **kwargs):
        self.stops.append(kwargs)

        if self.stop_error:
            raise AppError(
                self.stop_error,
                "Denied",
            )

        row = next(
            row
            for row in self.suppliers
            if row["id"] == kwargs["supplier_id"]
        )

        row["is_active"] = False
        return row


@pytest.fixture
def env(monkeypatch):
    # Không mở thông báo Flet thật trong Unit Test.
    monkeypatch.setattr(
        "ui.pages.catalog_page.notify",
        lambda *args, **kwargs: None,
    )

    page = FakePage()
    service = FakeCatalog()

    panel = CatalogPanel(
        page,
        service=service,
    )
    panel.load(redraw=False)

    return panel, page, service


def test_initial_load_shows_brands_without_writes(env):
    panel, page, service = env

    assert panel.section == "brands"
    assert service.brand_reads == [
        (PAGE_SIZE + 1, 0)
    ]
    assert not service.brand_saves
    assert not service.supplier_saves
    assert page.updates == 0


def test_switch_to_supplier_passes_real_session(env):
    panel, page, service = env

    panel.show_suppliers()

    assert service.supplier_reads[-1] == (
        page.session.store,
        None,
        PAGE_SIZE + 1,
        0,
    )
    assert panel.supplier_filter.visible
    assert panel.supplier_add_button.visible
    assert not panel.brand_add_button.visible


@pytest.mark.parametrize(
    "value,expected",
    [
        ("ALL", None),
        ("ACTIVE", True),
        ("INACTIVE", False),
    ],
)
def test_supplier_filter_produces_correct_boolean(
    env,
    value,
    expected,
):
    panel, _, service = env
    panel.show_suppliers()

    panel.supplier_filter.value = value
    panel.offset = 10
    panel.apply_filter()

    assert panel.offset == 0
    assert service.supplier_reads[-1][1] is expected


def test_switch_back_to_brands_resets_offset_and_forms(env):
    panel, _, _ = env

    panel.show_suppliers()
    panel.open_supplier_create()
    panel.offset = 20
    panel.show_brands()

    assert panel.offset == 0
    assert not panel.supplier_form.visible
    assert not panel.supplier_filter.visible
    assert panel.brand_add_button.visible


def test_brand_create_form_has_empty_name(env):
    panel, _, _ = env
    panel.open_brand_create()

    assert panel.brand_id is None
    assert panel.brand_name.value == ""
    assert panel.brand_form.visible


def test_brand_edit_prefills_id_and_name(env):
    panel, _, service = env

    panel.open_brand_edit(
        service.brands[0]
    )

    assert panel.brand_id == 1
    assert panel.brand_name.value == "Apple"
    assert panel.brand_form.visible


def test_brand_save_passes_only_authorized_fields(env):
    panel, page, service = env

    panel.open_brand_create()
    panel.brand_name.value = "Samsung"
    panel.save_brand()

    assert service.brand_saves == [
        {
            "session_store": page.session.store,
            "brand_id": None,
            "name": "Samsung",
        }
    ]
    assert not panel.brand_form.visible
    assert panel.offset == 0


def test_brand_duplicate_keeps_form_open(env):
    panel, _, service = env
    service.brand_error = "BRAND_EXISTS"

    panel.open_brand_create()
    panel.brand_name.value = "Apple"
    panel.save_brand()

    assert panel.brand_form.visible
    assert "Tên hãng" in panel.brand_error.value


def test_supplier_create_form_is_blank(env):
    panel, _, _ = env

    panel.show_suppliers()
    panel.open_supplier_create()

    assert panel.supplier_id is None
    assert panel.supplier_name.value == ""
    assert panel.supplier_phone.value == ""
    assert panel.supplier_form.visible


def test_supplier_edit_populates_contact_values(env):
    panel, _, service = env

    panel.show_suppliers()
    panel.open_supplier_edit(
        service.suppliers[0]
    )

    assert panel.supplier_id == 10
    assert panel.supplier_email.value == "one@example.test"
    assert panel.supplier_form.visible


def test_supplier_save_does_not_send_is_active(env):
    panel, page, service = env

    panel.show_suppliers()
    panel.open_supplier_create()

    panel.supplier_name.value = "NCC New"
    panel.supplier_phone.value = "0912345678"
    panel.supplier_email.value = "new@example.com"
    panel.supplier_address.value = "Huế"

    panel.save_supplier()

    call = service.supplier_saves[-1]

    assert call["session_store"] is page.session.store
    assert call["name"] == "NCC New"
    assert call["supplier_id"] is None
    assert "is_active" not in call
    assert not panel.supplier_form.visible


def test_save_inactive_supplier_does_not_reactivate(env):
    panel, _, service = env

    panel.show_suppliers()
    panel.open_supplier_edit(
        service.suppliers[1]
    )
    panel.supplier_name.value = "NCC B Edited"
    panel.save_supplier()

    assert service.suppliers[1]["is_active"] is False
    assert "is_active" not in service.supplier_saves[-1]


def test_supplier_detail_shows_data(env):
    panel, _, service = env

    panel.show_suppliers()
    panel.show_supplier_detail(
        service.suppliers[0]
    )

    assert panel.detail_holder.visible

    panel.close_detail()
    assert not panel.detail_holder.visible


def test_confirmation_does_not_stop_supplier_immediately(env):
    panel, page, service = env

    panel.ask_discontinue(
        service.suppliers[0]
    )

    assert len(page.dialogs) == 1
    assert service.stops == []


def test_cancel_confirmation_does_not_stop_supplier(env):
    panel, page, service = env

    panel.ask_discontinue(
        service.suppliers[0]
    )

    dialog = page.dialogs[-1]
    dialog.actions[0].on_click(None)
    dialog.on_dismiss(None)

    assert service.stops == []
    assert page.pops == 1


def test_confirm_stops_only_after_dialog_dismissed(env):
    panel, page, service = env

    panel.show_suppliers()
    panel.ask_discontinue(
        service.suppliers[0]
    )

    dialog = page.dialogs[-1]

    dialog.actions[1].on_click(None)

    # Chưa được ghi khi dialog chưa đóng xong.
    assert service.stops == []

    dialog.on_dismiss(None)

    assert len(service.stops) == 1
    assert service.stops[0]["supplier_id"] == 10
    assert service.suppliers[0]["is_active"] is False

    # Không thực thi hai lần nếu nhận sự kiện lặp.
    dialog.on_dismiss(None)
    assert len(service.stops) == 1


def test_inactive_supplier_has_no_discontinue_dialog(env):
    panel, page, service = env

    panel.ask_discontinue(
        service.suppliers[1]
    )

    assert page.dialogs == []


def test_customer_forbidden_clears_supplier_rows(env):
    panel, page, service = env

    panel.show_suppliers()
    service.list_error = "FORBIDDEN"
    panel.reload()

    assert panel.table_holder.controls == []
    assert "403" in panel.message.value
    assert page.routes == []


@pytest.mark.parametrize(
    "error",
    ["UNAUTHORIZED", "ACCOUNT_LOCKED"],
)
def test_auth_lost_navigates_login_and_hides_data(
    env,
    error,
):
    panel, page, _ = env

    panel._handle_error(
        AppError(error, "Mất phiên")
    )

    assert page.routes == ["/login"]
    assert panel.table_holder.controls == []


def test_pagination_uses_extra_row_sentinel(env):
    panel, _, service = env

    service.brands = [
        {
            "id": i,
            "name": f"Brand {i:03d}",
            "created_at": None,
        }
        for i in range(PAGE_SIZE + 1)
    ]

    panel.load()

    assert panel.has_next

    panel.next_page()
    assert panel.offset == PAGE_SIZE
    assert not panel.has_next

    panel.previous_page()
    assert panel.offset == 0


def test_deactivate_last_row_moves_back_one_page(env):
    panel, _, service = env

    service.suppliers = [
        {
            "id": i,
            "name": f"Supplier {i:03d}",
            "is_active": True,
            "phone": None,
            "email": None,
            "address": None,
        }
        for i in range(PAGE_SIZE + 1)
    ]

    panel.show_suppliers()
    panel.supplier_filter.value = "ACTIVE"
    panel.load()
    panel.next_page()

    assert panel.offset == PAGE_SIZE

    service.suppliers[-1]["is_active"] = False

    panel.load()
    assert panel.offset == 0


def test_close_form_does_not_call_backend(env):
    panel, _, service = env

    panel.open_brand_create()
    panel.close_forms()

    assert not panel.brand_form.visible
    assert service.brand_saves == []


def test_duplicate_save_guard_prevents_second_write(env):
    panel, _, service = env

    panel.open_brand_create()
    panel.busy = True
    panel.save_brand()

    assert service.brand_saves == []
