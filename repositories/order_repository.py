
"""Task 49 / US09-T02: Order Repository for MariaDB.

This Repository provides SQL access to orders and order_items.

Rules:
- Never commit or roll back transactions.
- Never authorize users at Repository level.
- Never alter stock when creating a PENDING order.
- Keep order and product snapshots in their original form.
- Handle checkout validation and idempotency in Service later.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class OrderRepository(BaseRepository):
    """Order and order-item persistence without business orchestration."""

    _ORDER_COLUMNS = """
        id,
        code,
        customer_id,
        idempotency_key,
        request_hash,
        status,
        receiver_name,
        receiver_phone,
        receiver_address,
        note,
        total_amount,
        created_at,
        confirmed_at,
        completed_at,
        cancelled_at,
        cancelled_by,
        cancel_reason,
        updated_at
    """

    _ITEM_COLUMNS = """
        id,
        order_id,
        product_id,
        product_name,
        brand_name,
        quantity,
        unit_price,
        unit_cost
    """

    @staticmethod
    def _page(
        limit: int,
        offset: int,
    ) -> dict[str, int]:
        """Validate SQL pagination arguments."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError(
                "limit phải là số nguyên từ 1 đến 100."
            )

        if type(offset) is not int or offset < 0:
            raise ValueError(
                "offset phải là số nguyên không âm."
            )

        return {
            "limit": limit,
            "offset": offset,
        }

    def get_by_id(
        self,
        order_id: int,
    ) -> dict[str, Any] | None:
        """Return one order by primary key."""
        row = self.session.execute(
            text(f"""
                SELECT {self._ORDER_COLUMNS}
                FROM orders
                WHERE id = :order_id
                LIMIT 1
            """),
            {"order_id": order_id},
        ).mappings().first()

        return dict(row) if row is not None else None

    def get_by_code(
        self,
        code: str,
    ) -> dict[str, Any] | None:
        """Return one order by its unique code."""
        row = self.session.execute(
            text(f"""
                SELECT {self._ORDER_COLUMNS}
                FROM orders
                WHERE code = :code
                LIMIT 1
            """),
            {"code": code},
        ).mappings().first()

        return dict(row) if row is not None else None

    def find_by_idempotency_key(
        self,
        *,
        customer_id: int,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        """Find a previously created order for the same customer.

        The Service must compare request_hash before deciding
        whether to return an existing order or raise conflict.
        """
        row = self.session.execute(
            text(f"""
                SELECT {self._ORDER_COLUMNS}
                FROM orders
                WHERE customer_id = :customer_id
                  AND idempotency_key = :idempotency_key
                LIMIT 1
            """),
            {
                "customer_id": customer_id,
                "idempotency_key": idempotency_key,
            },
        ).mappings().first()

        return dict(row) if row is not None else None

    def create_pending(
        self,
        *,
        temporary_code: str,
        customer_id: int,
        idempotency_key: str,
        request_hash: str,
        receiver_name: str,
        receiver_phone: str,
        receiver_address: str,
        note: str | None,
        total_amount: Decimal,
        now_utc: datetime,
    ) -> int:
        """Insert an order with status PENDING.

        The caller owns the transaction and must supply
        validated checkout values and the computed total.
        """
        result = self.session.execute(
            text("""
                INSERT INTO orders (
                    code,
                    customer_id,
                    idempotency_key,
                    request_hash,
                    status,
                    receiver_name,
                    receiver_phone,
                    receiver_address,
                    note,
                    total_amount,
                    created_at,
                    updated_at
                )
                VALUES (
                    :code,
                    :customer_id,
                    :idempotency_key,
                    :request_hash,
                    'PENDING',
                    :receiver_name,
                    :receiver_phone,
                    :receiver_address,
                    :note,
                    :total_amount,
                    :now_utc,
                    :now_utc
                )
            """),
            {
                "code": temporary_code,
                "customer_id": customer_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "receiver_name": receiver_name,
                "receiver_phone": receiver_phone,
                "receiver_address": receiver_address,
                "note": note,
                "total_amount": total_amount,
                "now_utc": now_utc,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError(
                "Không lấy được ID đơn hàng vừa tạo."
            )

        return int(result.lastrowid)

    def update_code(
        self,
        *,
        order_id: int,
        code: str,
    ) -> bool:
        """Replace a temporary code while the order is PENDING."""
        result = self.session.execute(
            text("""
                UPDATE orders
                SET code = :code
                WHERE id = :order_id
                  AND status = 'PENDING'
            """),
            {
                "order_id": order_id,
                "code": code,
            },
        )

        return result.rowcount == 1

    def create_item(
        self,
        *,
        order_id: int,
        product_id: int,
        product_name: str,
        brand_name: str,
        quantity: int,
        unit_price: Decimal,
    ) -> int:
        """Insert the product/price snapshot for a PENDING order.

        unit_cost remains NULL until the Admin confirms
        the order in US10.
        """
        result = self.session.execute(
            text("""
                INSERT INTO order_items (
                    order_id,
                    product_id,
                    product_name,
                    brand_name,
                    quantity,
                    unit_price,
                    unit_cost
                )
                VALUES (
                    :order_id,
                    :product_id,
                    :product_name,
                    :brand_name,
                    :quantity,
                    :unit_price,
                    NULL
                )
            """),
            {
                "order_id": order_id,
                "product_id": product_id,
                "product_name": product_name,
                "brand_name": brand_name,
                "quantity": quantity,
                "unit_price": unit_price,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError(
                "Không lấy được ID dòng sản phẩm."
            )

        return int(result.lastrowid)

    def list_items(
        self,
        order_id: int,
    ) -> list[dict[str, Any]]:
        """Read internal order-item snapshots.

        unit_cost is internal data; a Customer-facing Service
        must not expose this field.
        """
        rows = self.session.execute(
            text(f"""
                SELECT {self._ITEM_COLUMNS}
                FROM order_items
                WHERE order_id = :order_id
                ORDER BY id ASC
            """),
            {"order_id": order_id},
        ).mappings().all()

        return [dict(row) for row in rows]

    def list_customer_orders(
        self,
        *,
        customer_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List one customer's orders in stable newest-first order."""
        params = {
            "customer_id": customer_id,
            **self._page(limit, offset),
        }

        rows = self.session.execute(
            text(f"""
                SELECT {self._ORDER_COLUMNS}
                FROM orders
                WHERE customer_id = :customer_id
                ORDER BY created_at DESC, id DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings().all()

        return [dict(row) for row in rows]
