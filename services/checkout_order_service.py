
"""Create a PENDING order with safe MariaDB UNIQUE race recovery."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.order_repository import OrderRepository
from repositories.product_repository import ProductRepository
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.checkout_idempotency_service import (
    CheckoutIdempotencyService,
    IdempotencyCheckResult,
)
from utils.money_utils import quantize_money
from utils.time_utils import Clock

MAX_ORDER_TOTAL = Decimal("9999999999999999.99")


@dataclass(frozen=True, slots=True)
class CheckoutOrderResult:
    """Customer-safe order result."""

    outcome: Literal["CREATED", "REPLAY"]
    order: dict[str, Any]
    message: str


def _safe_order_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "status": row["status"],
        "total_amount": row["total_amount"],
    }


def _resolve_existing(
    row: dict[str, Any],
    request_hash: str,
) -> CheckoutOrderResult:
    if row["request_hash"] != request_hash:
        raise AppError(
            "IDEMPOTENCY_CONFLICT",
            "Nội dung đặt hàng thay đổi nhưng checkout key không đổi.",
            {
                "idempotency_key": (
                    "Hãy sử dụng checkout key mới "
                    "khi thay đổi nội dung đặt hàng."
                )
            },
        )

    return CheckoutOrderResult(
        outcome="REPLAY",
        order=_safe_order_summary(row),
        message="Đơn hàng đã được tiếp nhận trước đó.",
    )


class CheckoutOrderService(BaseService):
    """Create once, replay matching retries, recover UNIQUE races."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        idempotency_service: CheckoutIdempotencyService | None = None,
        order_repository_factory: Callable[
            [Session], OrderRepository
        ] = OrderRepository,
        product_repository_factory: Callable[
            [Session], ProductRepository
        ] = ProductRepository,
    ) -> None:
        super().__init__(clock=clock)
        self.session_factory = session_factory
        self.idempotency_service = (
            idempotency_service
            if idempotency_service is not None
            else CheckoutIdempotencyService(
                session_factory=session_factory,
            )
        )
        self.order_repository_factory = order_repository_factory
        self.product_repository_factory = product_repository_factory

    @staticmethod
    def _read_item_snapshots(
        product_repository: ProductRepository,
        items: list[dict[str, int]],
    ) -> tuple[list[dict[str, Any]], Decimal]:
        snapshots: list[dict[str, Any]] = []
        total = Decimal(0)

        for item in sorted(
            items,
            key=lambda value: value["product_id"],
        ):
            product_id = item["product_id"]
            quantity = item["quantity"]

            product = product_repository.get_by_id(
                product_id,
                for_update=True,
            )

            if product is None or product["status"] != "ACTIVE":
                raise AppError(
                    "PRODUCT_UNAVAILABLE",
                    "Có sản phẩm không còn khả dụng để đặt hàng.",
                    {
                        "items": (
                            "Vui lòng cập nhật giỏ hàng và thử lại."
                        )
                    },
                )

            unit_price = product["sell_price"]

            if (
                type(unit_price) is not Decimal
                or not unit_price.is_finite()
                or unit_price <= 0
                or unit_price != quantize_money(unit_price)
            ):
                raise AppError(
                    "PRICE_INVALID",
                    "Giá bán sản phẩm không hợp lệ.",
                )

            total += quantize_money(unit_price * quantity)

            if total > MAX_ORDER_TOTAL:
                raise AppError(
                    "ORDER_TOTAL_EXCEEDED",
                    "Tổng tiền vượt giới hạn xử lý đơn hàng.",
                )

            snapshots.append(
                {
                    "product_id": product_id,
                    "product_name": product["name"],
                    "brand_name": product["brand_name"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            )

        return snapshots, quantize_money(total)

    def _create_pending_new(
        self,
        decision: IdempotencyCheckResult,
    ) -> CheckoutOrderResult:
        """Write an order in one transaction; failures roll back."""
        normalized = decision.normalized_request

        with self.session_factory() as session, session.begin():
            orders = self.order_repository_factory(session)

            previous = orders.find_by_idempotency_key(
                customer_id=decision.customer_id,
                idempotency_key=decision.idempotency_key,
            )

            if previous is not None:
                return _resolve_existing(
                    previous,
                    decision.request_hash,
                )

            products = self.product_repository_factory(session)

            snapshots, total_amount = self._read_item_snapshots(
                products,
                normalized["items"],
            )

            order_id = orders.create_pending(
                temporary_code=f"TMP-{uuid4().hex}",
                customer_id=decision.customer_id,
                idempotency_key=decision.idempotency_key,
                request_hash=decision.request_hash,
                receiver_name=normalized["receiver_name"],
                receiver_phone=normalized["receiver_phone"],
                receiver_address=normalized["receiver_address"],
                note=normalized["note"],
                total_amount=total_amount,
                now_utc=self.current_time(),
            )

            for snapshot in snapshots:
                orders.create_item(
                    order_id=order_id,
                    **snapshot,
                )

            official_code = f"DH{order_id:08d}"

            if not orders.update_code(
                order_id=order_id,
                code=official_code,
            ):
                raise RuntimeError(
                    "Không thể tạo mã đơn hàng chính thức."
                )

            persisted = orders.get_by_id(order_id)

            if persisted is None:
                raise RuntimeError(
                    "Không tìm thấy đơn hàng vừa tạo."
                )

            result = CheckoutOrderResult(
                outcome="CREATED",
                order=_safe_order_summary(persisted),
                message=(
                    "Đơn hàng đã được tiếp nhận và đang chờ "
                    "cửa hàng xác nhận. "
                    "Sản phẩm chưa được giữ hàng."
                ),
            )

        return result

    def _recover_unique_violation(
        self,
        decision: IdempotencyCheckResult,
        exc: IntegrityError,
    ) -> CheckoutOrderResult:
        """Recover a MariaDB duplicate-key race using a fresh Session.

        The original failed transaction must already be rolled back.
        Only MariaDB error 1062 is eligible for idempotency recovery.
        """
        mysql_args = getattr(exc.orig, "args", ())
        mysql_code = mysql_args[0] if mysql_args else None

        if mysql_code != 1062:
            raise exc

        # Fresh Session => fresh database snapshot.
        with self.session_factory() as session:
            orders = self.order_repository_factory(session)

            previous = orders.find_by_idempotency_key(
                customer_id=decision.customer_id,
                idempotency_key=decision.idempotency_key,
            )

        if previous is None:
            # The UNIQUE error could involve another column,
            # for example the order code. Never invent a REPLAY.
            raise AppError(
                "CHECKOUT_RETRY_REQUIRED",
                "Chưa thể xác định kết quả đặt hàng. "
                "Vui lòng thử lại cùng nội dung và checkout key.",
            ) from exc

        return _resolve_existing(
            previous,
            decision.request_hash,
        )

    def create(
        self,
        *,
        session_store: AuthSessionStore,
        checkout_request: object,
    ) -> CheckoutOrderResult:
        """Authenticate, apply idempotency, then create or replay."""
        decision = self.idempotency_service.check(
            session_store=session_store,
            checkout_request=checkout_request,
        )

        if decision.outcome == "REPLAY":
            if decision.existing_order is None:
                raise RuntimeError(
                    "REPLAY không có dữ liệu đơn hàng."
                )

            return CheckoutOrderResult(
                outcome="REPLAY",
                order=dict(decision.existing_order),
                message="Đơn hàng đã được tiếp nhận trước đó.",
            )

        try:
            return self._create_pending_new(decision)

        except IntegrityError as exc:
            return self._recover_unique_violation(
                decision,
                exc,
            )
