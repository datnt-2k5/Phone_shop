
"""Task 48 / US09-T01: customer cart page in Flet."""

import logging
from collections.abc import Callable
from decimal import Decimal

import flet as ft

from models.app_error import AppError
from services.cart_session import CartSession
from services.product_management_service import ProductManagementService
from ui.components.money_format import format_vnd

logger = logging.getLogger(__name__)


class CartPanel:
    """View and edit cart items stored in the current Flet session."""

    def __init__(
        self,
        page: ft.Page,
        *,
        cart: CartSession,
        products: ProductManagementService,
        authorize: Callable[[], None],
    ) -> None:
        self.page = page
        self.cart = cart
        self.products = products
        self.authorize = authorize

        self.total = Decimal(0)
        self.error = ft.Text(color=ft.Colors.RED_700)
        self.counter = ft.Text()
        self.total_text = ft.Text(
            size=22,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_700,
        )
        self.note = ft.Text()
        self.rows = ft.Column(spacing=12)

        self.root = ft.Column(
            spacing=16,
            controls=[
                ft.Text(
                    "GIỎ HÀNG CỦA BẠN",
                    size=26,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Tối đa 20 sản phẩm khác nhau. "
                    "Số lượng mỗi sản phẩm phải từ 1 trở lên."
                ),
                self.error,
                self.counter,
                self.rows,
                ft.Divider(),
                self.total_text,
                self.note,
                ft.Row(
                    wrap=True,
                    spacing=10,
                    controls=[
                        ft.Button(
                            "Tiếp tục mua sắm",
                            on_click=self.continue_shopping,
                        ),
                        ft.TextButton(
                            "Xóa toàn bộ giỏ hàng",
                            on_click=self.clear_cart,
                        ),
                    ],
                ),
            ],
        )

    def continue_shopping(self, e=None) -> None:
        self.page.navigate("/products")

    def _product_card(
        self,
        row: dict,
        product: dict,
    ) -> ft.Card:
        product_id = row["product_id"]
        quantity = row["quantity"]

        price = product["sell_price"]

        if type(price) not in (Decimal, str, int):
            raise ValueError("Invalid product price")

        unit_price = Decimal(price)

        if not unit_price.is_finite() or unit_price <= 0:
            raise ValueError("Invalid product price")

        line_total = unit_price * quantity
        self.total += line_total

        quantity_field = ft.TextField(
            label="Số lượng",
            value=str(quantity),
            width=110,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        stock_label = (
            "Còn hàng"
            if product["in_stock"]
            else "Tạm hết hàng"
        )

        return ft.Card(
            content=ft.Container(
                padding=14,
                content=ft.Row(
                    wrap=True,
                    spacing=16,
                    run_spacing=12,
                    controls=[
                        ft.Column(
                            width=300,
                            spacing=6,
                            controls=[
                                ft.Text(
                                    str(product["name"]),
                                    size=18,
                                    weight=ft.FontWeight.BOLD,
                                ),
                                ft.Text(
                                    f"SKU: {product['sku']}"
                                ),
                                ft.Text(
                                    f"Đơn giá: {format_vnd(unit_price)}"
                                ),
                                ft.Text(stock_label),
                                ft.Text(
                                    "Thành tiền: "
                                    f"{format_vnd(line_total)}",
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                        ),
                        quantity_field,
                        ft.Button(
                            "Cập nhật",
                            on_click=(
                                lambda e,
                                pid=product_id,
                                field=quantity_field:
                                self.update_quantity(
                                    pid,
                                    field.value,
                                )
                            ),
                        ),
                        ft.Button(
                            "Xóa",
                            on_click=(
                                lambda e, pid=product_id:
                                self.remove_product(pid)
                            ),
                        ),
                    ],
                ),
            ),
        )

    def _unavailable_card(
        self,
        product_id: int,
    ) -> ft.Card:
        """Keep removed/discontinued products visible for deletion."""
        return ft.Card(
            content=ft.Container(
                padding=14,
                content=ft.Row(
                    wrap=True,
                    controls=[
                        ft.Text(
                            f"Sản phẩm #{product_id} "
                            "không còn kinh doanh."
                        ),
                        ft.Button(
                            "Xóa",
                            on_click=(
                                lambda e, pid=product_id:
                                self.remove_product(pid)
                            ),
                        ),
                    ],
                ),
            ),
        )

    def load(self, *, redraw: bool = False) -> None:
        """Refresh prices from database and calculate provisional total."""
        self.error.value = ""
        self.counter.value = ""
        self.rows.controls = []
        self.total = Decimal(0)

        try:
            cart_rows = self.cart.items()
            unavailable = 0

            for row in cart_rows:
                product_id = row["product_id"]

                try:
                    product = self.products.get_public_detail(
                        product_id=product_id,
                    )
                except AppError as exc:
                    if exc.error_code != "NOT_FOUND":
                        raise

                    unavailable += 1
                    self.rows.controls.append(
                        self._unavailable_card(product_id)
                    )
                    continue

                self.rows.controls.append(
                    self._product_card(row, product)
                )

            self.counter.value = (
                f"{len(cart_rows)}/20 dòng sản phẩm"
            )

            if not cart_rows:
                self.rows.controls = [
                    ft.Text(
                        "Giỏ hàng đang trống. "
                        "Hãy chọn một sản phẩm để bắt đầu."
                    )
                ]

            self.total_text.value = (
                "Tổng tiền tạm tính: "
                f"{format_vnd(self.total)}"
            )

            if unavailable:
                self.note.value = (
                    f"Có {unavailable} sản phẩm không còn "
                    "kinh doanh, không tính vào tổng tiền. "
                    "Vui lòng xóa khỏi giỏ hàng."
                )
            else:
                self.note.value = (
                    "Giá bán được cập nhật khi xem giỏ hàng. "
                    "Đây chưa phải đơn đặt hàng. "
                    "Sản phẩm chưa được giữ tồn."
                )

        except AppError as exc:
            if exc.error_code == "CART_INVALID":
                self.error.value = exc.message
            else:
                logger.warning(
                    "Cart load business error: %s",
                    exc.error_code,
                )
                self.error.value = (
                    "Không thể tải thông tin sản phẩm "
                    "trong giỏ hàng."
                )

            self.rows.controls = []
            self.total = Decimal(0)
            self.total_text.value = (
                f"Tổng tiền tạm tính: {format_vnd(0)}"
            )

        except Exception:
            logger.exception("Cart load failed")
            self.error.value = (
                "Không thể tải giỏ hàng. "
                "Vui lòng thử lại."
            )
            self.rows.controls = []
            self.total = Decimal(0)
            self.total_text.value = (
                f"Tổng tiền tạm tính: {format_vnd(0)}"
            )

        if redraw:
            self.page.update()

    def update_quantity(
        self,
        product_id: int,
        raw_quantity: str | None,
    ) -> None:
        try:
            self.authorize()

            value = (
                raw_quantity.strip()
                if isinstance(raw_quantity, str)
                else ""
            )

            if (
                not value
                or not value.isascii()
                or not value.isdecimal()
            ):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Số lượng phải là số nguyên dương.",
                )

            quantity = int(value)

            self.cart.set_quantity(
                product_id,
                quantity,
            )

        except AppError as exc:
            self.error.value = exc.message
            self.page.update()
            return

        except (TypeError, ValueError):
            self.error.value = (
                "Số lượng không hợp lệ."
            )
            self.page.update()
            return

        self.load(redraw=True)

    def remove_product(self, product_id: int) -> None:
        try:
            self.authorize()
            self.cart.remove(product_id)

        except AppError as exc:
            self.error.value = exc.message
            self.page.update()
            return

        self.load(redraw=True)

    def clear_cart(self, e=None) -> None:
        try:
            self.authorize()
            self.cart.clear()

        except AppError as exc:
            self.error.value = exc.message
            self.page.update()
            return

        self.load(redraw=True)


def build_cart_page(
    page: ft.Page,
    *,
    authorize: Callable[[], None],
) -> ft.Column:
    panel = CartPanel(
        page,
        cart=CartSession(page.session.store),
        products=ProductManagementService(),
        authorize=authorize,
    )

    panel.load(redraw=False)
    return panel.root
