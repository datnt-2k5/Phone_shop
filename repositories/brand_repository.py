
"""US06-T01: read/write brands; no commits and no permission decisions."""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class BrandRepository(BaseRepository):
    @staticmethod
    def _page(limit: int, offset: int) -> dict[str, int]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit phải là số nguyên từ 1 đến 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset phải là số nguyên không âm")
        return {"limit": limit, "offset": offset}

    def list_brands(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = self.session.execute(
            text("""
                SELECT id, name, created_at
                FROM brands
                ORDER BY name ASC, id ASC
                LIMIT :limit OFFSET :offset
            """),
            self._page(limit, offset),
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_by_id(
        self, brand_id: int, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        sql = """
            SELECT id, name, created_at FROM brands
            WHERE id = :brand_id LIMIT 1
        """
        if for_update:
            sql += " FOR UPDATE"
        row = self.session.execute(
            text(sql), {"brand_id": brand_id}
        ).mappings().first()
        return dict(row) if row is not None else None

    def find_by_name(
        self, name: str, *, exclude_id: int | None = None
    ) -> dict[str, Any] | None:
        """Pre-check duplicate brand names; DB UNIQUE wins any race."""
        sql = """
            SELECT id, name, created_at FROM brands
            WHERE name = :name
        """
        params: dict[str, Any] = {"name": name}
        if exclude_id is not None:
            sql += " AND id <> :exclude_id"
            params["exclude_id"] = exclude_id
        sql += " LIMIT 1"
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row is not None else None

    def create(self, *, name: str, now_utc: datetime) -> int:
        result = self.session.execute(
            text("""
                INSERT INTO brands (name, created_at)
                VALUES (:name, :now_utc)
            """),
            {"name": name, "now_utc": now_utc},
        )
        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID hãng mới")
        return int(result.lastrowid)

    def update_name(self, *, brand_id: int, name: str) -> bool:
        result = self.session.execute(
            text("""
                UPDATE brands SET name = :name
                WHERE id = :brand_id
            """),
            {"brand_id": brand_id, "name": name},
        )
        return result.rowcount == 1
