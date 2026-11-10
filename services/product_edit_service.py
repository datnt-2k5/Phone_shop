
"""US05 Task 28: sửa thông tin sản phẩm an toàn.

Chỉ sửa tên, mô tả, giá bán, URL ảnh và ngưỡng tồn.
Không nhận hay cập nhật stock/cost_price từ người dùng.
"""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.product_validation_service import ProductValidationService
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock


class ProductEditService(BaseService):
    """Service sửa chi tiết sản phẩm với quyền MANAGE_PRODUCTS."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        repository_factory: Callable[
            [Session], ProductRepository
        ] = ProductRepository,
    ) -> None:
        super().__init__(clock=clock)
        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
            clock=clock,
        )
        self.protected_actions = (
            protected_actions
            if protected_actions is not None
            else ProtectedActionService(
                session_factory=session_factory,
                auth_service=self.auth_service,
            )
        )
        self.repository_factory = repository_factory
        self.validator = ProductValidationService()

    @staticmethod
    def _validate_price(value: object) -> Decimal:
        """Giá bán dương, hữu hạn và tối đa hai chữ số thập phân."""

        if isinstance(value, bool) or not isinstance(
            value, (str, int, Decimal)
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá bán không hợp lệ.",
                {"sell_price": "Giá bán phải là số hợp lệ."},
            )

        try:
            price = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá bán không hợp lệ.",
                {"sell_price": "Không thể chuyển thành số."},
            ) from None

        if (
            not price.is_finite()
            or price <= 0
            or price > Decimal("999999999.99")
            or price != price.quantize(Decimal("0.01"))
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Giá bán không hợp lệ.",
                {
                    "sell_price": (
                        "Giá bán phải lớn hơn 0 và có tối đa "
                        "hai chữ số thập phân."
                    )
                },
            )

        return price.quantize(Decimal("0.01"))

    @staticmethod
    def _validate_min_stock(value: object) -> int:
        if (
            type(value) is not int
            or value < 0
            or value > 2_147_483_647
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Ngưỡng tồn không hợp lệ.",
                {
                    "min_stock": (
                        "Ngưỡng tồn phải là số nguyên không âm."
                    )
                },
            )
        return value

    @staticmethod
    def _validate_description(value: object) -> str | None:
        if value is None:
            return None

        if not isinstance(value, str) or len(value) > 4000:
            raise AppError(
                "VALIDATION_ERROR",
                "Mô tả không hợp lệ.",
                {
                    "description": (
                        "Mô tả phải là chuỗi tối đa 4000 ký tự."
                    )
                },
            )

        return value.strip() or None

    @staticmethod
    def _validate_image_url(value: object) -> str | None:
        """Chỉ chấp nhận HTTPS/HTTP hoặc đường dẫn nội bộ an toàn."""

        if value is None:
            return None

        if not isinstance(value, str):
            raise AppError(
                "VALIDATION_ERROR",
                "Đường dẫn ảnh không hợp lệ.",
                {"image_url": "Đường dẫn ảnh phải là chuỗi."},
            )

        image_url = value.strip()

        if not image_url:
            return None

        if len(image_url) > 255 or any(
            character.isspace() for character in image_url
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Đường dẫn ảnh không hợp lệ.",
                {
                    "image_url": (
                        "Đường dẫn tối đa 255 ký tự, "
                        "không chứa khoảng trắng."
                    )
                },
            )

        parsed = urlsplit(image_url)

        is_web_url = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )

        is_local_path = (
            image_url.startswith("/")
            and not image_url.startswith("//")
            and not parsed.scheme
            and ".." not in parsed.path.split("/")
            and not parsed.query
            and not parsed.fragment
        )

        if not (is_web_url or is_local_path):
            raise AppError(
                "VALIDATION_ERROR",
                "Đường dẫn ảnh không hợp lệ.",
                {
                    "image_url": (
                        "Chỉ dùng URL http(s) hoặc "
                        "đường dẫn nội bộ bắt đầu bằng /."
                    )
                },
            )

        return image_url

    def update_details(
        self,
        *,
        session_store: AuthSessionStore,
        product_id: int,
        name: str,
        description: str | None,
        sell_price: Decimal | str | int,
        image_url: str | None,
        min_stock: int,
    ) -> dict[str, Any]:
        """Sửa sản phẩm trong transaction đã xác thực và phân quyền.

        Các trường sku, brand_id, storage, color, stock,
        cost_price không nằm trong API sửa sản phẩm.
        """

        def action(session: Session) -> dict[str, Any]:
            repository = self.repository_factory(session)

            # Kiểm tra ID, chuẩn hóa tên và phát hiện trùng.
            # validate_rename() khóa sản phẩm bằng FOR UPDATE.
            normalized_name = self.validator.validate_rename(
                repository,
                product_id=product_id,
                new_name=name,
            )

            normalized_description = self._validate_description(
                description
            )
            normalized_price = self._validate_price(sell_price)
            normalized_image = self._validate_image_url(image_url)
            normalized_min_stock = self._validate_min_stock(
                min_stock
            )

            # user_id lấy từ AuthService, không nhận từ client.
            actor = self.auth_service.require_user(
                session_store=session_store,
            )

            updated = repository.update_details(
                product_id=product_id,
                name=normalized_name,
                description=normalized_description,
                sell_price=normalized_price,
                image_url=normalized_image,
                min_stock=normalized_min_stock,
                now_utc=self.current_time(),
                updated_by=actor.user_id,
            )

            if not updated:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm cần sửa.",
                )

            result = repository.get_by_id(product_id)

            if result is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm sau cập nhật.",
                )

            return result

        try:
            return self.protected_actions.run_allowed(
                session_store=session_store,
                permission=Permission.MANAGE_PRODUCTS,
                action=action,
            )
        except IntegrityError as exc:
            # run_allowed() đã kết thúc transaction bằng rollback
            # trước khi lỗi được xử lý ở đây.
            mapped = self.validator.translate_unique_error(exc)

            if mapped is not None:
                raise mapped from exc

            raise
