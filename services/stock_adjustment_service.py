
"""Task 42 / US07 P2: atomic physical inventory stock adjustments."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.inventory_repository import InventoryRepository
from repositories.stock_adjustment_repository import StockAdjustmentRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock

MAX_INT = 2_147_483_647
MAX_REASON_LENGTH = 255


class StockAdjustmentService(BaseService):
    """Count actual stock and persist only nonzero differences."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        adjustment_repository_factory: Callable[
            [Session], StockAdjustmentRepository
        ] = StockAdjustmentRepository,
        inventory_repository_factory: Callable[
            [Session], InventoryRepository
        ] = InventoryRepository,
    ) -> None:
        super().__init__(clock=clock)

        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
            clock=clock,
        )
        self.protected_actions = (
            protected_actions
            if protected_actions is not None
            else ProtectedActionService(
                session_factory=session_factory,
                auth_service=self.auth_service,
            )
        )
        self.adjustment_repository_factory = (
            adjustment_repository_factory
        )
        self.inventory_repository_factory = (
            inventory_repository_factory
        )

    @staticmethod
    def _positive_id(value: object) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "ID sản phẩm không hợp lệ.",
                {"product_id": "Phải là số nguyên dương."},
            )
        return value

    @classmethod
    def _prepare(
        cls,
        *,
        reason: object,
        items: object,
    ) -> tuple[str, list[dict[str, int]]]:
        if not isinstance(reason, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Lý do kiểm kê không hợp lệ.",
            )

        reason = reason.strip()
        if not 1 <= len(reason) <= MAX_REASON_LENGTH:
            raise AppError(
                "VALIDATION_ERROR",
                "Lý do kiểm kê phải có từ 1 đến 255 ký tự.",
            )

        if not isinstance(items, list) or not items:
            raise AppError(
                "VALIDATION_ERROR",
                "Phiếu kiểm kê cần ít nhất một sản phẩm.",
            )

        seen: set[int] = set()
        clean: list[dict[str, int]] = []

        for item in items:
            if not isinstance(item, dict):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Dòng kiểm kê không hợp lệ.",
                )

            product_id = cls._positive_id(item.get("product_id"))
            actual_quantity = item.get("actual_quantity")

            if (
                type(actual_quantity) is not int
                or not 0 <= actual_quantity <= MAX_INT
            ):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Tồn thực tế phải là số nguyên không âm.",
                )

            if product_id in seen:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Một sản phẩm không được xuất hiện hai lần.",
                )

            seen.add(product_id)
            clean.append(
                {
                    "product_id": product_id,
                    "actual_quantity": actual_quantity,
                }
            )

        # Khóa sản phẩm theo thứ tự ID tăng dần.
        clean.sort(key=lambda item: item["product_id"])
        return reason, clean

    def create_adjustment(
        self,
        *,
        session_store: AuthSessionStore,
        reason: str,
        items: list[dict[str, int]],
    ) -> dict[str, Any]:
        """Create one adjustment transaction, or no document if no delta."""
        reason, lines = self._prepare(
            reason=reason,
            items=items,
        )

        def action(session: Session) -> dict[str, Any]:
            actor = self.auth_service.require_user(
                session_store=session_store
            )
            actor_id = actor.user_id

            inventory = self.inventory_repository_factory(session)
            adjustments = self.adjustment_repository_factory(session)
            timestamp = self.current_time()

            changes: list[dict[str, Any]] = []

            # Read fresh stock only after locking each product.
            for line in lines:
                product_id = line["product_id"]
                row = inventory.get_for_update(product_id)

                if row is None:
                    raise AppError(
                        "NOT_FOUND",
                        "Không tìm thấy sản phẩm kiểm kê.",
                    )

                old_quantity = int(row["stock"])
                actual_quantity = line["actual_quantity"]
                delta = actual_quantity - old_quantity

                # No movement, no item for unchanged stock.
                if delta == 0:
                    continue

                changes.append(
                    {
                        "product_id": product_id,
                        "old_quantity": old_quantity,
                        "actual_quantity": actual_quantity,
                        "quantity_change": delta,
                        "stock_after": actual_quantity,
                        "cost_price": row["cost_price"],
                    }
                )

            # All lines unchanged: do not create a header.
            if not changes:
                return {
                    "created": False,
                    "id": None,
                    "code": None,
                    "changed_items": 0,
                }

            adjustment_id = adjustments.create_adjustment(
                temporary_code=f"TMP-ADJ-{uuid4().hex}",
                reason=reason,
                created_by=actor_id,
                created_at=timestamp,
            )
            code = f"ADJ{adjustment_id:08d}"

            if not adjustments.update_code(
                adjustment_id=adjustment_id,
                code=code,
            ):
                raise RuntimeError(
                    "Không cập nhật được mã phiếu kiểm kê"
                )

            # Every item, balance, and movement shares this transaction.
            for change in changes:
                product_id = change["product_id"]

                adjustments.create_item(
                    adjustment_id=adjustment_id,
                    product_id=product_id,
                    old_quantity=change["old_quantity"],
                    actual_quantity=change["actual_quantity"],
                    quantity_change=change["quantity_change"],
                    stock_after=change["stock_after"],
                )

                updated = inventory.set_balance(
                    product_id=product_id,
                    stock=change["stock_after"],
                    # Adjustments preserve cost_price, including at zero.
                    cost_price=change["cost_price"],
                    updated_at=timestamp,
                    updated_by=actor_id,
                )

                if not updated:
                    raise RuntimeError(
                        "Không cập nhật được tồn kiểm kê"
                    )

                adjustments.record_movement(
                    adjustment_id=adjustment_id,
                    product_id=product_id,
                    quantity_change=change["quantity_change"],
                    stock_after=change["stock_after"],
                    reason=reason,
                    created_by=actor_id,
                    created_at=timestamp,
                )

            return {
                "created": True,
                "id": adjustment_id,
                "code": code,
                "changed_items": len(changes),
            }

        # P2: use the existing admin-only stock mutation permission.
        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.IMPORT_STOCK,
            action=action,
        )
