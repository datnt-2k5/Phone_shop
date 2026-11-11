
"""Task 43: Flet stock-count form and adjustment history."""

import logging
from typing import Any

import flet as ft

from models.app_error import AppError
from services.product_management_service import ProductManagementService
from services.stock_adjustment_service import StockAdjustmentService
from ui.components.money_format import format_vnd
from ui.components.notifications import notify

logger = logging.getLogger(__name__)
PAGE_SIZE = 20
MAX_QTY = 2_147_483_647


class StockAdjustmentPanel:
    def __init__(
        self,
        page: ft.Page,
        *,
        products: ProductManagementService,
        service: StockAdjustmentService,
    ) -> None:
        self.page = page
        self.products = products
        self.service = service
        self.busy = False
        self.confirm_pending = False
        self.product_offset = 0
        self.history_offset = 0
        self.product_has_next = False
        self.history_has_next = False
        self.options_by_id: dict[int, dict[str, Any]] = {}
        self.lines: list[dict[str, Any]] = []

        self.error = ft.Text(color=ft.Colors.RED_700)
        self.success = ft.Text(color=ft.Colors.GREEN_700)

        self.keyword = ft.TextField(
            label="Tìm SKU hoặc tên sản phẩm",
            width=320,
            on_submit=self.search_changed,
        )
        self.product = ft.Dropdown(
            label="Chọn sản phẩm (cả ngừng kinh doanh)",
            width=440,
            options=[],
        )
        self.product_page = ft.Text()
        self.product_prev = ft.Button(
            "Sản phẩm trước",
            on_click=self.previous_product,
            disabled=True,
        )
        self.product_next = ft.Button(
            "Sản phẩm sau",
            on_click=self.next_product,
            disabled=True,
        )
        self.actual = ft.TextField(
            label="Số lượng kiểm kê thực tế",
            width=220,
            value="0",
        )
        self.reason = ft.TextField(
            label="Lý do kiểm kê *",
            multiline=True,
            min_lines=2,
            width=550,
        )
        self.draft_holder = ft.Column()
        self.confirm_button = ft.Button(
            "Xác nhận điều chỉnh tồn",
            on_click=self.ask_confirm,
        )

        self.history_holder = ft.Column()
        self.history_page = ft.Text()
        self.history_prev = ft.Button(
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
            spacing=14,
            controls=[
                ft.Text(
                    "KIỂM KÊ VÀ ĐIỀU CHỈNH TỒN",
                    size=24,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Số tồn hiển thị chỉ là tham khảo tại lúc tìm kiếm. "
                    "Khi xác nhận, hệ thống khóa sản phẩm, đọc lại tồn mới nhất "
                    "và tính chênh lệch trong transaction. Giá vốn không đổi."
                ),
                self.error,
                self.success,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.keyword,
                        ft.Button(
                            "Tìm",
                            on_click=self.search_changed,
                        ),
                        self.product_prev,
                        self.product_next,
                    ],
                ),
                self.product_page,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.product,
                        self.actual,
                        ft.Button(
                            "Thêm vào phiếu",
                            on_click=self.add_line,
                        ),
                    ],
                ),
                ft.Divider(),
                ft.Text(
                    "PHIẾU KIỂM KÊ ĐANG LẬP",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                ),
                self.draft_holder,
                self.reason,
                self.confirm_button,
                ft.Divider(),
                ft.Text(
                    "LỊCH SỬ ĐIỀU CHỈNH TỒN",
                    size=19,
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
                        self.history_prev,
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

    def refresh(self):
        self.page.update()

    def handle_error(self, exc: AppError):
        self.success.value = ""
        self.error.value = exc.message

        if exc.error_code in {
            "UNAUTHORIZED",
            "ACCOUNT_LOCKED",
            "FORBIDDEN",
        }:
            self.history_holder.controls = []
            self.detail_holder.controls = []
            self.detail_holder.visible = False
            self.options_by_id = {}
            self.product.options = []

        if exc.error_code in {
            "UNAUTHORIZED",
            "ACCOUNT_LOCKED",
        }:
            self.page.navigate("/login")
        else:
            self.refresh()

    def load(self, *, redraw=True):
        self.search_products(redraw=False)
        self.load_history(redraw=False)
        if redraw:
            self.refresh()

    def search_changed(self, e=None):
        self.product_offset = 0
        self.search_products()

    def search_products(self, *, redraw=True):
        try:
            result = self.products.search_admin(
                session_store=self.store,
                keyword=(self.keyword.value or "").strip() or None,
                status="ALL",
                sort_by="newest",
                limit=PAGE_SIZE,
                offset=self.product_offset,
            )
            rows = result["items"]
            total = int(result["total"])
            self.options_by_id = {
                int(row["id"]): dict(row)
                for row in rows
            }
            self.product.options = [
                ft.DropdownOption(
                    key=str(row["id"]),
                    text=(
                        f"{row['sku']} - {row['name']} "
                        f"(tồn {row['stock']})"
                    ),
                )
                for row in rows
            ]
            self.product.value = None
            self.product_has_next = (
                self.product_offset + PAGE_SIZE < total
            )
            self.product_prev.disabled = self.product_offset == 0
            self.product_next.disabled = not self.product_has_next
            self.product_page.value = (
                f"Tìm thấy {total} sản phẩm – trang "
                f"{self.product_offset // PAGE_SIZE + 1}"
            )
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception("Search stock-count products failed")
            self.error.value = "Không thể tìm sản phẩm."

        if redraw:
            self.refresh()

    def previous_product(self, e=None):
        if self.product_offset >= PAGE_SIZE:
            self.product_offset -= PAGE_SIZE
            self.search_products()

    def next_product(self, e=None):
        if self.product_has_next:
            self.product_offset += PAGE_SIZE
            self.search_products()

    def add_line(self, e=None):
        try:
            if not self.product.value:
                raise ValueError("Vui lòng chọn sản phẩm.")

            product_id = int(self.product.value)
            row = self.options_by_id.get(product_id)

            if row is None:
                raise ValueError(
                    "Sản phẩm không thuộc kết quả hiện tại."
                )

            if any(
                item["product_id"] == product_id
                for item in self.lines
            ):
                raise ValueError(
                    "Sản phẩm đã có trong phiếu kiểm kê."
                )

            raw = (self.actual.value or "").strip()
            if not raw.isascii() or not raw.isdigit():
                raise ValueError(
                    "Số thực tế phải là số nguyên không âm."
                )

            count = int(raw)
            if count > MAX_QTY:
                raise ValueError("Số thực tế vượt giới hạn.")

            self.lines.append(
                {
                    "product_id": product_id,
                    "sku": row["sku"],
                    "name": row["name"],
                    "stock_snapshot": int(row["stock"]),
                    "cost_snapshot": row["cost_price"],
                    "actual_quantity": count,
                }
            )
            self.error.value = ""
            self.success.value = "Đã thêm sản phẩm vào phiếu."
            self.actual.value = "0"
            self.product.value = None
            self.render_draft()
            self.refresh()
        except ValueError as exc:
            self.error.value = str(exc)
            self.success.value = ""
            self.refresh()

    def remove_line(self, product_id):
        self.lines = [
            line
            for line in self.lines
            if line["product_id"] != product_id
        ]
        self.render_draft()
        self.refresh()

    def render_draft(self):
        if not self.lines:
            self.draft_holder.controls = [
                ft.Text("Chưa có sản phẩm.")
            ]
            return

        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text(label))
                for label in (
                    "SKU",
                    "Sản phẩm",
                    "Tồn tham khảo",
                    "Thực tế",
                    "Chênh lệch dự kiến",
                    "Giá vốn (giữ nguyên)",
                    "Bỏ",
                )
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Text(str(line["sku"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(line["name"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(line["stock_snapshot"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(line["actual_quantity"]))
                        ),
                        ft.DataCell(
                            ft.Text(
                                f"{line['actual_quantity'] - line['stock_snapshot']:+d}"
                            )
                        ),
                        ft.DataCell(
                            ft.Text(format_vnd(line["cost_snapshot"]))
                        ),
                        ft.DataCell(
                            ft.TextButton(
                                "Bỏ",
                                on_click=(
                                    lambda e, pid=line["product_id"]:
                                    self.remove_line(pid)
                                ),
                            )
                        ),
                    ]
                )
                for line in self.lines
            ],
        )
        self.draft_holder.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def ask_confirm(self, e=None):
        if self.busy or self.confirm_pending:
            return

        if not self.lines:
            self.error.value = "Phiếu chưa có sản phẩm."
            self.refresh()
            return

        reason = (self.reason.value or "").strip()
        if not 1 <= len(reason) <= 255:
            self.error.value = (
                "Lý do kiểm kê phải có từ 1 đến 255 ký tự."
            )
            self.refresh()
            return

        self.confirm_pending = True
        state = {
            "choice": None,
            "handled": False,
        }

        def choose(choice):
            if state["choice"] is not None:
                return
            state["choice"] = choice
            self.page.pop_dialog()

        def dismissed(e):
            if state["handled"]:
                return
            state["handled"] = True
            self.confirm_pending = False

            if state["choice"] == "confirm":
                self.save()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Xác nhận điều chỉnh tồn"),
            content=ft.Text(
                f"Kiểm kê {len(self.lines)} sản phẩm. "
                "Chênh lệch thực tế sẽ được tính lại lúc lưu. "
                "Bạn xác nhận?"
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

    def save(self):
        if self.busy or not self.lines:
            return

        self.busy = True
        self.confirm_button.disabled = True

        try:
            result = self.service.create_adjustment(
                session_store=self.store,
                reason=(self.reason.value or "").strip(),
                items=[
                    {
                        "product_id": line["product_id"],
                        "actual_quantity": line["actual_quantity"],
                    }
                    for line in self.lines
                ],
            )
        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception(
                "Adjustment save returned unexpected failure"
            )
            self.success.value = ""
            self.error.value = (
                "Không xác định được kết quả. Kiểm tra lịch sử phiếu "
                "trước khi gửi lại để tránh điều chỉnh trùng."
            )
        else:
            self.lines.clear()
            self.reason.value = ""
            self.render_draft()
            self.error.value = ""

            if result["created"]:
                self.success.value = (
                    f"Đã lưu phiếu {result['code']}."
                )
            else:
                self.success.value = (
                    "Tồn thực tế không chênh lệch: "
                    "không tạo phiếu/movement."
                )

            try:
                self.history_offset = 0
                self.load_history(redraw=False)
                self.search_products(redraw=False)

                if result["created"]:
                    self.show_detail(
                        result["id"],
                        redraw=False,
                    )
            except Exception:
                logger.exception(
                    "Could not refresh adjustment history"
                )

            notify(self.page, self.success.value)
        finally:
            self.busy = False
            self.confirm_button.disabled = False
            self.refresh()

    def reload_history(self, e=None):
        self.history_offset = 0
        self.load_history()

    def load_history(self, *, redraw=True):
        try:
            rows = self.service.list_adjustments(
                session_store=self.store,
                limit=PAGE_SIZE + 1,
                offset=self.history_offset,
            )
            displayed = rows[:PAGE_SIZE]
            self.history_has_next = len(rows) > PAGE_SIZE
            self.history_prev.disabled = (
                self.history_offset == 0
            )
            self.history_next.disabled = (
                not self.history_has_next
            )
            self.history_page.value = (
                f"Trang {self.history_offset // PAGE_SIZE + 1}"
            )

            if not displayed:
                self.history_holder.controls = [
                    ft.Text("Chưa có phiếu.")
                ]
            else:
                table = ft.DataTable(
                    columns=[
                        ft.DataColumn(label=ft.Text(label))
                        for label in (
                            "Mã phiếu",
                            "Thời gian UTC",
                            "Người thực hiện",
                            "Lý do",
                            "Dòng thay đổi",
                            "Chi tiết",
                        )
                    ],
                    rows=[
                        ft.DataRow(
                            cells=[
                                ft.DataCell(
                                    ft.Text(str(row["code"]))
                                ),
                                ft.DataCell(
                                    ft.Text(str(row["created_at"]))
                                ),
                                ft.DataCell(
                                    ft.Text(
                                        str(row["created_by_name"])
                                    )
                                ),
                                ft.DataCell(
                                    ft.Text(str(row["reason"]))
                                ),
                                ft.DataCell(
                                    ft.Text(
                                        str(row["changed_items"])
                                    )
                                ),
                                ft.DataCell(
                                    ft.TextButton(
                                        "Xem",
                                        on_click=(
                                            lambda e, aid=row["id"]:
                                            self.show_detail(aid)
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
            logger.exception(
                "Cannot load adjustment history"
            )
            self.error.value = (
                "Không đọc được lịch sử kiểm kê."
            )

        if redraw:
            self.refresh()

    def previous_history(self, e=None):
        if self.history_offset >= PAGE_SIZE:
            self.history_offset -= PAGE_SIZE
            self.load_history()

    def next_history(self, e=None):
        if self.history_has_next:
            self.history_offset += PAGE_SIZE
            self.load_history()

    def show_detail(
        self,
        adjustment_id,
        *,
        redraw=True,
    ):
        try:
            result = self.service.get_adjustment(
                session_store=self.store,
                adjustment_id=int(adjustment_id),
            )
            header = result["adjustment"]
            lines = result["items"]

            table = ft.DataTable(
                columns=[
                    ft.DataColumn(label=ft.Text(label))
                    for label in (
                        "SKU",
                        "Sản phẩm",
                        "Tồn trước",
                        "Thực tế",
                        "Chênh lệch",
                        "Tồn sau",
                    )
                ],
                rows=[
                    ft.DataRow(
                        cells=[
                            ft.DataCell(
                                ft.Text(str(line["sku"]))
                            ),
                            ft.DataCell(
                                ft.Text(
                                    str(line["product_name"])
                                )
                            ),
                            ft.DataCell(
                                ft.Text(
                                    str(line["old_quantity"])
                                )
                            ),
                            ft.DataCell(
                                ft.Text(
                                    str(line["actual_quantity"])
                                )
                            ),
                            ft.DataCell(
                                ft.Text(
                                    f"{line['quantity_change']:+d}"
                                )
                            ),
                            ft.DataCell(
                                ft.Text(
                                    str(line["stock_after"])
                                )
                            ),
                        ]
                    )
                    for line in lines
                ],
            )

            self.detail_holder.controls = [
                ft.Divider(),
                ft.Text(
                    f"CHI TIẾT {header['code']}",
                    size=19,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f"Lý do: {header['reason']}"
                ),
                ft.Row(
                    scroll=ft.ScrollMode.AUTO,
                    controls=[table],
                ),
                ft.TextButton(
                    "Đóng",
                    on_click=self.close_detail,
                ),
            ]
            self.detail_holder.visible = True
        except AppError as exc:
            self.handle_error(exc)
            return
        except Exception:
            logger.exception(
                "Cannot load adjustment details"
            )
            self.error.value = (
                "Không xem được chi tiết phiếu."
            )

        if redraw:
            self.refresh()

    def close_detail(self, e=None):
        self.detail_holder.visible = False
        self.refresh()


def build_stock_adjustment_page(page: ft.Page) -> ft.Column:
    panel = StockAdjustmentPanel(
        page,
        products=ProductManagementService(),
        service=StockAdjustmentService(),
    )
    panel.load(redraw=False)
    return panel.root
