
"""Task 53: Customer order list and detail pages in Flet."""

import logging
from datetime import UTC, datetime, timedelta, timezone

import flet as ft

from models.app_error import AppError
from services.customer_order_service import CustomerOrderService
from ui.components.money_format import format_vnd

logger = logging.getLogger(__name__)

VIETNAM_TIMEZONE = timezone(timedelta(hours=7))

STATUS_LABELS = {
    "PENDING": "Chờ xác nhận",
    "CONFIRMED": "Đã xác nhận",
    "COMPLETED": "Hoàn thành",
    "CANCELLED": "Đã hủy",
}


def format_order_time(value: object) -> str:
    """Database timestamps are stored as UTC."""
    if not isinstance(value, datetime):
        return "Không xác định"

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    local_time = value.astimezone(VIETNAM_TIMEZONE)
    return local_time.strftime("%d/%m/%Y %H:%M")


class CustomerOrdersPanel:
    """Read-only, paginated order history for one Customer."""

    def __init__(
        self,
        page: ft.Page,
        *,
        session_store,
        service: CustomerOrderService | None = None,
    ) -> None:
        self.page = page
        self.session_store = session_store
        self.service = (
            service
            if service is not None
            else CustomerOrderService()
        )

        self.page_number = 1
        self.total_pages = 1

        self.error = ft.Text(
            color=ft.Colors.RED_700,
        )
        self.rows = ft.Column(spacing=12)
        self.page_label = ft.Text()

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

        self.root = ft.Column(
            spacing=16,
            controls=[
                ft.Text(
                    "ĐƠN HÀNG CỦA TÔI",
                    size=26,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Danh sách đơn hàng đã đặt. "
                    "Giá và thông tin sản phẩm là snapshot "
                    "tại thời điểm tạo đơn."
                ),
                self.error,
                self.rows,
                ft.Divider(),
                ft.Row(
                    wrap=True,
                    spacing=12,
                    controls=[
                        self.previous_button,
                        self.page_label,
                        self.next_button,
                    ],
                ),
                ft.Button(
                    "Tiếp tục mua sắm",
                    on_click=lambda e: (
                        self.page.navigate("/products")
                    ),
                ),
            ],
        )

    def _order_card(self, order: dict) -> ft.Card:
        order_id = order["id"]

        status = STATUS_LABELS.get(
            order["status"],
            order["status"],
        )

        return ft.Card(
            content=ft.Container(
                padding=14,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text(
                            f"Mã đơn: {order['code']}",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            f"Trạng thái: {status}"
                        ),
                        ft.Text(
                            "Ngày đặt: "
                            f"{format_order_time(order['created_at'])}"
                        ),
                        ft.Text(
                            "Tổng tiền: "
                            f"{format_vnd(order['total_amount'])}",
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Button(
                            "Xem chi tiết",
                            on_click=(
                                lambda e, oid=order_id:
                                self.page.navigate(
                                    f"/my-orders/{oid}"
                                )
                            ),
                        ),
                    ],
                ),
            ),
        )

    def load(self, *, redraw: bool = False) -> None:
        self.error.value = ""
        self.rows.controls = []

        try:
            result = self.service.list_orders(
                session_store=self.session_store,
                page=self.page_number,
                page_size=10,
            )

        except AppError as exc:
            self.error.value = exc.message
            self.previous_button.disabled = True
            self.next_button.disabled = True

        except Exception:
            logger.exception(
                "Could not load Customer order history"
            )
            self.error.value = (
                "Không thể tải danh sách đơn hàng."
            )
            self.previous_button.disabled = True
            self.next_button.disabled = True

        else:
            self.total_pages = result["total_pages"]

            self.page_label.value = (
                f"Trang {self.page_number}/"
                f"{self.total_pages} – "
                f"{result['total']} đơn hàng"
            )

            if not result["items"]:
                self.rows.controls = [
                    ft.Text(
                        "Bạn chưa có đơn hàng trong trang này."
                    )
                ]
            else:
                self.rows.controls = [
                    self._order_card(order)
                    for order in result["items"]
                ]

            self.previous_button.disabled = (
                self.page_number <= 1
            )
            self.next_button.disabled = (
                self.page_number >= self.total_pages
            )

        if redraw:
            self.page.update()

    def previous_page(self, e=None) -> None:
        if self.page_number > 1:
            self.page_number -= 1
            self.load(redraw=True)

    def next_page(self, e=None) -> None:
        if self.page_number < self.total_pages:
            self.page_number += 1
            self.load(redraw=True)


