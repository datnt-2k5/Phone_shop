
"""Task 46 / US08-T04: read-only public product detail page."""

import logging
from typing import Any

import flet as ft

from models.app_error import AppError
from services.product_management_service import ProductManagementService
from ui.components.money_format import format_vnd

logger = logging.getLogger(__name__)


class PublicProductDetailPanel:
    """Display one ACTIVE product using the public Service only."""

    def __init__(
        self,
        page: ft.Page,
        *,
        product_id: int,
        products: ProductManagementService,
    ) -> None:
        self.page = page
        self.product_id = product_id
        self.products = products

        self.message = ft.Text(color=ft.Colors.RED_700)
        self.content = ft.Column(spacing=14)

        self.back_button = ft.Button(
            "Quay lại danh sách",
            on_click=self.back_to_products,
        )

        self.root = ft.Column(
            spacing=16,
            controls=[
                ft.Text(
                    "CHI TIẾT SẢN PHẨM",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                self.back_button,
                self.message,
                self.content,
            ],
        )

    def back_to_products(self, e=None) -> None:
        self.page.navigate("/products")

    @staticmethod
    def product_view(
        row: dict[str, Any],
    ) -> ft.Row:
        """Render only customer-safe fields."""

        image_url = row.get("image_url")

        if image_url:
            picture = ft.Image(
                src=str(image_url),
                width=320,
                height=260,
                fit=ft.BoxFit.CONTAIN,
                error_content=ft.Text(
                    "Không tải được ảnh sản phẩm"
                ),
            )
        else:
            picture = ft.Container(
                width=320,
                height=260,
                bgcolor=ft.Colors.BLUE_GREY_50,
                border_radius=12,
                alignment=ft.Alignment.CENTER,
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("📱", size=64),
                        ft.Text("Chưa có ảnh"),
                    ],
                ),
            )

        available = bool(row.get("in_stock"))

        stock_label = (
            "Còn hàng"
            if available
            else "Tạm hết hàng"
        )
        stock_color = (
            ft.Colors.GREEN_700
            if available
            else ft.Colors.RED_700
        )

        details = ft.Column(
            spacing=12,
            controls=[
                ft.Text(
                    str(row["name"]),
                    size=27,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    f"Mã sản phẩm: {row['sku']}"
                ),
                ft.Text(
                    f"Hãng: {row['brand_name']}"
                ),
                ft.Text(
                    f"Dung lượng: {row.get('storage') or 'Chưa cập nhật'}"
                ),
                ft.Text(
                    f"Màu sắc: {row.get('color') or 'Chưa cập nhật'}"
                ),
                ft.Text(
                    format_vnd(row["sell_price"]),
                    size=25,
                    color=ft.Colors.BLUE_700,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    stock_label,
                    color=stock_color,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Divider(),
                ft.Text(
                    "MÔ TẢ SẢN PHẨM",
                    size=17,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    str(
                        row.get("description")
                        or "Chưa có mô tả sản phẩm."
                    )
                ),
                ft.Text(
                    "Thông tin tồn kho hiển thị chỉ ở mức "
                    "còn hàng hoặc tạm hết hàng."
                ),
            ],
        )

        return ft.Row(
            wrap=True,
            spacing=24,
            run_spacing=18,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                picture,
                ft.Container(
                    width=440,
                    content=details,
                ),
            ],
        )

    def load(self, *, redraw: bool = False) -> None:
        """Fetch detail before attaching the control to its View."""
        self.message.value = ""
        self.content.controls = []

        try:
            product = self.products.get_public_detail(
                product_id=self.product_id,
            )

            self.content.controls = [
                self.product_view(product)
            ]

        except AppError as exc:
            if exc.error_code == "NOT_FOUND":
                self.message.value = (
                    "404 – Sản phẩm không tồn tại "
                    "hoặc đã ngừng kinh doanh."
                )
            elif exc.error_code == "VALIDATION_ERROR":
                self.message.value = (
                    "ID sản phẩm không hợp lệ."
                )
            else:
                logger.warning(
                    "Public product detail business error: %s",
                    exc.error_code,
                )
                self.message.value = (
                    "Không thể tải chi tiết sản phẩm."
                )

        except Exception:
            logger.exception(
                "Failed to load public product detail"
            )
            self.message.value = (
                "Không thể tải chi tiết sản phẩm."
            )

        if redraw:
            self.page.update()


def build_public_product_detail_page(
    page: ft.Page,
    *,
    product_id: int,
) -> ft.Column:
    panel = PublicProductDetailPanel(
        page,
        product_id=product_id,
        products=ProductManagementService(),
    )

    panel.load(redraw=False)
    return panel.root
