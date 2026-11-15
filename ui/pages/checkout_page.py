
"""Task 52 (Excel v2.5): checkout and order receipt pages."""

import asyncio
import logging
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

import flet as ft

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.order_repository import OrderRepository
from services.cart_session import CartSession
from services.checkout_order_service import CheckoutOrderService
from services.product_management_service import ProductManagementService
from ui.checkout_flow import CheckoutFlow
from ui.checkout_key_state import CheckoutKeyState
from ui.components.money_format import format_vnd
from ui.components.notifications import notify

logger = logging.getLogger(__name__)


class CheckoutPanel:
    """Customer checkout form backed by the real order service."""

    def __init__(
        self,
        page: ft.Page,
        *,
        authorize: Callable[[], None],
        cart: CartSession | None = None,
        products: ProductManagementService | None = None,
        service: CheckoutOrderService | None = None,
    ) -> None:
        self.page = page
        self.cart = (
            cart
            if cart is not None
            else CartSession(page.session.store)
        )
        self.products = (
            products
            if products is not None
            else ProductManagementService()
        )

        self.flow = CheckoutFlow(
            cart=self.cart,
            keys=CheckoutKeyState(self.cart.store),
            authorize=authorize,
            service=service,
        )

        self.busy = False
        self.confirmed_order_id: int | None = None

        self.receiver_name = ft.TextField(
            label="Họ và tên người nhận",
            width=450,
        )
        self.receiver_phone = ft.TextField(
            label="Số điện thoại",
            width=450,
            keyboard_type=ft.KeyboardType.PHONE,
        )
        self.receiver_address = ft.TextField(
            label="Địa chỉ nhận hàng",
            width=550,
            multiline=True,
            min_lines=2,
            max_lines=3,
        )
        self.note = ft.TextField(
            label="Ghi chú (không bắt buộc)",
            width=550,
            multiline=True,
            min_lines=2,
            max_lines=3,
        )

        self.error = ft.Text(
            color=ft.Colors.RED_700,
        )
        self.summary = ft.Column(spacing=8)
        self.estimated_total = ft.Text(
            weight=ft.FontWeight.BOLD,
            size=19,
        )
        self.loading = ft.ProgressRing(
            width=22,
            height=22,
            visible=False,
        )

        self.submit_button = ft.Button(
            "Đặt hàng",
            on_click=self.place_order,
        )

        self.root = ft.Column(
            spacing=16,
            controls=[
                ft.Text(
                    "THANH TOÁN / ĐẶT HÀNG",
                    size=26,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Đơn hàng sẽ được tiếp nhận ở trạng thái "
                    "PENDING. Sản phẩm chưa được giữ hàng."
                ),
                ft.Divider(),
                ft.Text(
                    "SẢN PHẨM TRONG GIỎ",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                ),
                self.summary,
                self.estimated_total,
                ft.Text(
                    "Giá hiển thị chỉ là tạm tính. "
                    "Hệ thống sẽ lấy giá bán hiện tại từ "
                    "database khi tạo đơn mới."
                ),
                ft.Divider(),
                ft.Text(
                    "THÔNG TIN NGƯỜI NHẬN",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                ),
                self.receiver_name,
                self.receiver_phone,
                self.receiver_address,
                self.note,
                self.error,
                ft.Row(
                    wrap=True,
                    spacing=12,
                    controls=[
                        self.submit_button,
                        self.loading,
                        ft.TextButton(
                            "Quay về giỏ hàng",
                            on_click=lambda e: (
                                self.page.navigate("/cart")
                            ),
                        ),
                    ],
                ),
            ],
        )

    def load(self) -> None:
        """Show a provisional cart summary without blocking replay."""
        self.summary.controls = []
        self.estimated_total.value = ""
        self.error.value = ""

        try:
            items = self.cart.items()
        except AppError as exc:
            self.error.value = exc.message
            self.submit_button.disabled = True
            return

        if not items:
            self.summary.controls.append(
                ft.Text("Giỏ hàng đang trống.")
            )
            self.submit_button.disabled = True
            return

        self.submit_button.disabled = False
        provisional_total = Decimal(0)
        has_unknown_price = False

        for item in items:
            product_id = item["product_id"]
            quantity = item["quantity"]

            title = f"Sản phẩm #{product_id}"
            price_text = "Giá sẽ được xác nhận"

            try:
                product = self.products.get_public_detail(
                    product_id=product_id,
                )

                title = str(product["name"])
                raw_price = product["sell_price"]

                if type(raw_price) not in (
                    Decimal,
                    int,
                    str,
                ):
                    raise ValueError("Invalid price")

                price = Decimal(raw_price)

                if not price.is_finite() or price <= 0:
                    raise ValueError("Invalid price")

                line_total = price * quantity
                provisional_total += line_total
                price_text = format_vnd(line_total)

            except (
                AppError,
                InvalidOperation,
                ValueError,
                KeyError,
                TypeError,
            ):
                # Allow a matching idempotency retry even if
                # a product has since become unavailable.
                has_unknown_price = True

            self.summary.controls.append(
                ft.Text(
                    f"{title} | SL: {quantity} | "
                    f"Tạm tính: {price_text}"
                )
            )

        if has_unknown_price:
            self.estimated_total.value = (
                "Tổng tiền cần xác nhận khi đặt hàng."
            )
        else:
            self.estimated_total.value = (
                "Tổng tiền tạm tính: "
                f"{format_vnd(provisional_total)}"
            )


    async def place_order(self, e=None) -> None:
        """Submit checkout and never confuse UI failure with DB failure."""
        if self.busy or self.confirmed_order_id is not None:
            return

        self.busy = True
        self.submit_button.disabled = True
        self.loading.visible = True
        self.error.value = ""
        self.page.update()

        try:
            values = {
                "receiver_name": self.receiver_name.value or "",
                "receiver_phone": self.receiver_phone.value or "",
                "receiver_address": self.receiver_address.value or "",
                "note": self.note.value or "",
            }

            # Prepare payload and session key on the UI thread.
            checkout_request = self.flow.prepare_order(**values)

            # Only the database operation runs in a worker thread.
            result = await asyncio.to_thread(
                self.flow.execute_order,
                checkout_request,
            )

        except AppError as exc:
            self.error.color = ft.Colors.RED_700
            self.error.value = exc.message

            notify(
                self.page,
                exc.message,
                error=True,
            )

        except Exception:
            logger.exception(
                "Checkout result not confirmed by UI"
            )

            self.error.color = ft.Colors.RED_700
            self.error.value = (
                "Chưa thể xác định kết quả đặt hàng. "
                "Giỏ và checkout key được giữ để kiểm tra "
                "hoặc thử lại cùng nội dung."
            )

            notify(
                self.page,
                self.error.value,
                error=True,
            )

        else:
            # Backend has returned a successful result.
            # From here onwards, never report that checkout failed.
            order_id = int(result.order["id"])
            order_code = str(result.order["code"])

            self.confirmed_order_id = order_id

            self.error.color = ft.Colors.GREEN_700
            self.error.value = (
                f"Đơn {order_code} đã được ghi nhận thành công."
            )

            try:
                # Session cleanup stays on the UI thread.
                self.flow.finalize_success()

            except Exception:
                logger.exception(
                    "Order %s committed, but session cleanup failed",
                    order_code,
                )
                self.error.value = (
                    f"Đơn {order_code} đã được ghi nhận. "
                    "Không thể dọn trạng thái giỏ hàng. "
                    "Không đặt lại đơn này."
                )

            try:
                # Flet async handlers should await push_route().
                await self.page.push_route(
                    f"/my-orders/{order_id}"
                )

            except Exception:
                logger.exception(
                    "Order %s committed, receipt navigation failed",
                    order_code,
                )

                self.error.value = (
                    f"Đơn {order_code} đã được tạo thành công. "
                    f"Bạn có thể xem đơn tại /my-orders/{order_id}. "
                    "Không bấm Đặt hàng lần nữa."
                )

            else:
                try:
                    notify(self.page, result.message)
                except Exception:
                    logger.exception(
                        "Could not display order success notification"
                    )

        finally:
            self.busy = False
            self.loading.visible = False

            # Never allow resubmission after confirmed success.
            self.submit_button.disabled = (
                self.confirmed_order_id is not None
            )

            self.page.update()


