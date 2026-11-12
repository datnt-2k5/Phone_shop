
"""Task 48 / US09-T01: customer cart in Flet Page Session.

The cart stores product IDs and quantities only.
Product prices and availability come from the database
when displayed or checked out.

No database writes and no checkout in this task.
"""

from typing import Any

from models.app_error import AppError
from services.auth_session import (
    CART_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    AuthSessionStore,
)

MAX_CART_LINES = 20


class CartSession:
    """A cart isolated to one Flet server-side session."""

    def __init__(self, store: AuthSessionStore) -> None:
        self.store = store

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                f"{field} phải là số nguyên dương.",
            )
        return value

    def items(self) -> list[dict[str, int]]:
        """Return a validated copy of the current cart."""
        raw = self.store.get(CART_SESSION_KEY)

        if raw is None:
            return []

        if not isinstance(raw, list) or len(raw) > MAX_CART_LINES:
            raise AppError(
                "CART_INVALID",
                "Dữ liệu giỏ hàng không hợp lệ.",
            )

        result = []
        seen = set()

        for row in raw:
            if (
                type(row) is not dict
                or set(row) != {"product_id", "quantity"}
            ):
                raise AppError(
                    "CART_INVALID",
                    "Dữ liệu giỏ hàng không hợp lệ.",
                )

            product_id = row["product_id"]
            quantity = row["quantity"]

            if (
                type(product_id) is not int
                or product_id <= 0
                or type(quantity) is not int
                or quantity <= 0
                or product_id in seen
            ):
                raise AppError(
                    "CART_INVALID",
                    "Dữ liệu giỏ hàng không hợp lệ.",
                )

            seen.add(product_id)
            result.append(
                {
                    "product_id": product_id,
                    "quantity": quantity,
                }
            )

        return result

    def _save(self, items: list[dict[str, int]]) -> None:
        """Persist a new cart and invalidate an old checkout key."""
        if items:
            self.store.set(
                CART_SESSION_KEY,
                [dict(row) for row in items],
            )
        else:
            self.store.remove(CART_SESSION_KEY)

        # A changed cart must not reuse an old checkout key.
        if self.store.get(CHECKOUT_SESSION_KEY) is not None:
            self.store.remove(CHECKOUT_SESSION_KEY)

    def add(
        self,
        product_id: int,
        quantity: int = 1,
    ) -> list[dict[str, int]]:
        """Add a product or increase its existing quantity."""
        self._positive_int(product_id, "ID sản phẩm")
        self._positive_int(quantity, "Số lượng")

        items = self.items()

        for row in items:
            if row["product_id"] == product_id:
                row["quantity"] += quantity
                self._save(items)
                return self.items()

        if len(items) >= MAX_CART_LINES:
            raise AppError(
                "CART_LIMIT_EXCEEDED",
                "Giỏ hàng chỉ được chứa tối đa 20 sản phẩm khác nhau.",
            )

        items.append(
            {
                "product_id": product_id,
                "quantity": quantity,
            }
        )
        self._save(items)

        return self.items()

    def set_quantity(
        self,
        product_id: int,
        quantity: int,
    ) -> list[dict[str, int]]:
        """Change the quantity of an existing cart line."""
        self._positive_int(product_id, "ID sản phẩm")
        self._positive_int(quantity, "Số lượng")

        items = self.items()

        for row in items:
            if row["product_id"] == product_id:
                if row["quantity"] != quantity:
                    row["quantity"] = quantity
                    self._save(items)

                return self.items()

        raise AppError(
            "CART_ITEM_NOT_FOUND",
            "Sản phẩm không có trong giỏ hàng.",
        )

    def remove(self, product_id: int) -> bool:
        """Remove one product without affecting other items."""
        self._positive_int(product_id, "ID sản phẩm")

        items = self.items()
        remaining = [
            row
            for row in items
            if row["product_id"] != product_id
        ]

        if len(remaining) == len(items):
            return False

        self._save(remaining)
        return True

    def clear(self) -> None:
        """Clear the cart, if it contains any items."""
        if self.items():
            self._save([])

    def line_count(self) -> int:
        """Number of distinct products, not total quantity."""
        return len(self.items())

    def total_quantity(self) -> int:
        return sum(row["quantity"] for row in self.items())

    def has_product(self, product_id: int) -> bool:
        self._positive_int(product_id, "ID sản phẩm")

        return any(
            row["product_id"] == product_id
            for row in self.items()
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a safe cart snapshot for later checkout work."""
        rows = self.items()

        return {
            "items": rows,
            "line_count": len(rows),
            "total_quantity": sum(
                row["quantity"]
                for row in rows
            ),
        }
