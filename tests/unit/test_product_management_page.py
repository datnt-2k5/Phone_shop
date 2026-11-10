
"""Task 30: Unit Tests for product management panel."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from ui.pages.product_management_page import ProductManagementPanel


class FakePage:
    def __init__(self):
        self.session = SimpleNamespace(store=object())
        self.updated = 0
        self.navigated = []
        self.dialogs = []

    def update(self):
        self.updated += 1

    def navigate(self, route):
        self.navigated.append(route)

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        pass


class FakeManagement:
    def __init__(self):
        self.items = []
        self.search_calls = []
        self.status_calls = []
        self.denied = False

    def search_admin(self, **kwargs):
        self.search_calls.append(kwargs)

        if self.denied:
            raise AppError("FORBIDDEN", "Không có quyền.")

        offset = kwargs["offset"]
        limit = kwargs["limit"]
        return {
            "items": self.items[offset:offset + limit],
            "total": len(self.items),
            "limit": limit,
            "offset": offset,
        }

    def set_status(self, **kwargs):
        self.status_calls.append(kwargs)
        return {"id": kwargs["product_id"], "status": kwargs["status"]}


class FakeCreator:
    def __init__(self):
        self.created = []
        self.brands = [{"id": 3, "name": "Demo Brand"}]

    def list_brands(self, **kwargs):
        return self.brands

    def create(self, **kwargs):
        self.created.append(kwargs)
        return {"id": 11, "sku": kwargs["sku"]}


class FakeEditor:
    def __init__(self):
        self.updated = []

    def update_details(self, **kwargs):
        self.updated.append(kwargs)
        return {"id": kwargs["product_id"], "sku": "SKU-OLD"}


def sample_product(product_id=11):
    return {
        "id": product_id,
        "sku": f"SKU-{product_id}",
        "name": "Phone A",
        "brand_id": 3,
        "brand_name": "Demo Brand",
        "storage": "128GB",
        "color": "Black",
        "sell_price": Decimal("12000000.00"),
        "cost_price": Decimal("9000000.00"),
        "stock": 3,
        "min_stock": 5,
        "is_low_stock": True,
        "status": "ACTIVE",
        "description": "Original",
        "image_url": None,
    }


@pytest.fixture
def env():
    page = FakePage()
    management = FakeManagement()
    creator = FakeCreator()
    editor = FakeEditor()
    panel = ProductManagementPanel(
        page,
        management_service=management,
        create_service=creator,
        edit_service=editor,
    )
    panel.load()
    return panel, page, management, creator, editor


def test_panel_loads_brand_choices_and_searches(env):
    panel, _, management, creator, _ = env

    assert panel.brands == creator.brands
    assert len(panel.brand.options) == 1
    assert management.search_calls[0]["limit"] == 10


def test_create_form_opens_with_editable_identity(env):
    panel, _, _, _, _ = env
    panel.open_create()

    assert panel.form.visible is True
    assert panel.editing_id is None
    assert panel.sku.disabled is False
    assert panel.brand.disabled is False


def test_edit_form_locks_identity_fields(env):
    panel, _, _, _, _ = env
    panel.open_edit(sample_product())

    assert panel.editing_id == 11
    assert panel.name.value == "Phone A"
    assert panel.sku.disabled is True
    assert panel.brand.disabled is True
    assert panel.storage.disabled is True
    assert panel.color.disabled is True


def test_create_form_uses_create_service(env, monkeypatch):
    panel, _, _, creator, _ = env
    panel.open_create()
    panel.sku.value = "SKU-NEW"
    panel.name.value = "Phone New"
    panel.brand.value = "3"
    panel.storage.value = "256GB"
    panel.color.value = "Black"
    panel.price.value = "15000000"
    panel.minimum.value = "2"

    # Notification Flet is not mounted in this unit test.
    monkeypatch.setattr(
        "ui.pages.product_management_page.notify",
        lambda *args, **kwargs: None,
    )

    panel.save_form()

    assert len(creator.created) == 1
    saved = creator.created[0]
    assert saved["brand_id"] == 3
    assert saved["min_stock"] == 2
    assert saved["sku"] == "SKU-NEW"
    assert "stock" not in saved
    assert "cost_price" not in saved
    assert panel.form.visible is False


def test_edit_form_uses_edit_service(env, monkeypatch):
    panel, _, _, _, editor = env
    panel.open_edit(sample_product())
    panel.name.value = "Phone Premium"
    panel.price.value = "13000000"
    panel.minimum.value = "4"

    monkeypatch.setattr(
        "ui.pages.product_management_page.notify",
        lambda *args, **kwargs: None,
    )

    panel.save_form()

    assert len(editor.updated) == 1
    values = editor.updated[0]
    assert values["product_id"] == 11
    assert values["name"] == "Phone Premium"
    assert "sku" not in values
    assert "stock" not in values
    assert "cost_price" not in values


@pytest.mark.parametrize("invalid", ["", "abc", "-2", "1.5"])
def test_invalid_min_stock_never_calls_backend(env, invalid):
    panel, _, _, creator, editor = env
    panel.open_create()
    panel.minimum.value = invalid

    panel.save_form()

    assert creator.created == []
    assert editor.updated == []
    assert panel.form.visible is True


def test_filter_resets_pagination(env):
    panel, _, management, _, _ = env
    panel.offset = 20
    panel.keyword.value = "Phone"

    panel.apply_filters()

    assert panel.offset == 0
    assert management.search_calls[-1]["keyword"] == "Phone"


def test_customer_denial_does_not_display_admin_data(env):
    panel, _, management, _, _ = env
    management.denied = True

    panel.search()

    assert "Không có quyền" in panel.message.value


def test_account_locked_navigates_to_login(env):
    panel, page, _, _, _ = env
    panel.handle_error(
        AppError("ACCOUNT_LOCKED", "Tài khoản bị khóa.")
    )
    assert page.navigated == ["/login"]


def test_status_confirmation_does_not_write_immediately(env):
    panel, page, management, _, _ = env
    panel.ask_change_status(sample_product())

    assert len(page.dialogs) == 1
    assert management.status_calls == []


def test_pagination_changes_offset(env):
    panel, _, management, _, _ = env
    management.items = [
        sample_product(product_id=i)
        for i in range(1, 23)
    ]
    panel.search()

    panel.next_page()
    assert panel.offset == 10

    panel.previous_page()
    assert panel.offset == 0


def test_detail_can_open_and_close(env):
    panel, _, _, _, _ = env
    panel.show_detail(sample_product())
    assert panel.details.visible is True

    panel.close_detail()
    assert panel.details.visible is False