def build_checkout_page(
    page: ft.Page,
    *,
    authorize: Callable[[], None],
) -> ft.Column:
    panel = CheckoutPanel(
        page,
        authorize=authorize,
    )
    panel.load()
    return panel.root


def build_order_receipt_page(
    page: ft.Page,
    *,
    order_id: int,
    customer_id: int,
    authorize: Callable[[], None],
) -> ft.Column:
    """Show only an order belonging to the current Customer."""
    try:
        authorize()

        with SessionLocal() as session:
            repository = OrderRepository(session)
            order = repository.get_by_id(order_id)

            if (
                order is None
                or order["customer_id"] != customer_id
            ):
                return ft.Column(
                    controls=[
                        ft.Text(
                            "404 – Không tìm thấy đơn hàng.",
                            size=22,
                        ),
                        ft.Button(
                            "Về trang sản phẩm",
                            on_click=lambda e: (
                                page.navigate("/products")
                            ),
                        ),
                    ]
                )

            items = repository.list_items(order_id)

    except AppError:
        return ft.Column(
            controls=[
                ft.Text(
                    "Không có quyền xem đơn hàng.",
                    size=22,
                ),
            ]
        )

    except Exception:
        logger.exception("Could not load customer order")
        return ft.Column(
            controls=[
                ft.Text(
                    "Không thể tải chi tiết đơn hàng.",
                    size=22,
                ),
            ]
        )

    item_controls = []

    for item in items:
        line_total = (
            item["unit_price"] * item["quantity"]
        )

        item_controls.append(
            ft.Text(
                f"{item['product_name']} "
                f"({item['brand_name']}) | "
                f"SL: {item['quantity']} | "
                f"Đơn giá: {format_vnd(item['unit_price'])} | "
                f"Thành tiền: {format_vnd(line_total)}"
            )
        )

    return ft.Column(
        spacing=14,
        controls=[
            ft.Text(
                "CHI TIẾT ĐƠN HÀNG",
                size=26,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                f"Mã đơn: {order['code']}",
                size=20,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                f"Trạng thái: {order['status']}"
            ),
            ft.Text(
                "Đơn hàng đã được tiếp nhận và đang chờ "
                "cửa hàng xác nhận. "
                "Sản phẩm chưa được giữ hàng."
            ),
            ft.Divider(),
            *item_controls,
            ft.Divider(),
            ft.Text(
                "Tổng tiền: "
                f"{format_vnd(order['total_amount'])}",
                weight=ft.FontWeight.BOLD,
                size=20,
            ),
            ft.Button(
                "Tiếp tục mua sắm",
                on_click=lambda e: (
                    page.navigate("/products")
                ),
            ),
        ],
    )
