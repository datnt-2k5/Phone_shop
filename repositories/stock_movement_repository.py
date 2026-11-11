
"""Task 38 / US07: append-only IMPORT stock movements."""

from datetime import datetime

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class StockMovementRepository(BaseRepository):
    """Create a single IMPORT movement; never commit or delete history."""

    def record_import(
        self,
        *,
        receipt_id: int,
        product_id: int,
        quantity: int,
        stock_after: int,
        created_at: datetime,
        created_by: int,
    ) -> int:
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
                    'IMPORT',
                    :quantity,
                    :stock_after,
                    'IMPORT_RECEIPT',
                    :receipt_id,
                    :operation_key,
                    NULL,
                    :created_at,
                    :created_by
                )
            """),
            {
                "product_id": product_id,
                "quantity": quantity,
                "stock_after": stock_after,
                "receipt_id": receipt_id,
                "operation_key": f"IMPORT:{receipt_id}:{product_id}",
                "created_at": created_at,
                "created_by": created_by,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID biến động kho")

        return int(result.lastrowid)
