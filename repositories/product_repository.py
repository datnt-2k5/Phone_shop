
"""US05-T01: SQL access to product variants; no session commit or authorization.

Only inventory workflows may change stock/cost_price. Only a higher-level,
authorized Service may call mutating repository methods.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class ProductRepository(BaseRepository):
    """One SKU represents one brand/name/storage/color variant."""

    _ADMIN_COLUMNS = """
        p.id, p.sku, p.name, p.brand_id, b.name AS brand_name,
        p.storage, p.color, p.description, p.image_url,
        p.sell_price, p.cost_price, p.stock, p.min_stock,
        p.status, p.created_at, p.updated_at, p.updated_by
    """
    _PUBLIC_COLUMNS = """
        p.id, p.sku, p.name, p.brand_id, b.name AS brand_name,
        p.storage, p.color, p.description, p.image_url,
        p.sell_price, (p.stock > 0) AS in_stock
    """

    @staticmethod
    def _page_params(limit: int, offset: int) -> dict[str, int]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit phải là số nguyên từ 1 đến 100")
        if type(offset) is not int or offset < 0:
            raise ValueError("offset phải là số nguyên không âm")
        return {"limit": limit, "offset": offset}

    def get_by_id(
        self, product_id: int, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        """Internal/admin read. Callers must check permissions first."""
        sql = f"""
            SELECT {self._ADMIN_COLUMNS}
            FROM products AS p
            JOIN brands AS b ON b.id = p.brand_id
            WHERE p.id = :product_id
            LIMIT 1
        """
        if for_update:
            sql += " FOR UPDATE"
        row = self.session.execute(
            text(sql), {"product_id": product_id}
        ).mappings().first()
        return dict(row) if row is not None else None

    def get_by_sku(
        self, sku: str, *, for_update: bool = False
    ) -> dict[str, Any] | None:
        sql = f"""
            SELECT {self._ADMIN_COLUMNS}
            FROM products AS p
            JOIN brands AS b ON b.id = p.brand_id
            WHERE p.sku = :sku
            LIMIT 1
        """
        if for_update:
            sql += " FOR UPDATE"
        row = self.session.execute(
            text(sql), {"sku": sku}
        ).mappings().first()
        return dict(row) if row is not None else None

    def find_variant(
        self,
        *,
        brand_id: int,
        name: str,
        storage: str,
        color: str,
        exclude_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Lookup for US05 uniqueness validation, optionally excluding self."""
        sql = """
            SELECT id, sku
            FROM products
            WHERE brand_id = :brand_id
              AND name = :name
              AND storage = :storage
              AND color = :color
        """
        params: dict[str, Any] = {
            "brand_id": brand_id,
            "name": name,
            "storage": storage,
            "color": color,
        }
        if exclude_id is not None:
            sql += " AND id <> :exclude_id"
            params["exclude_id"] = exclude_id
        sql += " LIMIT 1"
        row = self.session.execute(text(sql), params).mappings().first()
        return dict(row) if row is not None else None

    def list_products(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Internal/admin listing; includes cost and exact stock."""
        params = self._page_params(limit, offset)
        rows = self.session.execute(
            text(f"""
                SELECT {self._ADMIN_COLUMNS}
                FROM products AS p
                JOIN brands AS b ON b.id = p.brand_id
                ORDER BY p.id DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def list_public(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Only ACTIVE products; never project cost or exact stock."""
        params = self._page_params(limit, offset)
        rows = self.session.execute(
            text(f"""
                SELECT {self._PUBLIC_COLUMNS}
                FROM products AS p
                JOIN brands AS b ON b.id = p.brand_id
                WHERE p.status = 'ACTIVE'
                ORDER BY p.id DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_public_by_id(self, product_id: int) -> dict[str, Any] | None:
        row = self.session.execute(
            text(f"""
                SELECT {self._PUBLIC_COLUMNS}
                FROM products AS p
                JOIN brands AS b ON b.id = p.brand_id
                WHERE p.id = :product_id AND p.status = 'ACTIVE'
                LIMIT 1
            """),
            {"product_id": product_id},
        ).mappings().first()
        return dict(row) if row is not None else None

    def create(
        self,
        *,
        sku: str,
        name: str,
        brand_id: int,
        storage: str,
        color: str,
        sell_price: Decimal,
        now_utc: datetime,
        description: str | None = None,
        image_url: str | None = None,
        min_stock: int = 0,
        updated_by: int | None = None,
    ) -> int:
        """Insert product with immutable opening stock/cost = zero."""
        result = self.session.execute(
            text("""
                INSERT INTO products (
                    sku, name, brand_id, storage, color,
                    description, image_url, sell_price,
                    cost_price, stock, min_stock, status,
                    created_at, updated_at, updated_by
                ) VALUES (
                    :sku, :name, :brand_id, :storage, :color,
                    :description, :image_url, :sell_price,
                    0, 0, :min_stock, 'ACTIVE',
                    :now_utc, :now_utc, :updated_by
                )
            """),
            {
                "sku": sku,
                "name": name,
                "brand_id": brand_id,
                "storage": storage,
                "color": color,
                "description": description,
                "image_url": image_url,
                "sell_price": sell_price,
                "min_stock": min_stock,
                "now_utc": now_utc,
                "updated_by": updated_by,
            },
        )
        if result.lastrowid is None:
            raise RuntimeError("Không lấy được ID sản phẩm vừa tạo")
        return int(result.lastrowid)

    def update_details(
        self,
        *,
        product_id: int,
        name: str,
        sell_price: Decimal,
        min_stock: int,
        description: str | None,
        image_url: str | None,
        now_utc: datetime,
        updated_by: int | None,
    ) -> bool:
        """No stock, cost_price, SKU, brand, storage or color modification."""
        result = self.session.execute(
            text("""
                UPDATE products
                SET name = :name, sell_price = :sell_price,
                    min_stock = :min_stock, description = :description,
                    image_url = :image_url, updated_at = :now_utc,
                    updated_by = :updated_by
                WHERE id = :product_id
            """),
            {
                "product_id": product_id,
                "name": name,
                "sell_price": sell_price,
                "min_stock": min_stock,
                "description": description,
                "image_url": image_url,
                "now_utc": now_utc,
                "updated_by": updated_by,
            },
        )
        return result.rowcount == 1

    def set_status(
        self,
        *,
        product_id: int,
        status: str,
        now_utc: datetime,
        updated_by: int | None,
    ) -> bool:
        """Soft-discontinue/restore; business rules belong in US05 Service."""
        if status not in {"ACTIVE", "DISCONTINUED"}:
            raise ValueError("Trạng thái sản phẩm không hợp lệ")
        result = self.session.execute(
            text("""
                UPDATE products
                SET status = :status, updated_at = :now_utc,
                    updated_by = :updated_by
                WHERE id = :product_id
            """),
            {
                "product_id": product_id,
                "status": status,
                "now_utc": now_utc,
                "updated_by": updated_by,
            },
        )
        return result.rowcount == 1
