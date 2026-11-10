
"""US05 Task 29: product search and low-stock SQL queries (no auth/commit)."""

from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import text

from repositories.product_repository import ProductRepository


class ProductSearchRepository(ProductRepository):
    """The public projection deliberately omits cost and exact stock."""

    _SORTS: ClassVar[dict[str, str]] = {
        "newest": "p.id DESC",
        "price_asc": "p.sell_price ASC, p.id DESC",
        "price_desc": "p.sell_price DESC, p.id DESC",
        "name_asc": "p.name ASC, p.id DESC",
    }


    @staticmethod
    def _like_pattern(keyword: str) -> str:
        """Treat user-entered percent/underscore as literal characters."""
        escaped = (
            keyword.replace("!", "!!")
            .replace("%", "!%")
            .replace("_", "!_")
        )
        return f"%{escaped}%"

    def _search(
        self,
        *,
        public: bool,
        keyword: str | None,
        brand_id: int | None,
        min_price: Decimal | None,
        max_price: Decimal | None,
        only_in_stock: bool,
        status: str | None,
        low_stock: bool,
        sort_by: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        # Service validates filters; Repository also keeps SQL sort safe.
        page = self._page_params(limit, offset)

        if sort_by not in self._SORTS:
            raise ValueError("Kiểu sắp xếp không hợp lệ")

        filters: list[str] = []
        params: dict[str, Any] = {}

        if public:
            filters.append("p.status = 'ACTIVE'")
        elif status is not None:
            filters.append("p.status = :status")
            params["status"] = status

        if keyword:
            filters.append(
                "(p.sku LIKE :keyword ESCAPE '!' "
                "OR p.name LIKE :keyword ESCAPE '!' "
                "OR b.name LIKE :keyword ESCAPE '!')"
            )
            params["keyword"] = self._like_pattern(keyword)

        if brand_id is not None:
            filters.append("p.brand_id = :brand_id")
            params["brand_id"] = brand_id

        if min_price is not None:
            filters.append("p.sell_price >= :min_price")
            params["min_price"] = min_price

        if max_price is not None:
            filters.append("p.sell_price <= :max_price")
            params["max_price"] = max_price

        if only_in_stock:
            filters.append("p.stock > 0")

        if low_stock:
            filters.append("p.stock <= p.min_stock")

        where_sql = (
            " WHERE " + " AND ".join(filters)
            if filters
            else ""
        )

        from_sql = (
            " FROM products AS p "
            "JOIN brands AS b ON b.id = p.brand_id"
        )

        columns = (
            self._PUBLIC_COLUMNS
            if public
            else self._ADMIN_COLUMNS
            + ", (p.stock <= p.min_stock) AS is_low_stock"
        )

        rows = self.session.execute(
            text(
                f"SELECT {columns}{from_sql}{where_sql} "
                f"ORDER BY {self._SORTS[sort_by]} "
                "LIMIT :limit OFFSET :offset"
            ),
            {**params, **page},
        ).mappings().all()

        total = self.session.execute(
            text(
                f"SELECT COUNT(*){from_sql}{where_sql}"
            ),
            params,
        ).scalar_one()

        return {
            "items": [dict(row) for row in rows],
            "total": int(total),
            "limit": limit,
            "offset": offset,
        }

    def search_public(
        self,
        *,
        keyword: str | None = None,
        brand_id: int | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        only_in_stock: bool = False,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._search(
            public=True,
            keyword=keyword,
            brand_id=brand_id,
            min_price=min_price,
            max_price=max_price,
            only_in_stock=only_in_stock,
            status=None,
            low_stock=False,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

    def search_admin(
        self,
        *,
        keyword: str | None = None,
        brand_id: int | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        status: str | None = None,
        low_stock: bool = False,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._search(
            public=False,
            keyword=keyword,
            brand_id=brand_id,
            min_price=min_price,
            max_price=max_price,
            only_in_stock=False,
            status=status,
            low_stock=low_stock,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )
