
"""Task 52: checkout workflow and safe session lifecycle."""

from collections.abc import Callable
from typing import Any

from models.app_error import AppError
from services.cart_session import CartSession
from services.checkout_order_service import (
    CheckoutOrderResult,
    CheckoutOrderService,
)
from services.persistent_cart import PersistentCart
from ui.checkout_key_state import CheckoutKeyState


class CheckoutFlow:
    def __init__(
        self,
        *,
        cart: CartSession | PersistentCart,
        keys: CheckoutKeyState,
        authorize: Callable[[], None],
        service: CheckoutOrderService | None = None,
    ) -> None:
        self.cart = cart
        self.keys = keys
        self.authorize = authorize
        self.service = (
            service
            if service is not None
            else CheckoutOrderService()
        )

    def prepare_order(
        self,
        *,
        receiver_name: str,
        receiver_phone: str,
        receiver_address: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Authorize and prepare a stable checkout request."""
        self.authorize()

        items = self.cart.items()

        if not items:
            raise AppError(
                "VALIDATION_ERROR",
                "Giỏ hàng đang trống. Vui lòng chọn sản phẩm.",
            )

        business_payload = {
            "receiver_name": receiver_name,
            "receiver_phone": receiver_phone,
            "receiver_address": receiver_address,
            "note": note,
            "items": items,
        }

        return self.keys.prepare(business_payload)

    def execute_order(
        self,
        checkout_request: dict[str, Any],
    ) -> CheckoutOrderResult:
        """Execute checkout without changing cart or checkout key."""
        result = self.service.create(
            session_store=self.cart.store,
            checkout_request=checkout_request,
        )

        if result.outcome not in ("CREATED", "REPLAY"):
            raise RuntimeError(
                "Kết quả checkout không hợp lệ."
            )

        return result

    def finalize_success(self) -> None:
        """Clear session state after receiving confirmed success."""
        self.cart.clear()
        self.keys.clear()

    def place_order(
        self,
        *,
        receiver_name: str,
        receiver_phone: str,
        receiver_address: str,
        note: str = "",
    ) -> CheckoutOrderResult:
        """Synchronous workflow retained for existing unit tests."""
        checkout_request = self.prepare_order(
            receiver_name=receiver_name,
            receiver_phone=receiver_phone,
            receiver_address=receiver_address,
            note=note,
        )

        result = self.execute_order(checkout_request)

        self.finalize_success()
        return result
