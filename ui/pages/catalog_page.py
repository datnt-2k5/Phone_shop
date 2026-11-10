
"""Task 35 / US06-T04: Flet UI for brands and suppliers."""

import logging
from datetime import datetime
from typing import Any

import flet as ft

from models.app_error import AppError
from services.catalog_service import CatalogService
from ui.components.notifications import notify

logger = logging.getLogger(__name__)
PAGE_SIZE = 20


class CatalogPanel:
    """Flet panel: all writes use CatalogService, not SQL/Repository."""

    def __init__(self, page: ft.Page, *, service: CatalogService) -> None:
        self.page = page
        self.service = service
        self.section = "brands"
        self.offset = 0
        self.has_next = False
        self.busy = False
        self.brand_id: int | None = None
        self.supplier_id: int | None = None

        self.message = ft.Text(color=ft.Colors.RED_700)
        self.counter = ft.Text()
        self.page_label = ft.Text()
        self.table_holder = ft.Column()
        self.detail_holder = ft.Column(visible=False)

        self.supplier_filter = ft.Dropdown(
            label="Trạng thái nhà cung cấp",
            value="ALL",
            width=240,
            visible=False,
            options=[
                ft.DropdownOption(key="ALL", text="Tất cả"),
                ft.DropdownOption(key="ACTIVE", text="Đang hợp tác"),
                ft.DropdownOption(key="INACTIVE", text="Ngừng hợp tác"),
            ],
        )

        self.brand_add_button = ft.Button(
            "Thêm hãng",
            on_click=self.open_brand_create,
        )
        self.supplier_add_button = ft.Button(
            "Thêm nhà cung cấp",
            on_click=self.open_supplier_create,
            visible=False,
        )

        self.previous_button = ft.Button(
            "Trang trước",
            on_click=self.previous_page,
            disabled=True,
        )
        self.next_button = ft.Button(
            "Trang sau",
            on_click=self.next_page,
            disabled=True,
        )

        # Form hãng.
        self.brand_name = ft.TextField(
            label="Tên hãng *",
            width=360,
        )
        self.brand_form_title = ft.Text(
            weight=ft.FontWeight.BOLD,
            size=20,
        )
        self.brand_error = ft.Text(color=ft.Colors.RED_700)
        self.brand_save_button = ft.Button(
            "Lưu hãng",
            on_click=self.save_brand,
        )

        self.brand_form = ft.Column(
            visible=False,
            controls=[
                ft.Divider(),
                self.brand_form_title,
                self.brand_name,
                self.brand_error,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.brand_save_button,
                        ft.TextButton(
                            "Hủy",
                            on_click=self.close_forms,
                        ),
                    ],
                ),
            ],
        )

        # Form nhà cung cấp.
        self.supplier_name = ft.TextField(
            label="Tên nhà cung cấp *",
            width=360,
        )
        self.supplier_phone = ft.TextField(
            label="Số điện thoại",
            width=200,
        )
        self.supplier_email = ft.TextField(
            label="Email",
            width=300,
        )
        self.supplier_address = ft.TextField(
            label="Địa chỉ",
            width=450,
            multiline=True,
            min_lines=2,
        )
        self.supplier_form_title = ft.Text(
            weight=ft.FontWeight.BOLD,
            size=20,
        )
        self.supplier_error = ft.Text(color=ft.Colors.RED_700)
        self.supplier_save_button = ft.Button(
            "Lưu nhà cung cấp",
            on_click=self.save_supplier,
        )

        self.supplier_form = ft.Column(
            visible=False,
            controls=[
                ft.Divider(),
                self.supplier_form_title,
                ft.Row(
                    wrap=True,
                    spacing=12,
                    run_spacing=12,
                    controls=[
                        self.supplier_name,
                        self.supplier_phone,
                        self.supplier_email,
                        self.supplier_address,
                    ],
                ),
                ft.Text(
                    "Ngừng hợp tác chỉ đổi trạng thái, "
                    "không xóa lịch sử.",
                    color=ft.Colors.BLUE_GREY_700,
                ),
                self.supplier_error,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.supplier_save_button,
                        ft.TextButton(
                            "Hủy",
                            on_click=self.close_forms,
                        ),
                    ],
                ),
            ],
        )

        # Trang chính.
        self.root = ft.Column(
            spacing=14,
            controls=[
                ft.Text(
                    "QUẢN LÝ HÃNG VÀ NHÀ CUNG CẤP",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.Button(
                            "Hãng",
                            on_click=self.show_brands,
                        ),
                        ft.Button(
                            "Nhà cung cấp",
                            on_click=self.show_suppliers,
                        ),
                        self.brand_add_button,
                        self.supplier_add_button,
                        ft.Button(
                            "Làm mới",
                            on_click=self.reload,
                        ),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    controls=[
                        self.supplier_filter,
                        ft.Button(
                            "Lọc",
                            on_click=self.apply_filter,
                        ),
                    ],
                ),
                self.message,
                self.counter,
                self.table_holder,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.previous_button,
                        self.page_label,
                        self.next_button,
                    ],
                ),
                self.detail_holder,
                self.brand_form,
                self.supplier_form,
            ],
        )

    @property
    def session_store(self):
        return self.page.session.store

    def refresh(self) -> None:
        self.page.update()

    def _hide_forms(self) -> None:
        self.brand_form.visible = False
        self.supplier_form.visible = False
        self.brand_id = None
        self.supplier_id = None

    def _handle_error(
        self,
        exc: AppError,
        *,
        redraw: bool = True,
    ) -> None:
        message = exc.message

        if exc.errors:
            message += ": " + "; ".join(
                str(detail)
                for detail in exc.errors.values()
            )

        if exc.error_code == "FORBIDDEN":
            message = "403 – " + message

        self.message.value = message
        self.brand_error.value = message
        self.supplier_error.value = message

        if exc.error_code in {
            "FORBIDDEN",
            "UNAUTHORIZED",
            "ACCOUNT_LOCKED",
        }:
            self.table_holder.controls = []
            self.detail_holder.visible = False
            self._hide_forms()

        if exc.error_code in {
            "UNAUTHORIZED",
            "ACCOUNT_LOCKED",
        }:
            self.page.navigate("/login")
        elif redraw:
            self.refresh()

    # ======================================================
    # CHUYỂN GIỮA HÃNG VÀ NHÀ CUNG CẤP
    # ======================================================

    def show_brands(self, e=None) -> None:
        self.section = "brands"
        self.offset = 0
        self.supplier_filter.visible = False
        self.brand_add_button.visible = True
        self.supplier_add_button.visible = False
        self.detail_holder.visible = False
        self._hide_forms()
        self.load()

    def show_suppliers(self, e=None) -> None:
        self.section = "suppliers"
        self.offset = 0
        self.supplier_filter.visible = True
        self.brand_add_button.visible = False
        self.supplier_add_button.visible = True
        self.detail_holder.visible = False
        self._hide_forms()
        self.load()

    def apply_filter(self, e=None) -> None:
        self.offset = 0
        self.load()

    def reload(self, e=None) -> None:
        self.load()

    def _supplier_active_filter(self) -> bool | None:
        value = self.supplier_filter.value or "ALL"

        if value == "ALL":
            return None
        if value == "ACTIVE":
            return True
        if value == "INACTIVE":
            return False

        raise AppError(
            "VALIDATION_ERROR",
            "Bộ lọc trạng thái không hợp lệ.",
        )

    # ======================================================
    # ĐỌC DANH SÁCH VÀ PHÂN TRANG
    # ======================================================

    def load(self, *, redraw: bool = True) -> None:
        """Read one server-side page plus one sentinel row."""

        try:
            if self.section == "brands":
                rows = self.service.list_brands(
                    limit=PAGE_SIZE + 1,
                    offset=self.offset,
                )
            else:
                rows = self.service.list_suppliers(
                    session_store=self.session_store,
                    is_active=self._supplier_active_filter(),
                    limit=PAGE_SIZE + 1,
                    offset=self.offset,
                )

            # Có thể mất dòng cuối khi ngừng hợp tác.
            if not rows and self.offset:
                self.offset = max(
                    0,
                    self.offset - PAGE_SIZE,
                )
                self.load(redraw=redraw)
                return

            self.has_next = len(rows) > PAGE_SIZE
            displayed = rows[:PAGE_SIZE]

            if self.section == "brands":
                self._render_brands(displayed)
                label = "hãng"
            else:
                self._render_suppliers(displayed)
                label = "nhà cung cấp"

            self.counter.value = (
                f"Hiển thị {len(displayed)} {label}"
            )
            self.page_label.value = (
                f"Trang {self.offset // PAGE_SIZE + 1}"
            )
            self.previous_button.disabled = self.offset == 0
            self.next_button.disabled = not self.has_next
            self.message.value = ""

        except AppError as exc:
            self._handle_error(exc, redraw=redraw)
            return
        except Exception:
            logger.exception("Could not load catalog")
            self.message.value = "Không thể tải danh mục."

        if redraw:
            self.refresh()

    @staticmethod
    def _format_date(value: object) -> str:
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y %H:%M")
        return str(value or "")

    def _render_brands(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            self.table_holder.controls = [
                ft.Text("Chưa có hãng.")
            ]
            return

        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID")),
                ft.DataColumn(label=ft.Text("Hãng")),
                ft.DataColumn(label=ft.Text("Ngày tạo")),
                ft.DataColumn(label=ft.Text("Thao tác")),
            ],
            rows=[
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Text(str(item["id"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(item["name"]))
                        ),
                        ft.DataCell(
                            ft.Text(
                                self._format_date(
                                    item.get("created_at")
                                )
                            )
                        ),
                        ft.DataCell(
                            ft.TextButton(
                                "Sửa",
                                on_click=(
                                    lambda e, row=item:
                                    self.open_brand_edit(row)
                                ),
                            )
                        ),
                    ],
                )
                for item in rows
            ],
        )

        self.table_holder.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def _render_suppliers(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            self.table_holder.controls = [
                ft.Text(
                    "Không có nhà cung cấp phù hợp."
                )
            ]
            return

        table_rows = []

        for item in rows:
            active = bool(item["is_active"])

            actions = [
                ft.TextButton(
                    "Chi tiết",
                    on_click=(
                        lambda e, row=item:
                        self.show_supplier_detail(row)
                    ),
                ),
                ft.TextButton(
                    "Sửa",
                    on_click=(
                        lambda e, row=item:
                        self.open_supplier_edit(row)
                    ),
                ),
            ]

            if active:
                actions.append(
                    ft.TextButton(
                        "Ngừng hợp tác",
                        on_click=(
                            lambda e, row=item:
                            self.ask_discontinue(row)
                        ),
                    )
                )

            table_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(
                            ft.Text(str(item["id"]))
                        ),
                        ft.DataCell(
                            ft.Text(str(item["name"]))
                        ),
                        ft.DataCell(
                            ft.Text(
                                item.get("phone") or "—"
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                item.get("email") or "—"
                            )
                        ),
                        ft.DataCell(
                            ft.Text(
                                "Đang hợp tác"
                                if active
                                else "Ngừng hợp tác"
                            )
                        ),
                        ft.DataCell(
                            ft.Row(
                                controls=actions,
                                spacing=4,
                            )
                        ),
                    ],
                )
            )

        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("ID")),
                ft.DataColumn(label=ft.Text("Nhà cung cấp")),
                ft.DataColumn(label=ft.Text("Điện thoại")),
                ft.DataColumn(label=ft.Text("Email")),
                ft.DataColumn(label=ft.Text("Trạng thái")),
                ft.DataColumn(label=ft.Text("Thao tác")),
            ],
            rows=table_rows,
        )

        self.table_holder.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def previous_page(self, e=None) -> None:
        if self.offset >= PAGE_SIZE:
            self.offset -= PAGE_SIZE
            self.load()

    def next_page(self, e=None) -> None:
        if self.has_next:
            self.offset += PAGE_SIZE
            self.load()

    # ======================================================
    # THÊM VÀ SỬA HÃNG
    # ======================================================

    def open_brand_create(self, e=None) -> None:
        self._hide_forms()
        self.brand_id = None
        self.brand_name.value = ""
        self.brand_error.value = ""
        self.brand_form_title.value = "THÊM HÃNG"
        self.brand_form.visible = True
        self.detail_holder.visible = False
        self.refresh()

    def open_brand_edit(
        self,
        item: dict[str, Any],
    ) -> None:
        self._hide_forms()
        self.brand_id = int(item["id"])
        self.brand_name.value = str(item["name"])
        self.brand_error.value = ""
        self.brand_form_title.value = "SỬA TÊN HÃNG"
        self.brand_form.visible = True
        self.detail_holder.visible = False
        self.refresh()

    def save_brand(self, e=None) -> None:
        if self.busy:
            return

        self.busy = True
        self.brand_save_button.disabled = True

        try:
            self.service.save_brand(
                session_store=self.session_store,
                brand_id=self.brand_id,
                name=self.brand_name.value or "",
            )

            self._hide_forms()
            self.offset = 0
            self.load(redraw=False)
            self.refresh()

            notify(
                self.page,
                "Đã lưu hãng thành công.",
            )

        except AppError as exc:
            self._handle_error(exc)
        except Exception:
            logger.exception("Could not save brand")
            self.brand_error.value = "Không thể lưu hãng."
            self.refresh()
        finally:
            self.busy = False
            self.brand_save_button.disabled = False
            self.refresh()

    # ======================================================
    # THÊM VÀ SỬA NHÀ CUNG CẤP
    # ======================================================

    def open_supplier_create(self, e=None) -> None:
        self._hide_forms()
        self.supplier_id = None
        self.supplier_name.value = ""
        self.supplier_phone.value = ""
        self.supplier_email.value = ""
        self.supplier_address.value = ""
        self.supplier_error.value = ""
        self.supplier_form_title.value = (
            "THÊM NHÀ CUNG CẤP"
        )
        self.supplier_form.visible = True
        self.detail_holder.visible = False
        self.refresh()

    def open_supplier_edit(
        self,
        item: dict[str, Any],
    ) -> None:
        self._hide_forms()
        self.supplier_id = int(item["id"])
        self.supplier_name.value = str(item["name"])
        self.supplier_phone.value = (
            item.get("phone") or ""
        )
        self.supplier_email.value = (
            item.get("email") or ""
        )
        self.supplier_address.value = (
            item.get("address") or ""
        )
        self.supplier_error.value = ""
        self.supplier_form_title.value = (
            "SỬA NHÀ CUNG CẤP"
        )
        self.supplier_form.visible = True
        self.detail_holder.visible = False
        self.refresh()

    def save_supplier(self, e=None) -> None:
        if self.busy:
            return

        self.busy = True
        self.supplier_save_button.disabled = True

        try:
            self.service.save_supplier(
                session_store=self.session_store,
                supplier_id=self.supplier_id,
                name=self.supplier_name.value or "",
                phone=self.supplier_phone.value or None,
                email=self.supplier_email.value or None,
                address=self.supplier_address.value or None,
            )

            self._hide_forms()
            self.offset = 0
            self.load(redraw=False)
            self.refresh()

            notify(
                self.page,
                "Đã lưu nhà cung cấp thành công.",
            )

        except AppError as exc:
            self._handle_error(exc)
        except Exception:
            logger.exception("Could not save supplier")
            self.supplier_error.value = (
                "Không thể lưu nhà cung cấp."
            )
            self.refresh()
        finally:
            self.busy = False
            self.supplier_save_button.disabled = False
            self.refresh()

    def close_forms(self, e=None) -> None:
        self._hide_forms()
        self.refresh()

    # ======================================================
    # CHI TIẾT NHÀ CUNG CẤP
    # ======================================================

    def show_supplier_detail(
        self,
        item: dict[str, Any],
    ) -> None:
        self._hide_forms()

        lines = [
            f"ID: {item['id']}",
            f"Tên: {item['name']}",
            f"Điện thoại: {item.get('phone') or 'Chưa có'}",
            f"Email: {item.get('email') or 'Chưa có'}",
            f"Địa chỉ: {item.get('address') or 'Chưa có'}",
            "Trạng thái: " + (
                "Đang hợp tác"
                if bool(item["is_active"])
                else "Ngừng hợp tác"
            ),
        ]

        self.detail_holder.controls = [
            ft.Divider(),
            ft.Text(
                "CHI TIẾT NHÀ CUNG CẤP",
                weight=ft.FontWeight.BOLD,
            ),
            *[ft.Text(line) for line in lines],
            ft.TextButton(
                "Đóng chi tiết",
                on_click=self.close_detail,
            ),
        ]

        self.detail_holder.visible = True
        self.refresh()

    def close_detail(self, e=None) -> None:
        self.detail_holder.visible = False
        self.refresh()

    # ======================================================
    # NGỪNG HỢP TÁC – CÓ HỘP THOẠI XÁC NHẬN
    # ======================================================

    def ask_discontinue(
        self,
        item: dict[str, Any],
    ) -> None:
        if not bool(item["is_active"]):
            return

        supplier_id = int(item["id"])

        state = {
            "answer": None,
            "handled": False,
        }

        def choose(answer: str) -> None:
            if state["answer"] is not None:
                return
            state["answer"] = answer
            self.page.pop_dialog()

        def on_dismiss(e) -> None:
            if state["handled"]:
                return

            state["handled"] = True

            if state["answer"] == "confirm":
                self.discontinue_supplier(
                    supplier_id
                )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Xác nhận ngừng hợp tác"
            ),
            content=ft.Text(
                f"Ngừng hợp tác với {item['name']}? "
                "Thông tin và phiếu nhập cũ "
                "vẫn được giữ nguyên."
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
            on_dismiss=on_dismiss,
        )

        self.page.show_dialog(dialog)

    def discontinue_supplier(
        self,
        supplier_id: int,
    ) -> None:
        if self.busy:
            return

        self.busy = True

        try:
            self.service.discontinue_supplier(
                session_store=self.session_store,
                supplier_id=supplier_id,
            )

            self.detail_holder.visible = False
            self.load(redraw=False)
            self.refresh()

            notify(
                self.page,
                "Đã ngừng hợp tác nhà cung cấp.",
            )

        except AppError as exc:
            self._handle_error(exc)
        except Exception:
            logger.exception(
                "Could not deactivate supplier"
            )
            self.message.value = (
                "Không thể ngừng hợp tác nhà cung cấp."
            )
            self.refresh()
        finally:
            self.busy = False


def build_catalog_page(page: ft.Page) -> ft.Column:
    """Tạo trang sau khi Route Guard kiểm tra quyền."""
    panel = CatalogPanel(
        page,
        service=CatalogService(),
    )

    # Đọc dữ liệu trước khi gắn control vào View.
    panel.load(redraw=False)

    return panel.root
