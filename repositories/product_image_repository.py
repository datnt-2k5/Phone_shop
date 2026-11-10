
"""Only change product image and audit columns; no commit or permission check."""

from datetime import datetime

from sqlalchemy import text

from repositories.product_repository import ProductRepository


class ProductImageRepository(ProductRepository):
    def update_image_url(
        self,
        *,
        product_id: int,
        image_url: str,
        now_utc: datetime,
        updated_by: int,
    ) -> bool:
        result = self.session.execute(
            text("""
                UPDATE products
                SET image_url = :image_url,
                    updated_at = :now_utc,
                    updated_by = :updated_by
                WHERE id = :product_id
            """),
            {
                "product_id": product_id,
                "image_url": image_url,
                "now_utc": now_utc,
                "updated_by": updated_by,
            },
        )
        return result.rowcount == 1
