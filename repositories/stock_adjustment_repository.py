
"""Task 42 / US07 P2: SQL for stock adjustment documents and movements."""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class StockAdjustmentRepository(BaseRepository):
    """Warehouse adjustment SQL. Transaction belongs to the Service."""

    def create_adjustment(
        self,
        *,
        temporary_code: str,
        reason: str,
        created_by: int,
        created_at: datetime,
    ) -> int:
        result = self.session.execute(
            text("""
                INSERT INTO stock_adjustments (
                    code, reason, created_by, created_at
                )
                VALUES (
                    :code, :reason, :created_by, :created_at
                )
            """),
            {
                "code": temporary_code,
                "reason": reason,
                "created_by": created_by,
                "created_at": created_at,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID phiếu điều chỉnh")

        return int(result.lastrowid)

    def update_code(
        self,
        *,
        adjustment_id: int,
        code: str,
    ) -> bool:
        result = self.session.execute(
            text("""
                UPDATE stock_adjustments
                SET code = :code
                WHERE id = :adjustment_id
            """),
            {
                "adjustment_id": adjustment_id,
                "code": code,
            },
        )
        return result.rowcount == 1

    def create_item(
        self,
        *,
        adjustment_id: int,
        product_id: int,
        old_quantity: int,
        actual_quantity: int,
        quantity_change: int,
        stock_after: int,
    ) -> int:
        result = self.session.execute(
            text("""
                INSERT INTO stock_adjustment_items (
                    adjustment_id,
                    product_id,
                    old_quantity,
                    actual_quantity,
                    quantity_change,
                    stock_after
                )
                VALUES (
                    :adjustment_id,
                    :product_id,
                    :old_quantity,
                    :actual_quantity,
                    :quantity_change,
                    :stock_after
                )
            """),
            {
                "adjustment_id": adjustment_id,
                "product_id": product_id,
                "old_quantity": old_quantity,
                "actual_quantity": actual_quantity,
                "quantity_change": quantity_change,
                "stock_after": stock_after,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID dòng kiểm kê")

        return int(result.lastrowid)

    def record_movement(
        self,
        *,
        adjustment_id: int,
        product_id: int,
        quantity_change: int,
        stock_after: int,
        reason: str,
        created_by: int,
        created_at: datetime,
    ) -> int:
        if quantity_change == 0:
            raise ValueError("Không ghi movement chênh lệch bằng 0")

        result = self.session.execute(
            text("""
                INSERT INTO stock_movements (
                    product_id,
                    type,
                    quantity_change,
                    stock_after,
                    ref_type,
                    ref_id,
                    operation_key,
                    reason,
                    created_at,
                    created_by
                )
                VALUES (
                    :product_id,
                    'ADJUST',
                    :quantity_change,
                    :stock_after,
                    'STOCK_ADJUSTMENT',
                    :adjustment_id,
                    :operation_key,
                    :reason,
                    :created_at,
                    :created_by
                )
            """),
            {
                "product_id": product_id,
                "quantity_change": quantity_change,
                "stock_after": stock_after,
                "adjustment_id": adjustment_id,
                "operation_key": (
                    f"ADJUST:{adjustment_id}:{product_id}"
                ),
                "reason": reason,
                "created_at": created_at,
                "created_by": created_by,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID biến động kho")

        return int(result.lastrowid)

    def get_adjustment(
        self,
        adjustment_id: int,
    ) -> dict[str, Any] | None:
        row = self.session.execute(
            text("""
                SELECT id, code, reason,
                       created_by, created_at
                FROM stock_adjustments
                WHERE id = :adjustment_id
                LIMIT 1
            """),
            {"adjustment_id": adjustment_id},
        ).mappings().first()

        return dict(row) if row is not None else None

    def list_items(
        self,
        adjustment_id: int,
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT
                    id, adjustment_id, product_id,
                    old_quantity, actual_quantity,
                    quantity_change, stock_after
                FROM stock_adjustment_items
                WHERE adjustment_id = :adjustment_id
                ORDER BY id ASC
            """),
            {"adjustment_id": adjustment_id},
        ).mappings().all()

        return [dict(row) for row in rows]
