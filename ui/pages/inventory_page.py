
"""Task 40 / US07: inventory alerts and stock movement history UI."""

import logging

import flet as ft

from models.app_error import AppError
from services.warehouse_query_service import WarehouseQueryService
from ui.components.money_format import format_vnd

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


class InventoryPanel:
    """Warehouse reads only; never performs stock or cost updates."""

    def __init__(
        self,
        page: ft.Page,
        *,
        service: WarehouseQueryService,
    ) -> None:
        self.page = page
        self.service = service
        self.inventory_offset = 0
        self.movement_offset = 0
        self.has_next_inventory = False
        self.has_next_movement = False

        self.message = ft.Text(color=ft.Colors.RED_700)

        self.level = ft.Dropdown(
            label="Trạng thái tồn kho",
            width=240,
            value="ALL",
            options=[
                ft.DropdownOption(key="ALL", text="Tất cả"),
                ft.DropdownOption(
                    key="ALERT", text="Cần cảnh báo"
                ),
                ft.DropdownOption(key="LOW", text="Tồn thấp"),
                ft.DropdownOption(key="OUT", text="Hết hàng"),
            ],
        )
        self.include_discontinued = ft.Checkbox(
            label="Bao gồm sản phẩm ngừng kinh doanh",
            value=False,
        )

        self.inventory_holder = ft.Column()
        self.inventory_page = ft.Text()
        self.inventory_previous = ft.Button(
            "Tồn trước",
            on_click=self.previous_inventory,
            disabled=True,
        )
        self.inventory_next = ft.Button(
            "Tồn sau",
            on_click=self.next_inventory,
            disabled=True,
        )

        self.movement_product_id = ft.TextField(
            label="Lọc biến động theo Product ID (để trống = tất cả)",
            width=370,
        )
        self.movement_type = ft.Dropdown(
            label="Loại biến động",
            width=230,
            value="ALL",
            options=[
                ft.DropdownOption(key="ALL", text="Tất cả"),
                ft.DropdownOption(key="IMPORT", text="Nhập kho"),
                ft.DropdownOption(key="SALE", text="Bán hàng"),
                ft.DropdownOption(
                    key="CANCEL_RESTORE",
                    text="Hoàn tồn khi hủy",
                ),
                ft.DropdownOption(
                    key="ADJUST",
                    text="Điều chỉnh tồn",
                ),
            ],
        )

        self.movement_holder = ft.Column()
        self.movement_page = ft.Text()
        self.movement_previous = ft.Button(
            "Biến động trước",
            on_click=self.previous_movement,
            disabled=True,
        )
        self.movement_next = ft.Button(
            "Biến động sau",
            on_click=self.next_movement,
            disabled=True,
        )

        self.root = ft.Column(
            spacing=16,
            controls=[
                ft.Text(
                    "QUẢN LÝ TỒN KHO",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Theo dõi số lượng, giá vốn và ngưỡng tồn thấp. "
                    "Trang này chỉ đọc dữ liệu, không điều chỉnh tồn."
                ),
                self.message,
                ft.Row(
                    wrap=True,
                    spacing=12,
                    controls=[
                        self.level,
                        self.include_discontinued,
                        ft.Button(
                            "Lọc tồn kho",
                            on_click=self.apply_inventory_filter,
                        ),
                    ],
                ),
                self.inventory_holder,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.inventory_previous,
                        self.inventory_page,
                        self.inventory_next,
                    ],
                ),
                ft.Divider(),
                ft.Text(
                    "LỊCH SỬ BIẾN ĐỘNG KHO",
                    size=21,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Row(
                    wrap=True,
                    spacing=12,
                    controls=[
                        self.movement_product_id,
                        self.movement_type,
                        ft.Button(
                            "Lọc biến động",
                            on_click=self.apply_movement_filter,
                        ),
                    ],
                ),
                self.movement_holder,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.movement_previous,
                        self.movement_page,
                        self.movement_next,
                    ],
                ),
            ],
        )

    @property
    def store(self):
        return self.page.session.store

    def refresh(self) -> None:
        self.page.update()

    def handle_error(self, exc: AppError) -> None:
        self.message.value = exc.message
        if exc.errors:
            self.message.value += ": " + "; ".join(
                str(value) for value in exc.errors.values()
            )
        if exc.error_code in {
            "FORBIDDEN", "UNAUTHORIZED", "ACCOUNT_LOCKED"
        }:
            self.inventory_holder.controls = []
            self.movement_holder.controls = []

        if exc.error_code in {"UNAUTHORIZED", "ACCOUNT_LOCKED"}:
            self.page.navigate("/login")
        else:
            self.refresh()

    def load(self, *, redraw: bool = True) -> None:
        self.load_inventory(redraw=False)
        self.load_movements(redraw=False)
        if redraw:
            self.refresh()

    def apply_inventory_filter(self, e=None) -> None:
        self.inventory_offset = 0
        self.load_inventory()

    def load_inventory(self, *, redraw: bool = True) -> None:
        try:
            rows = self.service.list_inventory(
                session_store=self.store,
                level=self.level.value or "ALL",
                include_discontinued=bool(
                    self.include_discontinued.value
                ),
                limit=PAGE_SIZE + 1,
                offset=self.inventory_offset,
            )
            self.has_next_inventory = len(rows) > PAGE_SIZE
            displayed = rows[:PAGE_SIZE]

            self.inventory_previous.disabled = (
                self.inventory_offset == 0
            )
            self.inventory_next.disabled = (
                not self.has_next_inventory
            )
            self.inventory_page.value = (
                f"Trang {self.inventory_offset // PAGE_SIZE + 1}"
            )
            self.message.value = ""

            if not displayed:
                self.inventory_holder.controls = [
                    ft.Text("Không có sản phẩm phù hợp.")
                ]
            else:
                self.render_inventory(displayed)
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot load inventory")
            self.message.value = "Không thể tải tồn kho."
        if redraw:
            self.refresh()

    def render_inventory(self, rows: list[dict]) -> None:
        labels = {
            "OUT": "Hết hàng",
            "LOW": "Tồn thấp",
            "OK": "Bình thường",
        }
        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("SKU")),
                ft.DataColumn(label=ft.Text("Sản phẩm")),
                ft.DataColumn(label=ft.Text("Hãng")),
                ft.DataColumn(label=ft.Text("Tồn")),
                ft.DataColumn(label=ft.Text("Tồn tối thiểu")),
                ft.DataColumn(label=ft.Text("Giá vốn")),
                ft.DataColumn(label=ft.Text("Giá bán")),
                ft.DataColumn(label=ft.Text("Cảnh báo")),
                ft.DataColumn(label=ft.Text("Biến động")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(row["sku"]))),
                        ft.DataCell(ft.Text(str(row["name"]))),
                        ft.DataCell(ft.Text(str(row["brand_name"]))),
                        ft.DataCell(ft.Text(str(row["stock"]))),
                        ft.DataCell(ft.Text(str(row["min_stock"]))),
                        ft.DataCell(
                            ft.Text(format_vnd(row["cost_price"]))
                        ),
                        ft.DataCell(
                            ft.Text(format_vnd(row["sell_price"]))
                        ),
                        ft.DataCell(
                            ft.Text(
                                labels.get(
                                    row["stock_level"],
                                    "Không xác định",
                                )
                            )
                        ),
                        ft.DataCell(
                            ft.TextButton(
                                "Xem",
                                on_click=(
                                    lambda e, pid=row["id"]:
                                    self.show_product_movements(pid)
                                ),
                            )
                        ),
                    ]
                )
                for row in rows
            ],
        )
        self.inventory_holder.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def previous_inventory(self, e=None) -> None:
        if self.inventory_offset >= PAGE_SIZE:
            self.inventory_offset -= PAGE_SIZE
            self.load_inventory()

    def next_inventory(self, e=None) -> None:
        if self.has_next_inventory:
            self.inventory_offset += PAGE_SIZE
            self.load_inventory()

    def apply_movement_filter(self, e=None) -> None:
        self.movement_offset = 0
        self.load_movements()

    def _movement_product_filter(self) -> int | None:
        raw = (self.movement_product_id.value or "").strip()
        if not raw:
            return None

        if not raw.isascii() or not raw.isdigit():
            raise ValueError("Product ID phải là số nguyên dương.")

        product_id = int(raw)
        if product_id <= 0:
            raise ValueError("Product ID phải lớn hơn 0.")
        return product_id

    def load_movements(self, *, redraw: bool = True) -> None:
        try:
            product_id = self._movement_product_filter()
            movement_type = self.movement_type.value or "ALL"

            rows = self.service.list_movements(
                session_store=self.store,
                product_id=product_id,
                movement_type=(
                    None
                    if movement_type == "ALL"
                    else movement_type
                ),
                limit=PAGE_SIZE + 1,
                offset=self.movement_offset,
            )
            self.has_next_movement = len(rows) > PAGE_SIZE
            displayed = rows[:PAGE_SIZE]

            self.movement_previous.disabled = (
                self.movement_offset == 0
            )
            self.movement_next.disabled = (
                not self.has_next_movement
            )
            self.movement_page.value = (
                f"Trang {self.movement_offset // PAGE_SIZE + 1}"
            )
            self.message.value = ""

            if not displayed:
                self.movement_holder.controls = [
                    ft.Text("Chưa có biến động kho phù hợp.")
                ]
            else:
                self.render_movements(displayed)
        except ValueError as exc:
            self.message.value = str(exc)
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot load stock movements")
            self.message.value = "Không thể tải lịch sử biến động."
        if redraw:
            self.refresh()

    def render_movements(self, rows: list[dict]) -> None:
        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID")),
                ft.DataColumn(label=ft.Text("SKU")),
                ft.DataColumn(label=ft.Text("Loại")),
                ft.DataColumn(label=ft.Text("Thay đổi")),
                ft.DataColumn(label=ft.Text("Tồn sau")),
                ft.DataColumn(label=ft.Text("Nguồn")),
                ft.DataColumn(label=ft.Text("Operation Key")),
                ft.DataColumn(label=ft.Text("Người thực hiện")),
                ft.DataColumn(label=ft.Text("Thời gian UTC")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(row["id"]))),
                        ft.DataCell(ft.Text(str(row["sku"]))),
                        ft.DataCell(ft.Text(str(row["type"]))),
                        ft.DataCell(
                            ft.Text(
                                str(row["quantity_change"])
                            )
                        ),
                        ft.DataCell(
                            ft.Text(str(row["stock_after"]))
                        ),
                        ft.DataCell(
                            ft.Text(
                                f"{row['ref_type']}:{row['ref_id']}"
                            )
                        ),
                        ft.DataCell(
                            ft.Text(str(row["operation_key"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(row["created_by_name"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(row["created_at"]))
                        ),
                    ]
                )
                for row in rows
            ],
        )
        self.movement_holder.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def previous_movement(self, e=None) -> None:
        if self.movement_offset >= PAGE_SIZE:
            self.movement_offset -= PAGE_SIZE
            self.load_movements()

    def next_movement(self, e=None) -> None:
        if self.has_next_movement:
            self.movement_offset += PAGE_SIZE
            self.load_movements()

    def show_product_movements(self, product_id: int) -> None:
        self.movement_product_id.value = str(product_id)
        self.movement_type.value = "ALL"
        self.movement_offset = 0
        self.load_movements()


def build_inventory_page(page: ft.Page) -> ft.Column:
    """Factory used after the route guard checks VIEW_INVENTORY."""
    panel = InventoryPanel(
        page,
        service=WarehouseQueryService(),
    )
    panel.load(redraw=False)
    return panel.root
