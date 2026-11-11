
"""Task 38 / US07: inventory-only SQL; transaction belongs to Service."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class InventoryRepository(BaseRepository):
    """Lock/read and change stock + cost; no commit, no public UI access."""

    def get_for_update(self, product_id: int) -> dict[str, Any] | None:
        row = self.session.execute(
            text("""
                SELECT id, stock, cost_price, status
                FROM products
                WHERE id = :product_id
                FOR UPDATE
            """),
            {"product_id": product_id},
        ).mappings().first()

        return dict(row) if row is not None else None

    def set_balance(
        self,
        *,
        product_id: int,
        stock: int,
        cost_price: Decimal,
        updated_at: datetime,
        updated_by: int,
    ) -> bool:
        result = self.session.execute(
            text("""
                UPDATE products
                SET stock = :stock,
                    cost_price = :cost_price,
                    updated_at = :updated_at,
                    updated_by = :updated_by
                WHERE id = :product_id
            """),
            {
                "product_id": product_id,
                "stock": stock,
                "cost_price": cost_price,
                "updated_at": updated_at,
                "updated_by": updated_by,
            },
        )

        return result.rowcount == 1
