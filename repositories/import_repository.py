
"""US07-T01: Import receipt/item data access without commits."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class ImportRepository(BaseRepository):
    """SQL operations for warehouse import records."""

    def create_receipt(
        self,
        *,
        temporary_code: str,
        supplier_id: int,
        import_date: datetime,
        total_amount: Decimal,
        note: str | None,
        created_by: int,
        created_at: datetime,
    ) -> int:
        """Create a receipt using a temporary unique code."""
        result = self.session.execute(
            text("""
                INSERT INTO import_receipts (
                    code, supplier_id, import_date,
                    total_amount, note, created_by, created_at
                )
                VALUES (
                    :code, :supplier_id, :import_date,
                    :total_amount, :note, :created_by, :created_at
                )
            """),
            {
                "code": temporary_code,
                "supplier_id": supplier_id,
                "import_date": import_date,
                "total_amount": total_amount,
                "note": note,
                "created_by": created_by,
                "created_at": created_at,
            },
        )
        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID phiếu nhập")
        return int(result.lastrowid)

    def update_code(
        self, *, receipt_id: int, code: str
    ) -> bool:
        """Replace temporary code with the official code."""
        result = self.session.execute(
            text("""
                UPDATE import_receipts
                SET code = :code
                WHERE id = :receipt_id
            """),
            {"receipt_id": receipt_id, "code": code},
        )
        return result.rowcount == 1

    def create_item(
        self,
        *,
        receipt_id: int,
        product_id: int,
        quantity: int,
        import_price: Decimal,
        line_total: Decimal,
    ) -> int:
        """Insert an immutable import receipt line."""
        result = self.session.execute(
            text("""
                INSERT INTO import_items (
                    receipt_id, product_id, quantity,
                    import_price, line_total
                )
                VALUES (
                    :receipt_id, :product_id, :quantity,
                    :import_price, :line_total
                )
            """),
            {
                "receipt_id": receipt_id,
                "product_id": product_id,
                "quantity": quantity,
                "import_price": import_price,
                "line_total": line_total,
            },
        )
        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID chi tiết nhập")
        return int(result.lastrowid)

    def get_receipt(
        self, receipt_id: int
    ) -> dict[str, Any] | None:
        row = self.session.execute(
            text("""
                SELECT id, code, supplier_id, import_date,
                       total_amount, note, created_by, created_at
                FROM import_receipts
                WHERE id = :receipt_id
                LIMIT 1
            """),
            {"receipt_id": receipt_id},
        ).mappings().first()
        return dict(row) if row is not None else None

    def list_items(
        self, receipt_id: int
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT id, receipt_id, product_id,
                       quantity, import_price, line_total
                FROM import_items
                WHERE receipt_id = :receipt_id
                ORDER BY id ASC
            """),
            {"receipt_id": receipt_id},
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_receipts(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit phải từ 1 đến 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset phải là số nguyên không âm")

        rows = self.session.execute(
            text("""
                SELECT id, code, supplier_id, import_date,
                       total_amount, note, created_by, created_at
                FROM import_receipts
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(row) for row in rows]
