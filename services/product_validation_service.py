
"""US05 Task 27: validate SKU and variant uniqueness.

Use this validator inside the same authorized transaction as the write.
Database UNIQUE constraints remain the final protection.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from repositories.product_repository import ProductRepository


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    sku: str
    brand_id: int
    name: str
    storage: str
    color: str


class ProductValidationService:
    """Validate product identity without committing or writing data."""

    @staticmethod
    def _required_text(
        value: str,
        *,
        field: str,
        max_length: int,
        collapse_spaces: bool = True,
    ) -> str:
        if not isinstance(value, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin sản phẩm không hợp lệ.",
                {field: "Giá trị phải là chuỗi ký tự."},
            )

        normalized = (
            " ".join(value.split())
            if collapse_spaces
            else value.strip()
        )

        if not normalized or len(normalized) > max_length:
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin sản phẩm không hợp lệ.",
                {
                    field: (
                        f"Bắt buộc nhập, tối đa {max_length} ký tự."
                    )
                },
            )

        return normalized

    @staticmethod
    def _positive_id(value: int, *, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "Thông tin sản phẩm không hợp lệ.",
                {field: "ID phải là số nguyên dương."},
            )

        return value

    def validate_create(
        self,
        repository: ProductRepository,
        *,
        sku: str,
        brand_id: int,
        name: str,
        storage: str,
        color: str,
    ) -> ProductIdentity:
        """Check SKU and variant for a new product."""

        identity = ProductIdentity(
            sku=self._required_text(
                sku,
                field="sku",
                max_length=50,
                collapse_spaces=False,
            ),
            brand_id=self._positive_id(
                brand_id,
                field="brand_id",
            ),
            name=self._required_text(
                name,
                field="name",
                max_length=150,
            ),
            storage=self._required_text(
                storage,
                field="storage",
                max_length=50,
            ),
            color=self._required_text(
                color,
                field="color",
                max_length=50,
            ),
        )

        # Check SKU before checking the variant.
        if repository.get_by_sku(identity.sku) is not None:
            raise AppError(
                "PRODUCT_EXISTS",
                "SKU đã tồn tại.",
                {"sku": "SKU đã được sử dụng."},
            )

        # UNIQUE(brand_id, name, storage, color)
        if repository.find_variant(
            brand_id=identity.brand_id,
            name=identity.name,
            storage=identity.storage,
            color=identity.color,
        ) is not None:
            raise AppError(
                "PRODUCT_EXISTS",
                "Biến thể sản phẩm đã tồn tại.",
                {
                    "name": (
                        "Trùng hãng, tên, dung lượng và màu."
                    )
                },
            )

        return identity

    def validate_rename(
        self,
        repository: ProductRepository,
        *,
        product_id: int,
        new_name: str,
    ) -> str:
        """Lock the current product and exclude itself from duplicate lookup."""

        product_id = self._positive_id(
            product_id,
            field="product_id",
        )

        normalized_name = self._required_text(
            new_name,
            field="name",
            max_length=150,
        )

        # This must use the same Session as update_details().
        current = repository.get_by_id(
            product_id,
            for_update=True,
        )

        if current is None:
            raise AppError(
                "NOT_FOUND",
                "Không tìm thấy sản phẩm.",
            )

        duplicate = repository.find_variant(
            brand_id=int(current["brand_id"]),
            name=normalized_name,
            storage=current["storage"],
            color=current["color"],
            exclude_id=product_id,
        )

        if duplicate is not None:
            raise AppError(
                "PRODUCT_EXISTS",
                "Tên sản phẩm tạo thành biến thể trùng.",
                {
                    "name": (
                        "Trùng hãng, tên, dung lượng và màu."
                    )
                },
            )

        return normalized_name

    @staticmethod
    def translate_unique_error(
        exc: IntegrityError,
    ) -> AppError | None:
        """Convert product duplicate-key error 1062 into a safe AppError.

        Call after the failed transaction has rolled back.
        Return None for errors not related to the product UNIQUE keys.
        """

        original_args = getattr(
            exc.orig,
            "args",
            (),
        )

        if not original_args or original_args[0] != 1062:
            return None

        detail = (
            str(original_args[1]).lower()
            if len(original_args) > 1
            else ""
        )

        if "uq_products_sku" in detail:
            return AppError(
                "PRODUCT_EXISTS",
                "SKU đã tồn tại.",
                {"sku": "SKU đã được sử dụng."},
            )

        if "uq_products_variant" in detail:
            return AppError(
                "PRODUCT_EXISTS",
                "Biến thể sản phẩm đã tồn tại.",
                {
                    "name": (
                        "Trùng hãng, tên, dung lượng và màu."
                    )
                },
            )

        return None
