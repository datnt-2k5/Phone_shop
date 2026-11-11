
"""Task 39 / US07: read-only import history, movements, and stock queries."""

from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class WarehouseQueryRepository(BaseRepository):
    """Read-only queries for the admin warehouse pages; no commits."""

    def list_receipts(
        self, *, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT r.id, r.code, r.supplier_id,
                       s.name AS supplier_name,
                       s.is_active AS supplier_is_active,
                       r.import_date, r.total_amount, r.note,
                       r.created_by, u.full_name AS created_by_name,
                       r.created_at
                FROM import_receipts AS r
                JOIN suppliers AS s ON s.id = r.supplier_id
                JOIN users AS u ON u.id = r.created_by
                ORDER BY r.id DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_receipt(self, receipt_id: int) -> dict[str, Any] | None:
        row = self.session.execute(
            text("""
                SELECT r.id, r.code, r.supplier_id,
                       s.name AS supplier_name,
                       s.is_active AS supplier_is_active,
                       r.import_date, r.total_amount, r.note,
                       r.created_by, u.full_name AS created_by_name,
                       r.created_at
                FROM import_receipts AS r
                JOIN suppliers AS s ON s.id = r.supplier_id
                JOIN users AS u ON u.id = r.created_by
                WHERE r.id = :receipt_id
                LIMIT 1
            """),
            {"receipt_id": receipt_id},
        ).mappings().first()
        return dict(row) if row is not None else None

    def list_receipt_items(
        self, receipt_id: int
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT i.id, i.receipt_id, i.product_id,
                       p.sku, p.name AS product_name,
                       p.storage, p.color,
                       i.quantity, i.import_price, i.line_total
                FROM import_items AS i
                JOIN products AS p ON p.id = i.product_id
                WHERE i.receipt_id = :receipt_id
                ORDER BY i.id ASC
            """),
            {"receipt_id": receipt_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_movements(
        self,
        *,
        product_id: int | None,
        movement_type: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT m.id, m.product_id, p.sku,
                   p.name AS product_name,
                   m.type, m.quantity_change, m.stock_after,
                   m.ref_type, m.ref_id, m.operation_key,
                   m.reason, m.created_at, m.created_by,
                   u.full_name AS created_by_name
            FROM stock_movements AS m
            JOIN products AS p ON p.id = m.product_id
            JOIN users AS u ON u.id = m.created_by
            WHERE 1 = 1
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if product_id is not None:
            sql += " AND m.product_id = :product_id"
            params["product_id"] = product_id
        if movement_type is not None:
            sql += " AND m.type = :movement_type"
            params["movement_type"] = movement_type
        sql += " ORDER BY m.id DESC LIMIT :limit OFFSET :offset"

        rows = self.session.execute(
            text(sql), params
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_inventory(
        self,
        *,
        level: str,
        include_discontinued: bool,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT p.id, p.sku, p.name, p.brand_id,
                   b.name AS brand_name, p.storage, p.color,
                   p.stock, p.min_stock, p.cost_price,
                   p.sell_price, p.status,
                   CASE
                       WHEN p.stock = 0 THEN 'OUT'
                       WHEN p.stock <= p.min_stock THEN 'LOW'
                       ELSE 'OK'
                   END AS stock_level
            FROM products AS p
            JOIN brands AS b ON b.id = p.brand_id
            WHERE 1 = 1
        """
        if not include_discontinued:
            sql += " AND p.status = 'ACTIVE'"
        if level == "OUT":
            sql += " AND p.stock = 0"
        elif level == "LOW":
            sql += " AND p.stock > 0 AND p.stock <= p.min_stock"
        elif level == "ALERT":
            sql += " AND p.stock <= p.min_stock"
        sql += " ORDER BY p.id DESC LIMIT :limit OFFSET :offset"

        rows = self.session.execute(
            text(sql), {"limit": limit, "offset": offset}
        ).mappings().all()
        return [dict(row) for row in rows]
