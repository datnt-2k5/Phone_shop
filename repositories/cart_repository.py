
"""Task 55: MariaDB repository for persistent Customer carts.

Repository methods never commit or roll back.
The Service owns the transaction.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


class CartRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def read(self, *, customer_id: int) -> str | None:
        """Read current cart without locking or writing."""
        return self.session.execute(
            text("""
                SELECT items_json
                FROM customer_carts
                WHERE customer_id = :customer_id
            """),
            {"customer_id": customer_id},
        ).scalar_one_or_none()

    def lock_or_create(self, *, customer_id: int) -> str:
        """Create row if absent, then lock it for mutation."""
        self.session.execute(
            text("""
                INSERT INTO customer_carts (
                    customer_id,
                    items_json,
                    revision,
                    updated_at
                )
                VALUES (
                    :customer_id,
                    '[]',
                    0,
                    UTC_TIMESTAMP(6)
                )
                ON DUPLICATE KEY UPDATE
                    customer_id = VALUES(customer_id)
            """),
            {"customer_id": customer_id},
        )

        return self.session.execute(
            text("""
                SELECT items_json
                FROM customer_carts
                WHERE customer_id = :customer_id
                FOR UPDATE
            """),
            {"customer_id": customer_id},
        ).scalar_one()

    def save(
        self,
        *,
        customer_id: int,
        items_json: str,
    ) -> None:
        """Save a validated cart inside the caller's transaction."""
        result = self.session.execute(
            text("""
                UPDATE customer_carts
                SET items_json = :items_json,
                    revision = revision + 1,
                    updated_at = UTC_TIMESTAMP(6)
                WHERE customer_id = :customer_id
            """),
            {
                "customer_id": customer_id,
                "items_json": items_json,
            },
        )

        if result.rowcount != 1:
            raise RuntimeError(
                "Không thể cập nhật giỏ hàng database."
            )
