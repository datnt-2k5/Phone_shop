
"""Task 40 / US07: create imports and read import history in Flet Web."""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import flet as ft

from models.app_error import AppError
from services.catalog_service import CatalogService
from services.import_service import ImportService
from services.product_management_service import ProductManagementService
from services.warehouse_query_service import WarehouseQueryService
from ui.components.money_format import format_vnd
from ui.components.notifications import notify

logger = logging.getLogger(__name__)

PRODUCT_PAGE_SIZE = 20
SUPPLIER_PAGE_SIZE = 30
HISTORY_PAGE_SIZE = 10


class ImportPanel:
    """All database operations go through existing protected Services."""

    def __init__(
        self,
        page: ft.Page,
        *,
        importer: ImportService,
        catalog: CatalogService,
        products: ProductManagementService,
        queries: WarehouseQueryService,
    ) -> None:
        self.page = page
        self.importer = importer
        self.catalog = catalog
        self.products = products
        self.queries = queries

        self.busy = False
        self.lines: list[dict[str, Any]] = []
        self.search_results: dict[int, dict[str, Any]] = {}
        self.supplier_offset = 0
        self.product_offset = 0
        self.history_offset = 0
        self.has_more_suppliers = False
        self.has_more_products = False
        self.has_more_history = False

        self.message = ft.Text(color=ft.Colors.RED_700)
        self.success = ft.Text(color=ft.Colors.GREEN_700)

        self.supplier = ft.Dropdown(
            label="Nhà cung cấp đang hợp tác *",
            width=350,
            options=[],
        )
        self.supplier_page = ft.Text()

        self.supplier_previous = ft.Button(
            "NCC trước",
            on_click=self.previous_supplier,
            disabled=True,
        )
        self.supplier_next = ft.Button(
            "NCC sau",
            on_click=self.next_supplier,
            disabled=True,
        )

        self.keyword = ft.TextField(
            label="Tìm SKU hoặc tên sản phẩm",
            width=330,
            on_submit=self.apply_product_search,
        )
        self.product = ft.Dropdown(
            label="Chọn sản phẩm đang bán *",
            width=440,
            options=[],
        )
        self.product_page = ft.Text()

        self.product_previous = ft.Button(
            "Sản phẩm trước",
            on_click=self.previous_product,
            disabled=True,
        )
        self.product_next = ft.Button(
            "Sản phẩm sau",
            on_click=self.next_product,
            disabled=True,
        )

        self.quantity = ft.TextField(
            label="Số lượng nhập *",
            value="1",
            width=170,
        )
        self.price = ft.TextField(
            label="Đơn giá nhập (VND) *",
            width=220,
        )
        self.note = ft.TextField(
            label="Ghi chú",
            width=530,
            multiline=True,
            min_lines=2,
        )

        self.draft_holder = ft.Column()
        self.total_text = ft.Text(
            "Tổng tiền: 0 ₫",
            size=18,
            weight=ft.FontWeight.BOLD,
        )
        self.save_button = ft.Button(
            "Xác nhận nhập kho",
            on_click=self.ask_confirm,
        )

        self.history_holder = ft.Column()
        self.history_page = ft.Text()
        self.history_previous = ft.Button(
            "Phiếu trước",
            on_click=self.previous_history,
            disabled=True,
        )
        self.history_next = ft.Button(
            "Phiếu sau",
            on_click=self.next_history,
            disabled=True,
        )
        self.detail_holder = ft.Column(visible=False)

        self.root = ft.Column(
            spacing=15,
            controls=[
                ft.Text(
                    "LẬP PHIẾU NHẬP KHO",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Phiếu nhập chỉ được lưu sau khi bạn xác nhận. "
                    "Số lượng tồn và giá vốn sẽ được cập nhật "
                    "trong cùng transaction."
                ),
                self.message,
                self.success,
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        self.supplier,
                        self.supplier_previous,
                        self.supplier_next,
                        self.supplier_page,
                    ],
                ),
                ft.Divider(),
                ft.Text(
                    "CHỌN SẢN PHẨM",
                    weight=ft.FontWeight.BOLD,
                    size=18,
                ),
                ft.Row(
                    wrap=True,
                    controls=[
                        self.keyword,
                        ft.Button(
                            "Tìm sản phẩm",
                            on_click=self.apply_product_search,
                        ),
                        self.product_previous,
                        self.product_next,
                    ],
                ),
                self.product_page,
                self.product,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.quantity,
                        self.price,
                        ft.Button(
                            "Thêm vào phiếu",
                            on_click=self.add_item,
                        ),
                    ],
                ),
                ft.Divider(),
                ft.Text(
                    "CHI TIẾT PHIẾU ĐANG LẬP",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                ),
                self.draft_holder,
                self.total_text,
                self.note,
                self.save_button,
                ft.Divider(),
                ft.Text(
                    "LỊCH SỬ PHIẾU NHẬP",
                    size=20,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Button(
                    "Làm mới lịch sử",
                    on_click=self.reload_history,
                ),
                self.history_holder,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.history_previous,
                        self.history_page,
                        self.history_next,
                    ],
                ),
                self.detail_holder,
            ],
        )
        self.render_draft()

    @property
    def store(self):
        return self.page.session.store

    def refresh(self) -> None:
        self.page.update()

    def handle_error(self, exc: AppError) -> None:
        self.success.value = ""
        self.message.value = exc.message
        if exc.errors:
            self.message.value += ": " + "; ".join(
                str(value) for value in exc.errors.values()
            )

        if exc.error_code in {
            "FORBIDDEN", "UNAUTHORIZED", "ACCOUNT_LOCKED"
        }:
            self.history_holder.controls = []
            self.detail_holder.controls = []
            self.detail_holder.visible = False

        if exc.error_code in {"UNAUTHORIZED", "ACCOUNT_LOCKED"}:
            self.page.navigate("/login")
        else:
            self.refresh()

    def load(self, *, redraw: bool = True) -> None:
        """Called before attaching root to Flet View."""
        try:
            self.load_suppliers(redraw=False)
            self.search_products(redraw=False)
            self.load_history(redraw=False)
        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception("Cannot load import page")
            self.message.value = "Không thể tải trang nhập kho."
        if redraw:
            self.refresh()

    def load_suppliers(self, *, redraw: bool = True) -> None:
        try:
            rows = self.catalog.list_suppliers(
                session_store=self.store,
                is_active=True,
                limit=SUPPLIER_PAGE_SIZE + 1,
                offset=self.supplier_offset,
            )
            self.has_more_suppliers = len(rows) > SUPPLIER_PAGE_SIZE
            visible = rows[:SUPPLIER_PAGE_SIZE]

            self.supplier.options = [
                ft.DropdownOption(
                    key=str(row["id"]),
                    text=str(row["name"]),
                )
                for row in visible
            ]
            self.supplier.value = None
            self.supplier_previous.disabled = self.supplier_offset == 0
            self.supplier_next.disabled = not self.has_more_suppliers
            self.supplier_page.value = (
                f"Trang {self.supplier_offset // SUPPLIER_PAGE_SIZE + 1}"
            )
            if not visible:
                self.message.value = (
                    "Không có nhà cung cấp đang hợp tác trên trang này."
                )
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot load suppliers")
            self.message.value = "Không thể tải nhà cung cấp."
        if redraw:
            self.refresh()

    def previous_supplier(self, e=None) -> None:
        if self.supplier_offset >= SUPPLIER_PAGE_SIZE:
            self.supplier_offset -= SUPPLIER_PAGE_SIZE
            self.load_suppliers()

    def next_supplier(self, e=None) -> None:
        if self.has_more_suppliers:
            self.supplier_offset += SUPPLIER_PAGE_SIZE
            self.load_suppliers()

    def apply_product_search(self, e=None) -> None:
        self.product_offset = 0
        self.search_products()

    def search_products(self, *, redraw: bool = True) -> None:
        try:
            result = self.products.search_admin(
                session_store=self.store,
                keyword=(self.keyword.value or "").strip() or None,
                status="ACTIVE",
                sort_by="newest",
                limit=PRODUCT_PAGE_SIZE,
                offset=self.product_offset,
            )
            rows = result["items"]
            total = int(result["total"])
            self.search_results = {
                int(row["id"]): dict(row) for row in rows
            }
            self.product.options = [
                ft.DropdownOption(
                    key=str(row["id"]),
                    text=f"{row['sku']} - {row['name']}",
                )
                for row in rows
            ]
            self.product.value = None
            self.has_more_products = (
                self.product_offset + PRODUCT_PAGE_SIZE < total
            )
            self.product_previous.disabled = self.product_offset == 0
            self.product_next.disabled = not self.has_more_products
            self.product_page.value = (
                f"Tìm thấy {total} sản phẩm - "
                f"trang {self.product_offset // PRODUCT_PAGE_SIZE + 1}"
            )
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot search import products")
            self.message.value = "Không thể tìm sản phẩm."
        if redraw:
            self.refresh()

    def previous_product(self, e=None) -> None:
        if self.product_offset >= PRODUCT_PAGE_SIZE:
            self.product_offset -= PRODUCT_PAGE_SIZE
            self.search_products()

    def next_product(self, e=None) -> None:
        if self.has_more_products:
            self.product_offset += PRODUCT_PAGE_SIZE
            self.search_products()

    def add_item(self, e=None) -> None:
        try:
            if not self.product.value:
                raise ValueError("Vui lòng chọn sản phẩm.")

            product_id = int(self.product.value)
            selected = self.search_results.get(product_id)
            if selected is None:
                raise ValueError("Sản phẩm không nằm trong kết quả tìm.")

            if any(
                row["product_id"] == product_id
                for row in self.lines
            ):
                raise ValueError("Sản phẩm đã có trong phiếu.")

            qty_text = (self.quantity.value or "").strip()
            if not qty_text.isascii() or not qty_text.isdigit():
                raise ValueError("Số lượng phải là số nguyên dương.")

            qty = int(qty_text)
            if not 1 <= qty <= 2_147_483_647:
                raise ValueError("Số lượng không hợp lệ.")

            price_text = (self.price.value or "").strip()
            price = Decimal(price_text)

            if (
                not price.is_finite()
                or price <= 0
                or price > Decimal("9999999999999999.99")
                or price != price.quantize(Decimal("0.01"))
            ):
                raise ValueError("Giá nhập không hợp lệ.")

            self.lines.append(
                {
                    "product_id": product_id,
                    "sku": str(selected["sku"]),
                    "name": str(selected["name"]),
                    "quantity": qty,
                    "import_price": format(price, "f"),
                }
            )
            self.message.value = ""
            self.success.value = "Đã thêm sản phẩm vào phiếu."
            self.product.value = None
            self.price.value = ""
            self.quantity.value = "1"
            self.render_draft()
            self.refresh()
        except (ValueError, InvalidOperation) as exc:
            self.message.value = str(exc)
            self.success.value = ""
            self.refresh()

    def remove_item(self, product_id: int) -> None:
        self.lines = [
            row
            for row in self.lines
            if row["product_id"] != product_id
        ]
        self.render_draft()
        self.refresh()

    def render_draft(self) -> None:
        if not self.lines:
            self.draft_holder.controls = [
                ft.Text("Chưa có sản phẩm trong phiếu nhập.")
            ]
            self.total_text.value = "Tổng tiền: 0 ₫"
            return

        total = Decimal("0.00")
        rows = []
        for item in self.lines:
            line_total = (
                Decimal(item["import_price"]) * item["quantity"]
            )
            total += line_total
            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(item["sku"])),
                        ft.DataCell(ft.Text(item["name"])),
                        ft.DataCell(ft.Text(str(item["quantity"]))),
                        ft.DataCell(
                            ft.Text(format_vnd(item["import_price"]))
                        ),
                        ft.DataCell(ft.Text(format_vnd(line_total))),
                        ft.DataCell(
                            ft.TextButton(
                                "Bỏ",
                                on_click=(
                                    lambda e, pid=item["product_id"]:
                                    self.remove_item(pid)
                                ),
                            )
                        ),
                    ]
                )
            )

        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("SKU")),
                ft.DataColumn(label=ft.Text("Sản phẩm")),
                ft.DataColumn(label=ft.Text("Số lượng")),
                ft.DataColumn(label=ft.Text("Giá nhập")),
                ft.DataColumn(label=ft.Text("Thành tiền")),
                ft.DataColumn(label=ft.Text("Thao tác")),
            ],
            rows=rows,
        )
        self.draft_holder.controls = [
            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[table])
        ]
        self.total_text.value = f"Tổng tiền: {format_vnd(total)}"

    def ask_confirm(self, e=None) -> None:
        if self.busy:
            return
        if not self.supplier.value or not self.lines:
            self.message.value = (
                "Vui lòng chọn nhà cung cấp và thêm sản phẩm."
            )
            self.refresh()
            return

        state = {"choice": None, "handled": False}

        def choose(value: str) -> None:
            if state["choice"] is not None:
                return
            state["choice"] = value
            self.page.pop_dialog()

        def dismissed(e) -> None:
            if state["handled"]:
                return
            state["handled"] = True
            if state["choice"] == "confirm":
                self.save_import()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Xác nhận nhập kho"),
            content=ft.Text(
                f"Bạn muốn nhập {len(self.lines)} sản phẩm? "
                f"{self.total_text.value}. "
                "Khi hoàn tất, hệ thống sẽ cập nhật tồn và giá vốn."
            ),
            actions=[
                ft.TextButton(
                    "Quay lại",
                    on_click=lambda e: choose("cancel"),
                ),
                ft.Button(
                    "Xác nhận",
                    on_click=lambda e: choose("confirm"),
                ),
            ],
            on_dismiss=dismissed,
        )
        self.page.show_dialog(dialog)

    def save_import(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.save_button.disabled = True
        try:
            payload = [
                {
                    "product_id": row["product_id"],
                    "quantity": row["quantity"],
                    "import_price": row["import_price"],
                }
                for row in self.lines
            ]
            result = self.importer.create_import(
                session_store=self.store,
                supplier_id=int(self.supplier.value),
                items=payload,
                note=(self.note.value or "").strip() or None,
            )
        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception("Cannot create stock import")
            self.message.value = "Không thể tạo phiếu nhập."
            self.refresh()
        else:
            # Đã commit: phải xóa draft để tránh nhập lặp khi làm mới.
            self.lines.clear()
            self.note.value = ""
            self.render_draft()
            self.message.value = ""
            self.success.value = (
                f"Đã tạo phiếu nhập {result['code']} thành công."
            )
            try:
                self.history_offset = 0
                self.load_history(redraw=False)
                self.show_receipt(int(result["id"]), redraw=False)
            except Exception:
                logger.exception("Cannot refresh saved import details")
                # Phiếu đã lưu; không khôi phục draft hoặc ghi thêm lần hai.
            notify(self.page, self.success.value)
            self.refresh()
        finally:
            self.busy = False
            self.save_button.disabled = False
            self.refresh()

    def reload_history(self, e=None) -> None:
        self.history_offset = 0
        self.load_history()

    def load_history(self, *, redraw: bool = True) -> None:
        try:
            rows = self.queries.list_receipts(
                session_store=self.store,
                limit=HISTORY_PAGE_SIZE + 1,
                offset=self.history_offset,
            )
            self.has_more_history = len(rows) > HISTORY_PAGE_SIZE
            displayed = rows[:HISTORY_PAGE_SIZE]
            self.history_previous.disabled = self.history_offset == 0
            self.history_next.disabled = not self.has_more_history
            self.history_page.value = (
                f"Trang {self.history_offset // HISTORY_PAGE_SIZE + 1}"
            )
            if not displayed:
                self.history_holder.controls = [
                    ft.Text("Chưa có phiếu nhập trên trang này.")
                ]
            else:
                table = ft.DataTable(
                    columns=[
                        ft.DataColumn(label=ft.Text("Mã phiếu")),
                        ft.DataColumn(label=ft.Text("Nhà cung cấp")),
                        ft.DataColumn(label=ft.Text("Tổng tiền")),
                        ft.DataColumn(label=ft.Text("Người nhập")),
                        ft.DataColumn(label=ft.Text("Chi tiết")),
                    ],
                    rows=[
                        ft.DataRow(
                            cells=[
                                ft.DataCell(ft.Text(str(row["code"]))),
                                ft.DataCell(
                                    ft.Text(str(row["supplier_name"]))
                                ),
                                ft.DataCell(
                                    ft.Text(format_vnd(row["total_amount"]))
                                ),
                                ft.DataCell(
                                    ft.Text(str(row["created_by_name"]))
                                ),
                                ft.DataCell(
                                    ft.TextButton(
                                        "Xem",
                                        on_click=(
                                            lambda e, rid=row["id"]:
                                            self.show_receipt(rid)
                                        ),
                                    )
                                ),
                            ]
                        )
                        for row in displayed
                    ],
                )
                self.history_holder.controls = [
                    ft.Row(
                        scroll=ft.ScrollMode.AUTO,
                        controls=[table],
                    )
                ]
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot load import history")
            self.message.value = "Không thể đọc lịch sử phiếu nhập."
        if redraw:
            self.refresh()

    def previous_history(self, e=None) -> None:
        if self.history_offset >= HISTORY_PAGE_SIZE:
            self.history_offset -= HISTORY_PAGE_SIZE
            self.load_history()

    def next_history(self, e=None) -> None:
        if self.has_more_history:
            self.history_offset += HISTORY_PAGE_SIZE
            self.load_history()

    def show_receipt(
        self, receipt_id: int, *, redraw: bool = True
    ) -> None:
        try:
            data = self.queries.get_receipt(
                session_store=self.store,
                receipt_id=int(receipt_id),
            )
            header = data["receipt"]
            items = data["items"]
            table = ft.DataTable(
                columns=[
                    ft.DataColumn(label=ft.Text("SKU")),
                    ft.DataColumn(label=ft.Text("Sản phẩm")),
                    ft.DataColumn(label=ft.Text("Số lượng")),
                    ft.DataColumn(label=ft.Text("Giá nhập")),
                    ft.DataColumn(label=ft.Text("Thành tiền")),
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(row["sku"]))),
                            ft.DataCell(ft.Text(str(row["product_name"]))),
                            ft.DataCell(ft.Text(str(row["quantity"]))),
                            ft.DataCell(
                                ft.Text(format_vnd(row["import_price"]))
                            ),
                            ft.DataCell(
                                ft.Text(format_vnd(row["line_total"]))
                            ),
                        ]
                    )
                    for row in items
                ],
            )
            self.detail_holder.controls = [
                ft.Divider(),
                ft.Text(
                    f"CHI TIẾT PHIẾU {header['code']}",
                    size=19,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f"Nhà cung cấp: {header['supplier_name']}"
                ),
                ft.Text(
                    f"Tổng tiền: {format_vnd(header['total_amount'])}"
                ),
                ft.Text(
                    f"Ghi chú: {header.get('note') or 'Không có'}"
                ),
                ft.Row(
                    scroll=ft.ScrollMode.AUTO,
                    controls=[table],
                ),
                ft.TextButton(
                    "Đóng chi tiết",
                    on_click=self.close_detail,
                ),
            ]
            self.detail_holder.visible = True
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Cannot read import receipt detail")
            self.message.value = "Không thể đọc chi tiết phiếu nhập."
        if redraw:
            self.refresh()

    def close_detail(self, e=None) -> None:
        self.detail_holder.visible = False
        self.refresh()


def build_import_page(page: ft.Page) -> ft.Column:
    """Build after main.py has checked the admin route."""
    panel = ImportPanel(
        page,
        importer=ImportService(),
        catalog=CatalogService(),
        products=ProductManagementService(),
        queries=WarehouseQueryService(),
    )
    panel.load(redraw=False)
    return panel.root
