
"""US06-T01: suppliers data access; activation rules belong to US06-T03."""

from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class SupplierRepository(BaseRepository):
    @staticmethod
    def _page(limit: int, offset: int) -> dict[str, int]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit phải là số nguyên từ 1 đến 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset phải là số nguyên không âm")
        return {"limit": limit, "offset": offset}

    def list_suppliers(
        self,
        *,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = self._page(limit, offset)
        sql = """
            SELECT id, name, phone, email, address, is_active
            FROM suppliers
        """
        if is_active is not None:
            if type(is_active) is not bool:
                raise ValueError("is_active phải là bool hoặc None")
            sql += " WHERE is_active = :is_active"
            params["is_active"] = int(is_active)
        sql += " ORDER BY name ASC, id ASC LIMIT :limit OFFSET :offset"
        rows = self.session.execute(text(sql), params).mappings().all()
        return [dict(row) for row in rows]

    def get_by_id(
        self, supplier_id: int, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        sql = """
            SELECT id, name, phone, email, address, is_active
            FROM suppliers WHERE id = :supplier_id LIMIT 1
        """
        if for_update:
            sql += " FOR UPDATE"
        row = self.session.execute(
            text(sql), {"supplier_id": supplier_id}
        ).mappings().first()
        return dict(row) if row is not None else None

    def create(
        self,
        *,
        name: str,
        phone: str | None = None,
        email: str | None = None,
        address: str | None = None,
    ) -> int:
        """Start ACTIVE; no arbitrary client-controlled initial status."""
        result = self.session.execute(
            text("""
                INSERT INTO suppliers (name, phone, email, address, is_active)
                VALUES (:name, :phone, :email, :address, 1)
            """),
            {
                "name": name,
                "phone": phone,
                "email": email,
                "address": address,
            },
        )
        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID nhà cung cấp mới")
        return int(result.lastrowid)

    def update_details(
        self,
        *,
        supplier_id: int,
        name: str,
        phone: str | None,
        email: str | None,
        address: str | None,
    ) -> bool:
        """No is_active change or physical deletion in regular edit."""
        result = self.session.execute(
            text("""
                UPDATE suppliers
                SET name = :name, phone = :phone,
                    email = :email, address = :address
                WHERE id = :supplier_id
            """),
            {
                "supplier_id": supplier_id,
                "name": name,
                "phone": phone,
                "email": email,
                "address": address,
            },
        )
        return result.rowcount == 1
