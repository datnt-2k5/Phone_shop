
"""Task 53: read-only queries for Customer orders.

All queries are parameterized and scoped to customer_id.
No write, commit, rollback or cost-price exposure.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class CustomerOrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_for_customer(self, *, customer_id: int) -> int:
        result = self.session.execute(
            text("""
                SELECT COUNT(*)
                FROM orders
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        )
        return int(result.scalar_one())

    def list_for_customer(
        self,
        *,
        customer_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT
                    id,
                    code,
                    status,
                    total_amount,
                    created_at
                FROM orders
                WHERE customer_id = :customer_id
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "customer_id": customer_id,
                "limit": limit,
                "offset": offset,
            },
        ).mappings().all()

        return [dict(row) for row in rows]

    def get_owned_order(
        self,
        *,
        customer_id: int,
        order_id: int,
    ) -> dict[str, Any] | None:
        row = self.session.execute(
            text("""
                SELECT
                    id,
                    code,
                    status,
                    total_amount,
                    receiver_name,
                    receiver_phone,
                    receiver_address,
                    note,
                    created_at
                FROM orders
                WHERE id = :order_id
                  AND customer_id = :customer_id
                LIMIT 1
            """),
            {
                "order_id": order_id,
                "customer_id": customer_id,
            },
        ).mappings().first()

        return dict(row) if row is not None else None

    def list_items(
        self,
        *,
        order_id: int,
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT
                    product_id,
                    product_name,
                    brand_name,
                    quantity,
                    unit_price
                FROM order_items
                WHERE order_id = :order_id
                ORDER BY product_id ASC
            """),
            {"order_id": order_id},
        ).mappings().all()

        return [dict(row) for row in rows]