def build_customer_orders_page(
    page: ft.Page,
    *,
    session_store,
    service: CustomerOrderService | None = None,
) -> ft.Column:
    panel = CustomerOrdersPanel(
        page,
        session_store=session_store,
        service=service,
    )
    panel.load()
    return panel.root


def build_customer_order_detail_page(
    page: ft.Page,
    *,
    order_id: int,
    session_store,
    service: CustomerOrderService | None = None,
) -> ft.Column:
    """Show one order after server-side ownership verification."""
    actual_service = (
        service
        if service is not None
        else CustomerOrderService()
    )

    try:
        order = actual_service.get_order(
            session_store=session_store,
            order_id=order_id,
        )

    except AppError as exc:
        if exc.error_code == "NOT_FOUND":
            message = "404 – Không tìm thấy đơn hàng."
        elif exc.error_code in {
            "UNAUTHORIZED",
            "FORBIDDEN",
            "ACCOUNT_LOCKED",
        }:
            message = "Không có quyền xem đơn hàng."
        else:
            message = exc.message

        return ft.Column(
            controls=[
                ft.Text(message, size=22),
                ft.Button(
                    "Về đơn của tôi",
                    on_click=lambda e: (
                        page.navigate("/my-orders")
                    ),
                ),
            ],
        )

    except Exception:
        logger.exception(
            "Could not load Customer order detail"
        )

        return ft.Column(
            controls=[
                ft.Text(
                    "Không thể tải chi tiết đơn hàng.",
                    size=22,
                ),
            ],
        )

    status = STATUS_LABELS.get(
        order["status"],
        order["status"],
    )

    item_controls: list[ft.Control] = []

    for item in order["items"]:
        line_total = (
            item["unit_price"] * item["quantity"]
        )

        item_controls.append(
            ft.Card(
                content=ft.Container(
                    padding=12,
                    content=ft.Column(
                        spacing=6,
                        controls=[
                            ft.Text(
                                str(item["product_name"]),
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(
                                f"Hãng: {item['brand_name']}"
                            ),
                            ft.Text(
                                f"Số lượng: {item['quantity']}"
                            ),
                            ft.Text(
                                "Đơn giá: "
                                f"{format_vnd(item['unit_price'])}"
                            ),
                            ft.Text(
                                "Thành tiền: "
                                f"{format_vnd(line_total)}"
                            ),
                        ],
                    ),
                ),
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
            ft.Text(f"Trạng thái: {status}"),
            ft.Text(
                "Ngày đặt: "
                f"{format_order_time(order['created_at'])}"
            ),
            ft.Divider(),
            ft.Text(
                "THÔNG TIN NGƯỜI NHẬN",
                weight=ft.FontWeight.BOLD,
                size=18,
            ),
            ft.Text(
                f"Họ tên: {order['receiver_name']}"
            ),
            ft.Text(
                f"Số điện thoại: {order['receiver_phone']}"
            ),
            ft.Text(
                f"Địa chỉ: {order['receiver_address']}"
            ),
            ft.Text(
                f"Ghi chú: {order['note'] or 'Không có'}"
            ),
            ft.Divider(),
            ft.Text(
                "SẢN PHẨM ĐÃ ĐẶT",
                weight=ft.FontWeight.BOLD,
                size=18,
            ),
            *item_controls,
            ft.Divider(),
            ft.Text(
                "Tổng tiền: "
                f"{format_vnd(order['total_amount'])}",
                size=20,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                "Thông tin sản phẩm và giá bán trên đơn "
                "là snapshot khi đặt hàng."
            ),
            ft.Row(
                wrap=True,
                controls=[
                    ft.Button(
                        "Đơn của tôi",
                        on_click=lambda e: (
                            page.navigate("/my-orders")
                        ),
                    ),
                    ft.Button(
                        "Tiếp tục mua sắm",
                        on_click=lambda e: (
                            page.navigate("/products")
                        ),
                    ),
                ],
            ),
        ],
    )
