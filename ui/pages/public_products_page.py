
"""Task 45 / US08-T03: public home and product listing for Flet Web."""

import logging
from typing import Any

import flet as ft

from models.app_error import AppError
from services.catalog_service import CatalogService
from services.product_management_service import ProductManagementService
from ui.components.money_format import format_vnd

logger = logging.getLogger(__name__)

PAGE_SIZE = 12
HOME_SIZE = 6


class PublicProductsPanel:
    """Read-only product browsing. No stock, cost or admin actions."""

    def __init__(
        self,
        page: ft.Page,
        *,
        products: ProductManagementService,
        catalog: CatalogService,
        home: bool = False,
    ) -> None:
        self.page = page
        self.products = products
        self.catalog = catalog
        self.home = home

        self.offset = 0
        self.total = 0
        self.loading = False
        self.items: list[dict[str, Any]] = []

        self.error = ft.Text(color=ft.Colors.RED_700)
        self.counter = ft.Text()
        self.page_label = ft.Text()
        self.cards = ft.Row(
            wrap=True,
            spacing=12,
            run_spacing=12,
        )

        self.keyword = ft.TextField(
            label="Tìm tên điện thoại, SKU hoặc hãng",
            width=300,
            on_submit=self.apply_filters,
        )

        self.brand = ft.Dropdown(
            label="Hãng",
            width=200,
            value="ALL",
            options=[
                ft.DropdownOption(
                    key="ALL",
                    text="Tất cả hãng",
                )
            ],
        )

        self.min_price = ft.TextField(
            label="Giá từ (VND)",
            width=160,
        )
        self.max_price = ft.TextField(
            label="Giá đến (VND)",
            width=160,
        )

        self.only_in_stock = ft.Checkbox(
            label="Chỉ sản phẩm còn hàng",
            value=False,
        )

        self.sort = ft.Dropdown(
            label="Sắp xếp",
            width=190,
            value="newest",
            options=[
                ft.DropdownOption(
                    key="newest", text="Mới nhất"
                ),
                ft.DropdownOption(
                    key="price_asc", text="Giá tăng dần"
                ),
                ft.DropdownOption(
                    key="price_desc", text="Giá giảm dần"
                ),
                ft.DropdownOption(
                    key="name_asc", text="Tên A-Z"
                ),
            ],
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

        if self.home:
            self.root = self.build_home()
        else:
            self.root = self.build_listing()

    @property
    def page_size(self) -> int:
        return HOME_SIZE if self.home else PAGE_SIZE

    def refresh(self) -> None:
        self.page.update()

    def build_home(self) -> ft.Column:
        hero = ft.Container(
            bgcolor=ft.Colors.BLUE_50,
            border_radius=14,
            padding=24,
            content=ft.Column(
                spacing=10,
                controls=[
                    ft.Text(
                        "PHONE SHOP",
                        size=30,
                        weight=ft.FontWeight.BOLD,
                    ),
                    ft.Text(
                        "Khám phá điện thoại phù hợp với bạn",
                        size=20,
                    ),
                    ft.Text(
                        "Xem giá bán, chọn hãng và tìm sản phẩm "
                        "theo nhu cầu của bạn."
                    ),
                    ft.Button(
                        "Khám phá tất cả sản phẩm",
                        on_click=self.open_products,
                    ),
                ],
            ),
        )

        return ft.Column(
            spacing=16,
            controls=[
                hero,
                ft.Text(
                    "SẢN PHẨM MỚI",
                    size=22,
                    weight=ft.FontWeight.BOLD,
                ),
                self.error,
                self.counter,
                self.cards,
                ft.Button(
                    "Xem tất cả sản phẩm",
                    on_click=self.open_products,
                ),
            ],
        )

    def build_listing(self) -> ft.Column:
        return ft.Column(
            spacing=14,
            controls=[
                ft.Text(
                    "DANH SÁCH ĐIỆN THOẠI",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Tìm kiếm và so sánh sản phẩm đang kinh doanh."
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        self.keyword,
                        self.brand,
                        self.min_price,
                        self.max_price,
                    ],
                ),
                ft.Row(
                    wrap=True,
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        self.only_in_stock,
                        self.sort,
                        ft.Button(
                            "Tìm kiếm",
                            on_click=self.apply_filters,
                        ),
                        ft.TextButton(
                            "Xóa bộ lọc",
                            on_click=self.reset_filters,
                        ),
                    ],
                ),
                self.error,
                self.counter,
                self.cards,
                ft.Row(
                    wrap=True,
                    spacing=12,
                    controls=[
                        self.previous_button,
                        self.page_label,
                        self.next_button,
                    ],
                ),
            ],
        )

    def open_products(self, e=None) -> None:
        self.page.navigate("/products")

    def load(self) -> None:
        """Load data before the panel is attached to the View."""
        if not self.home:
            try:
                brands = self.catalog.list_brands(
                    limit=100,
                    offset=0,
                )
                self.brand.options = [
                    ft.DropdownOption(
                        key="ALL",
                        text="Tất cả hãng",
                    ),
                    *[
                        ft.DropdownOption(
                            key=str(row["id"]),
                            text=str(row["name"]),
                        )
                        for row in brands
                    ],
                ]
            except AppError as exc:
                self.show_error(exc.message)
                return
            except Exception:
                logger.exception("Cannot load public brands")
                self.show_error(
                    "Không thể tải danh sách hãng."
                )
                return

        self.search(redraw=False)

    def show_error(self, message: str) -> None:
        self.error.value = message
        self.items = []
        self.total = 0
        self.cards.controls = []
        self.counter.value = ""
        self.page_label.value = ""
        self.previous_button.disabled = True
        self.next_button.disabled = True

    def apply_filters(self, e=None) -> None:
        self.offset = 0
        self.search()

    def reset_filters(self, e=None) -> None:
        self.keyword.value = ""
        self.brand.value = "ALL"
        self.min_price.value = ""
        self.max_price.value = ""
        self.only_in_stock.value = False
        self.sort.value = "newest"

        self.offset = 0
        self.search()

    def search(self, *, redraw: bool = True) -> None:
        if self.loading:
            return

        self.loading = True

        try:
            if self.home:
                result = self.products.search_public(
                    sort_by="newest",
                    limit=HOME_SIZE,
                    offset=0,
                )
            else:
                selected_brand = self.brand.value
                brand_id = (
                    None
                    if selected_brand in (None, "", "ALL")
                    else int(selected_brand)
                )

                result = self.products.search_public(
                    keyword=self.keyword.value or None,
                    brand_id=brand_id,
                    min_price=(
                        (self.min_price.value or "").strip()
                        or None
                    ),
                    max_price=(
                        (self.max_price.value or "").strip()
                        or None
                    ),
                    only_in_stock=bool(
                        self.only_in_stock.value
                    ),
                    sort_by=self.sort.value or "newest",
                    limit=PAGE_SIZE,
                    offset=self.offset,
                )

            self.items = list(result["items"])
            self.total = int(result["total"])
            self.error.value = ""

            if self.home:
                self.counter.value = (
                    "Khám phá các sản phẩm mới nhất "
                    "tại Phone Shop."
                )
            else:
                self.counter.value = (
                    f"Tìm thấy {self.total} sản phẩm"
                )

            self.render_cards()

            if not self.home:
                pages = max(
                    1,
                    (
                        self.total + PAGE_SIZE - 1
                    ) // PAGE_SIZE,
                )
                current = self.offset // PAGE_SIZE + 1
                self.page_label.value = (
                    f"Trang {current}/{pages}"
                )
                self.previous_button.disabled = (
                    self.offset == 0
                )
                self.next_button.disabled = (
                    self.offset + PAGE_SIZE >= self.total
                )

        except AppError as exc:
            self.show_error(exc.message)
        except (TypeError, ValueError):
            self.show_error(
                "Bộ lọc không hợp lệ. "
                "Vui lòng kiểm tra lại dữ liệu."
            )
        except Exception:
            logger.exception(
                "Cannot load public products"
            )
            self.show_error(
                "Không tải được danh sách sản phẩm."
            )
        finally:
            self.loading = False
            if redraw:
                self.refresh()

    def previous_page(self, e=None) -> None:
        if (
            not self.home
            and self.offset >= PAGE_SIZE
        ):
            self.offset -= PAGE_SIZE
            self.search()

    def next_page(self, e=None) -> None:
        if (
            not self.home
            and self.offset + PAGE_SIZE < self.total
        ):
            self.offset += PAGE_SIZE
            self.search()

    @staticmethod
    def make_card(row: dict[str, Any]) -> ft.Card:
        """Render only fields allowed in public product responses."""
        image_url = row.get("image_url")

        if image_url:
            picture = ft.Image(
                src=str(image_url),
                width=210,
                height=140,
                fit=ft.BoxFit.CONTAIN,
                error_content=ft.Text(
                    "Không tải được ảnh"
                ),
            )
        else:
            picture = ft.Container(
                width=210,
                height=140,
                bgcolor=ft.Colors.BLUE_GREY_50,
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "📱",
                            size=54,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            "Chưa có ảnh",
                            size=12,
                        ),
                    ],
                ),
            )

        available = bool(row.get("in_stock"))

        availability = (
            "Còn hàng"
            if available
            else "Tạm hết hàng"
        )

        availability_color = (
            ft.Colors.GREEN_700
            if available
            else ft.Colors.RED_700
        )

        return ft.Card(
            content=ft.Container(
                width=260,
                padding=14,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        picture,
                        ft.Text(
                            str(row["name"]),
                            size=17,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            f"Hãng: {row['brand_name']}"
                        ),
                        ft.Text(
                            f"{row['storage']} | {row['color']}"
                        ),
                        ft.Text(
                            format_vnd(row["sell_price"]),
                            size=19,
                            color=ft.Colors.BLUE_700,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            availability,
                            color=availability_color,
                        ),
                    ],
                ),
            )
        )

    def render_cards(self) -> None:
        if not self.items:
            self.cards.controls = [
                ft.Text(
                    "Không có sản phẩm phù hợp."
                )
            ]
            return

        self.cards.controls = [
            self.make_card(row)
            for row in self.items
        ]


def build_public_home_page(page: ft.Page) -> ft.Column:
    panel = PublicProductsPanel(
        page,
        products=ProductManagementService(),
        catalog=CatalogService(),
        home=True,
    )
    panel.load()
    return panel.root


def build_public_products_page(page: ft.Page) -> ft.Column:
    panel = PublicProductsPanel(
        page,
        products=ProductManagementService(),
        catalog=CatalogService(),
    )
    panel.load()
    return panel.root
