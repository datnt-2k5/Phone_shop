
"""US05 Task 30: Admin/Super Admin product management UI."""

import logging
from typing import Any

import flet as ft

from models.app_error import AppError
from services.product_create_service import ProductCreateService
from services.product_edit_service import ProductEditService
from services.product_management_service import ProductManagementService
from ui.components.money_format import format_vnd
from ui.components.notifications import notify

logger = logging.getLogger(__name__)
PAGE_SIZE = 10


class ProductManagementPanel:
    """Stateful panel; every operation goes through an authorized Service."""

    def __init__(
        self,
        page: ft.Page,
        *,
        management_service: ProductManagementService,
        create_service: ProductCreateService,
        edit_service: ProductEditService,
    ) -> None:
        self.page = page
        self.management = management_service
        self.creator = create_service
        self.editor = edit_service

        self.brands: list[dict[str, Any]] = []
        self.offset = 0
        self.total = 0
        self.editing_id: int | None = None
        self.busy = False

        self.message = ft.Text(color=ft.Colors.RED_700)
        self.count_text = ft.Text()
        self.page_text = ft.Text()
        self.table_area = ft.Column()
        self.details = ft.Column(visible=False)

        # Search controls.
        self.keyword = ft.TextField(
            label="Tìm SKU, tên sản phẩm, hãng",
            width=270,
            on_submit=self.apply_filters,
        )
        self.brand_filter = ft.Dropdown(
            label="Hãng",
            width=200,
            value="ALL",
            options=[
                ft.DropdownOption(key="ALL", text="Tất cả hãng")
            ],
        )
        self.status_filter = ft.Dropdown(
            label="Trạng thái",
            width=190,
            value="ALL",
            options=[
                ft.DropdownOption(key="ALL", text="Tất cả"),
                ft.DropdownOption(key="ACTIVE", text="Đang bán"),
                ft.DropdownOption(
                    key="DISCONTINUED",
                    text="Ngừng bán",
                ),
            ],
        )
        self.sort_filter = ft.Dropdown(
            label="Sắp xếp",
            width=190,
            value="newest",
            options=[
                ft.DropdownOption(key="newest", text="Mới nhất"),
                ft.DropdownOption(
                    key="price_asc", text="Giá tăng dần"
                ),
                ft.DropdownOption(
                    key="price_desc", text="Giá giảm dần"
                ),
                ft.DropdownOption(key="name_asc", text="Tên A-Z"),
            ],
        )
        self.low_stock_filter = ft.Checkbox(
            label="Chỉ xem tồn thấp",
            value=False,
        )
        self.previous_button = ft.Button(
            "Trang trước", on_click=self.previous_page
        )
        self.next_button = ft.Button(
            "Trang sau", on_click=self.next_page
        )

        # Product form.
        self.form_title = ft.Text(
            size=21,
            weight=ft.FontWeight.BOLD,
        )
        self.form_error = ft.Text(color=ft.Colors.RED_700)
        self.sku = ft.TextField(label="SKU *", width=200)
        self.name = ft.TextField(
            label="Tên sản phẩm *", width=300
        )
        self.brand = ft.Dropdown(
            label="Hãng *", width=220, options=[]
        )
        self.storage = ft.TextField(
            label="Dung lượng *", width=160
        )
        self.color = ft.TextField(
            label="Màu sắc *", width=160
        )
        self.price = ft.TextField(
            label="Giá bán (VND) *", width=210
        )
        self.minimum = ft.TextField(
            label="Ngưỡng tồn thấp",
            width=190,
            value="0",
        )
        self.image_url = ft.TextField(
            label="URL hoặc đường dẫn ảnh",
            width=350,
        )
        self.description = ft.TextField(
            label="Mô tả",
            multiline=True,
            min_lines=2,
            width=450,
        )
        self.save_button = ft.Button(
            "Lưu sản phẩm",
            on_click=self.save_form,
        )

        self.form = ft.Column(
            visible=False,
            spacing=12,
            controls=[
                ft.Divider(),
                self.form_title,
                ft.Row(
                    wrap=True,
                    spacing=12,
                    run_spacing=12,
                    controls=[
                        self.sku,
                        self.name,
                        self.brand,
                        self.storage,
                        self.color,
                        self.price,
                        self.minimum,
                        self.image_url,
                    ],
                ),
                self.description,
                ft.Text(
                    "Tồn kho và giá vốn không được sửa tại đây. "
                    "Ảnh ở Task này chỉ dùng đường dẫn có sẵn.",
                    color=ft.Colors.BLUE_GREY_700,
                ),
                self.form_error,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.save_button,
                        ft.TextButton(
                            "Hủy",
                            on_click=self.close_form,
                        ),
                    ],
                ),
            ],
        )

        self.root = ft.Column(
            spacing=14,
            controls=[
                ft.Text(
                    "QUẢN LÝ SẢN PHẨM",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.Button(
                            "Thêm sản phẩm",
                            on_click=self.open_create,
                        ),
                        ft.Button(
                            "Làm mới",
                            on_click=self.reload,
                        ),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        self.keyword,
                        self.brand_filter,
                        self.status_filter,
                        self.sort_filter,
                        self.low_stock_filter,
                        ft.Button(
                            "Tìm kiếm",
                            on_click=self.apply_filters,
                        ),
                    ],
                ),
                self.message,
                self.count_text,
                self.table_area,
                ft.Row(
                    wrap=True,
                    controls=[
                        self.previous_button,
                        self.page_text,
                        self.next_button,
                    ],
                ),
                self.details,
                self.form,
            ],
        )

    @property
    def session_store(self):
        return self.page.session.store

    def refresh(self) -> None:
        self.page.update()

    def handle_error(self, exc: AppError) -> None:
        description = exc.message
        if exc.errors:
            description += " " + "; ".join(
                str(value)
                for value in exc.errors.values()
            )

        self.message.value = description
        self.form_error.value = description

        if exc.error_code in {"UNAUTHORIZED", "ACCOUNT_LOCKED"}:
            self.page.navigate("/login")
        else:
            self.refresh()

    def load_brands(self) -> None:
        self.brands = self.creator.list_brands(
            session_store=self.session_store,
        )
        options = [
            ft.DropdownOption(
                key=str(item["id"]),
                text=str(item["name"]),
            )
            for item in self.brands
        ]

        self.brand.options = options
        self.brand_filter.options = [
            ft.DropdownOption(key="ALL", text="Tất cả hãng"),
            *[
                ft.DropdownOption(
                    key=str(item["id"]),
                    text=str(item["name"]),
                )
                for item in self.brands
            ],
        ]

    def load(self) -> None:
        """Called before the panel is attached to a View."""
        try:
            self.load_brands()
            self.search(redraw=False)
        except AppError as exc:
            self.message.value = exc.message
            if exc.error_code in {"ACCOUNT_LOCKED", "UNAUTHORIZED"}:
                self.page.navigate("/login")
        except Exception:
            logger.exception("Cannot load product management page")
            self.message.value = "Không tải được trang sản phẩm."

    def reload(self, e=None) -> None:
        try:
            self.load_brands()
            self.search()
        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception("Cannot reload products")
            self.message.value = "Không thể làm mới dữ liệu."
            self.refresh()

    def apply_filters(self, e=None) -> None:
        self.offset = 0
        self.search()

    def search(self, e=None, *, redraw: bool = True) -> None:
        try:
            brand_id = (
                None
                if self.brand_filter.value in (None, "ALL")
                else int(self.brand_filter.value)
            )
            result = self.management.search_admin(
                session_store=self.session_store,
                keyword=self.keyword.value or None,
                brand_id=brand_id,
                status=self.status_filter.value or "ALL",
                low_stock=bool(self.low_stock_filter.value),
                sort_by=self.sort_filter.value or "newest",
                limit=PAGE_SIZE,
                offset=self.offset,
            )

            items = result["items"]
            self.total = int(result["total"])
            self.message.value = ""
            self.count_text.value = (
                f"Tìm thấy {self.total} sản phẩm"
            )
            self.render_table(items)

            last_page = max(
                1,
                (self.total + PAGE_SIZE - 1) // PAGE_SIZE,
            )
            self.page_text.value = (
                f"Trang {self.offset // PAGE_SIZE + 1}/{last_page}"
            )
            self.previous_button.disabled = self.offset == 0
            self.next_button.disabled = (
                self.offset + PAGE_SIZE >= self.total
            )
        except AppError as exc:
            self.handle_error(exc)
            return
        except (TypeError, ValueError):
            self.message.value = "Bộ lọc hãng không hợp lệ."
        except Exception:
            logger.exception("Cannot search products")
            self.message.value = "Không thể tìm kiếm sản phẩm."

        if redraw:
            self.refresh()

    def render_table(
        self,
        items: list[dict[str, Any]],
    ) -> None:
        if not items:
            self.table_area.controls = [
                ft.Text("Không có sản phẩm phù hợp.")
            ]
            return

        rows = []

        for item in items:
            status = str(item["status"])
            action_text = (
                "Ngừng bán"
                if status == "ACTIVE"
                else "Khôi phục"
            )

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(item["sku"]))),
                        ft.DataCell(ft.Text(str(item["name"]))),
                        ft.DataCell(ft.Text(str(item["brand_name"]))),
                        ft.DataCell(
                            ft.Text(format_vnd(item["sell_price"]))
                        ),
                        ft.DataCell(ft.Text(str(item["stock"]))),
                        ft.DataCell(
                            ft.Text(
                                "Tồn thấp"
                                if bool(item["is_low_stock"])
                                else "Bình thường"
                            )
                        ),
                        ft.DataCell(ft.Text(status)),
                        ft.DataCell(
                            ft.Row(
                                spacing=4,
                                controls=[
                                    ft.TextButton(
                                        "Chi tiết",
                                        on_click=(
                                            lambda e, p=item:
                                            self.show_detail(p)
                                        ),
                                    ),
                                    ft.TextButton(
                                        "Sửa",
                                        on_click=(
                                            lambda e, p=item:
                                            self.open_edit(p)
                                        ),
                                    ),
                                    ft.TextButton(
                                        action_text,
                                        on_click=(
                                            lambda e, p=item:
                                            self.ask_change_status(p)
                                        ),
                                    ),
                                ],
                            )
                        ),
                    ],
                )
            )

        table = ft.DataTable(
            columns=[
                ft.DataColumn(label=ft.Text("SKU")),
                ft.DataColumn(label=ft.Text("Tên")),
                ft.DataColumn(label=ft.Text("Hãng")),
                ft.DataColumn(label=ft.Text("Giá")),
                ft.DataColumn(label=ft.Text("Tồn")),
                ft.DataColumn(label=ft.Text("Cảnh báo")),
                ft.DataColumn(label=ft.Text("Trạng thái")),
                ft.DataColumn(label=ft.Text("Thao tác")),
            ],
            rows=rows,
        )

        self.table_area.controls = [
            ft.Row(
                scroll=ft.ScrollMode.AUTO,
                controls=[table],
            )
        ]

    def previous_page(self, e=None) -> None:
        if self.offset >= PAGE_SIZE:
            self.offset -= PAGE_SIZE
            self.search()

    def next_page(self, e=None) -> None:
        if self.offset + PAGE_SIZE < self.total:
            self.offset += PAGE_SIZE
            self.search()

    def show_detail(self, product: dict[str, Any]) -> None:
        lines = [
            f"SKU: {product['sku']}",
            f"Tên: {product['name']}",
            f"Hãng: {product['brand_name']}",
            f"Dung lượng: {product['storage']}",
            f"Màu: {product['color']}",
            f"Giá bán: {format_vnd(product['sell_price'])}",
            f"Giá vốn: {format_vnd(product['cost_price'])}",
            f"Tồn: {product['stock']}",
            f"Ngưỡng tồn: {product['min_stock']}",
            f"Trạng thái: {product['status']}",
            f"Mô tả: {product.get('description') or 'Chưa có'}",
            f"Ảnh: {product.get('image_url') or 'Chưa có'}",
        ]

        self.details.controls = [
            ft.Divider(),
            ft.Text(
                "CHI TIẾT SẢN PHẨM",
                size=20,
                weight=ft.FontWeight.BOLD,
            ),
            *[ft.Text(value) for value in lines],
            ft.TextButton(
                "Đóng chi tiết",
                on_click=self.close_detail,
            ),
        ]
        self.details.visible = True
        self.refresh()

    def close_detail(self, e=None) -> None:
        self.details.visible = False
        self.refresh()

    def show_form(self) -> None:
        self.form_error.value = ""
        self.details.visible = False
        self.form.visible = True
        self.refresh()

    def open_create(self, e=None) -> None:
        if not self.brands:
            self.message.value = (
                "Chưa có hãng trong database. "
                "Hãy bổ sung hãng ở US06 trước khi tạo sản phẩm."
            )
            self.refresh()
            return

        self.editing_id = None
        self.form_title.value = "THÊM SẢN PHẨM"
        self.sku.value = ""
        self.name.value = ""
        self.brand.value = None
        self.storage.value = ""
        self.color.value = ""
        self.price.value = ""
        self.minimum.value = "0"
        self.description.value = ""
        self.image_url.value = ""

        for field in (
            self.sku,
            self.brand,
            self.storage,
            self.color,
        ):
            field.disabled = False

        self.show_form()

    def open_edit(self, product: dict[str, Any]) -> None:
        self.editing_id = int(product["id"])
        self.form_title.value = "SỬA SẢN PHẨM"

        self.sku.value = str(product["sku"])
        self.name.value = str(product["name"])
        self.brand.value = str(product["brand_id"])
        self.storage.value = str(product["storage"])
        self.color.value = str(product["color"])
        self.price.value = str(product["sell_price"])
        self.minimum.value = str(product["min_stock"])
        self.description.value = product.get("description") or ""
        self.image_url.value = product.get("image_url") or ""

        # Edit only allowed fields from Task 28.
        for field in (
            self.sku,
            self.brand,
            self.storage,
            self.color,
        ):
            field.disabled = True

        self.show_form()

    def close_form(self, e=None) -> None:
        self.form.visible = False
        self.editing_id = None
        self.refresh()

    def save_form(self, e=None) -> None:
        """Create or update via Backend Services, never direct SQL."""
        if self.busy:
            return

        self.busy = True
        self.save_button.disabled = True

        try:
            try:
                minimum = int((self.minimum.value or "").strip())
            except ValueError:
                self.form_error.value = (
                    "Ngưỡng tồn phải là số nguyên không âm."
                )
                return

            values = {
                "session_store": self.session_store,
                "name": self.name.value or "",
                "description": self.description.value,
                "sell_price": self.price.value or "",
                "image_url": self.image_url.value,
                "min_stock": minimum,
            }

            if self.editing_id is None:
                try:
                    brand_id = int(self.brand.value or "")
                except ValueError:
                    self.form_error.value = "Bạn phải chọn hãng."
                    return

                created = self.creator.create(
                    **values,
                    sku=self.sku.value or "",
                    brand_id=brand_id,
                    storage=self.storage.value or "",
                    color=self.color.value or "",
                )
                message = (
                    f"Đã thêm sản phẩm {created['sku']}."
                )
            else:
                updated = self.editor.update_details(
                    **values,
                    product_id=self.editing_id,
                )
                message = (
                    f"Đã cập nhật sản phẩm {updated['sku']}."
                )

            self.form.visible = False
            self.editing_id = None
            self.offset = 0
            self.search(redraw=False)
            self.refresh()
            notify(self.page, message)

        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception("Cannot save product")
            self.form_error.value = (
                "Không thể lưu sản phẩm. Vui lòng thử lại."
            )
            self.refresh()
        finally:
            self.busy = False
            self.save_button.disabled = False
            self.refresh()

    def ask_change_status(
        self,
        product: dict[str, Any],
    ) -> None:
        """Confirm after the dialog finishes closing."""
        product_id = int(product["id"])
        new_status = (
            "DISCONTINUED"
            if product["status"] == "ACTIVE"
            else "ACTIVE"
        )
        action_label = (
            "ngừng bán"
            if new_status == "DISCONTINUED"
            else "khôi phục"
        )
        state = {"choice": None, "handled": False}

        def choose(choice: str) -> None:
            if state["choice"] is not None:
                return
            state["choice"] = choice
            self.page.pop_dialog()

        def dismissed(e) -> None:
            if state["handled"]:
                return
            state["handled"] = True
            if state["choice"] == "confirm":
                self.change_status(product_id, new_status)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Xác nhận trạng thái sản phẩm"),
            content=ft.Text(
                f"Bạn muốn {action_label} sản phẩm "
                f"{product['sku']}?"
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

    def change_status(
        self,
        product_id: int,
        status: str,
    ) -> None:
        if self.busy:
            return

        self.busy = True
        try:
            self.management.set_status(
                session_store=self.session_store,
                product_id=product_id,
                status=status,
            )
            self.search(redraw=False)
            self.refresh()
            notify(
                self.page,
                "Đã cập nhật trạng thái kinh doanh.",
            )
        except AppError as exc:
            self.handle_error(exc)
        except Exception:
            logger.exception("Cannot change product status")
            self.message.value = (
                "Không thể thay đổi trạng thái sản phẩm."
            )
            self.refresh()
        finally:
            self.busy = False


def build_product_management_page(page: ft.Page) -> ft.Column:
    """Factory used by main.py after the existing role guard."""
    panel = ProductManagementPanel(
        page,
        management_service=ProductManagementService(),
        create_service=ProductCreateService(),
        edit_service=ProductEditService(),
    )
    panel.load()
    return panel.root
