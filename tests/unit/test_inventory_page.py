
"""Task 40: inventory page UI tests with authorized fake queries."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from ui.pages.inventory_page import PAGE_SIZE, InventoryPanel


class FakePage:
    def __init__(self):
        self.session = SimpleNamespace(store=object())
        self.updates = 0
        self.routes = []

    def update(self):
        self.updates += 1

    def navigate(self, route):
        self.routes.append(route)


class FakeQueries:
    def __init__(self):
        self.inventory_calls = []
        self.movement_calls = []
        self.error = None
        self.products = [
            {
                "id": 10,
                "sku": "IP-LOW",
                "name": "iPhone Test",
                "brand_name": "Apple",
                "stock": 3,
                "min_stock": 5,
                "cost_price": Decimal("100.00"),
                "sell_price": Decimal("200.00"),
                "stock_level": "LOW",
                "status": "ACTIVE",
            },
            {
                "id": 11,
                "sku": "SS-OUT",
                "name": "Samsung Test",
                "brand_name": "Samsung",
                "stock": 0,
                "min_stock": 2,
                "cost_price": Decimal("50.00"),
                "sell_price": Decimal("100.00"),
                "stock_level": "OUT",
                "status": "ACTIVE",
            },
            {
                "id": 12,
                "sku": "OP-OK",
                "name": "Oppo Test",
                "brand_name": "Oppo",
                "stock": 12,
                "min_stock": 5,
                "cost_price": Decimal("70.00"),
                "sell_price": Decimal("140.00"),
                "stock_level": "OK",
                "status": "ACTIVE",
            },
        ]
        self.moves = [{
            "id": 77,
            "sku": "IP-LOW",
            "product_id": 10,
            "type": "IMPORT",
            "quantity_change": 3,
            "stock_after": 3,
            "ref_type": "IMPORT_RECEIPT",
            "ref_id": 42,
            "operation_key": "IMPORT:42:10",
            "created_by_name": "Admin",
            "created_at": "2026-11-11 02:00:00",
        }]

    def list_inventory(self, **kwargs):
        self.inventory_calls.append(kwargs)
        if self.error:
            raise AppError(self.error, "Truy cập bị từ chối.")

        rows = list(self.products)
        if not kwargs["include_discontinued"]:
            rows = [
                row for row in rows
                if row["status"] == "ACTIVE"
            ]
        level = kwargs["level"]
        if level == "OUT":
            rows = [
                row for row in rows if row["stock_level"] == "OUT"
            ]
        elif level == "LOW":
            rows = [
                row for row in rows if row["stock_level"] == "LOW"
            ]
        elif level == "ALERT":
            rows = [
                row for row in rows
                if row["stock_level"] in {"LOW", "OUT"}
            ]
        start = kwargs["offset"]
        return rows[start:start + kwargs["limit"]]

    def list_movements(self, **kwargs):
        self.movement_calls.append(kwargs)
        if self.error:
            raise AppError(self.error, "Truy cập bị từ chối.")

        rows = list(self.moves)
        if kwargs["product_id"] is not None:
            rows = [
                row for row in rows
                if row["product_id"] == kwargs["product_id"]
            ]
        if kwargs["movement_type"] is not None:
            rows = [
                row for row in rows
                if row["type"] == kwargs["movement_type"]
            ]
        start = kwargs["offset"]
        return rows[start:start + kwargs["limit"]]


@pytest.fixture
def env():
    page = FakePage()
    service = FakeQueries()
    panel = InventoryPanel(page, service=service)
    panel.load(redraw=False)

    return SimpleNamespace(
        page=page,
        panel=panel,
        service=service,
    )


def test_initial_load_reads_inventory_and_movements(env):
    assert len(env.service.inventory_calls) == 1
    assert len(env.service.movement_calls) == 1
    assert env.page.updates == 0


def test_default_inventory_filter_is_all_active(env):
    args = env.service.inventory_calls[-1]
    assert args["level"] == "ALL"
    assert args["include_discontinued"] is False
    assert args["limit"] == PAGE_SIZE + 1


@pytest.mark.parametrize(
    "level,expected",
    [
        ("ALL", 3),
        ("ALERT", 2),
        ("LOW", 1),
        ("OUT", 1),
    ],
)
def test_inventory_filter_selects_correct_rows(env, level, expected):
    env.panel.level.value = level
    env.panel.apply_inventory_filter()
    args = env.service.inventory_calls[-1]
    assert args["level"] == level

    rows = env.service.list_inventory(**args)
    assert len(rows) == expected


def test_include_discontinued_is_forwarded(env):
    env.panel.include_discontinued.value = True
    env.panel.apply_inventory_filter()
    assert env.service.inventory_calls[-1][
        "include_discontinued"
    ] is True


def test_inventory_filter_resets_offset(env):
    env.panel.inventory_offset = PAGE_SIZE
    env.panel.level.value = "LOW"
    env.panel.apply_inventory_filter()
    assert env.panel.inventory_offset == 0


def test_movement_filter_by_product_and_type(env):
    env.panel.movement_product_id.value = "10"
    env.panel.movement_type.value = "IMPORT"
    env.panel.apply_movement_filter()

    args = env.service.movement_calls[-1]
    assert args["product_id"] == 10
    assert args["movement_type"] == "IMPORT"


def test_movement_all_type_maps_to_none(env):
    env.panel.movement_type.value = "ALL"
    env.panel.apply_movement_filter()
    assert env.service.movement_calls[-1][
        "movement_type"
    ] is None


@pytest.mark.parametrize(
    "value",
    ["-1", "0", "abc", "1.5"],
)
def test_invalid_product_id_does_not_call_service(env, value):
    previous = len(env.service.movement_calls)
    env.panel.movement_product_id.value = value
    env.panel.apply_movement_filter()

    assert len(env.service.movement_calls) == previous
    assert "Product ID" in env.panel.message.value


def test_click_inventory_product_filters_movement(env):
    env.panel.show_product_movements(10)
    assert env.panel.movement_product_id.value == "10"
    assert env.service.movement_calls[-1][
        "product_id"
    ] == 10


def test_inventory_pagination_uses_extra_row(env):
    env.service.products = [
        {
            "id": i,
            "sku": f"SKU-{i}",
            "name": f"Product {i}",
            "brand_name": "Brand",
            "stock": 1,
            "min_stock": 0,
            "cost_price": Decimal("10.00"),
            "sell_price": Decimal("20.00"),
            "stock_level": "OK",
            "status": "ACTIVE",
        }
        for i in range(PAGE_SIZE + 1)
    ]

    env.panel.load_inventory()
    assert env.panel.has_next_inventory
    env.panel.next_inventory()
    assert env.panel.inventory_offset == PAGE_SIZE
    env.panel.previous_inventory()
    assert env.panel.inventory_offset == 0


def test_movement_pagination_uses_extra_row(env):
    template = env.service.moves[0]
    env.service.moves = [
        {**template, "id": i}
        for i in range(PAGE_SIZE + 1)
    ]
    env.panel.load_movements()
    assert env.panel.has_next_movement
    env.panel.next_movement()
    assert env.panel.movement_offset == PAGE_SIZE
    env.panel.previous_movement()
    assert env.panel.movement_offset == 0


def test_forbidden_hides_sensitive_tables(env):
    env.service.error = "FORBIDDEN"
    env.panel.load_inventory()
    assert env.panel.inventory_holder.controls == []
    assert env.panel.movement_holder.controls == []


def test_locked_session_navigates_to_login(env):
    env.panel.handle_error(
        AppError("ACCOUNT_LOCKED", "Tài khoản bị khóa.")
    )
    assert env.page.routes == ["/login"]
    assert env.panel.inventory_holder.controls == []


def test_main_has_both_warehouse_routes():
    source = Path("main.py").read_text(encoding="utf-8")

    assert "from ui.pages.import_page import build_import_page" in source
    assert (
        "from ui.pages.inventory_page import build_inventory_page"
        in source
    )
    assert 'if route == "/admin/imports":' in source
    assert 'if route == "/admin/inventory":' in source
    assert "return build_import_page(page)" in source
    assert "return build_inventory_page(page)" in source
