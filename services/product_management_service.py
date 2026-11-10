
"""US05 Task 29: product lifecycle, search, status filter and low stock."""

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.product_repository import ProductRepository
from repositories.product_search_repository import ProductSearchRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock


class ProductManagementService(BaseService):
    """Customer-safe search, authorized admin search and status changes."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        clock: Clock | None = None,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        product_repository_factory: Callable[
            [Session], ProductRepository
        ] = ProductRepository,
        search_repository_factory: Callable[
            [Session], ProductSearchRepository
        ] = ProductSearchRepository,
    ) -> None:
        super().__init__(clock=clock)

        self.session_factory = session_factory

        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
            clock=clock,
        )

        self.protected_actions = (
            protected_actions
            or ProtectedActionService(
                session_factory=session_factory,
                auth_service=self.auth_service,
            )
        )

        self.product_repository_factory = product_repository_factory
        self.search_repository_factory = search_repository_factory

    @staticmethod
    def _positive_id(
        value: object,
        field: str = "id",
    ) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "ID không hợp lệ.",
                {field: "ID phải là số nguyên dương."},
            )

        return value

    @staticmethod
    def _price(
        value: Decimal | str | int | None,
        field: str,
    ) -> Decimal | None:
        if value is None:
            return None

        if (
            type(value) is bool
            or not isinstance(value, (str, int, Decimal))
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Khoảng giá không hợp lệ.",
                {field: "Giá phải là số."},
            )

        try:
            price = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise AppError(
                "VALIDATION_ERROR",
                "Khoảng giá không hợp lệ.",
                {field: "Giá phải là số."},
            ) from exc

        if (
            not price.is_finite()
            or price < 0
            or price > Decimal("999999999.99")
            or price != price.quantize(Decimal("0.01"))
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Khoảng giá không hợp lệ.",
                {
                    field: (
                        "Giá từ 0, tối đa hai chữ số thập phân."
                    )
                },
            )

        return price

    @classmethod
    def _search_args(
        cls,
        *,
        keyword: str | None,
        brand_id: int | None,
        min_price: Decimal | str | int | None,
        max_price: Decimal | str | int | None,
        sort_by: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:

        if (
            keyword is not None
            and not isinstance(keyword, str)
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Từ khóa không hợp lệ.",
                {"keyword": "Phải là chuỗi ký tự."},
            )

        normalized_keyword = (
            " ".join(keyword.split())
            if keyword
            else None
        )

        if (
            normalized_keyword
            and len(normalized_keyword) > 100
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Từ khóa quá dài.",
                {"keyword": "Tối đa 100 ký tự."},
            )

        if brand_id is not None:
            cls._positive_id(brand_id, "brand_id")

        min_value = cls._price(min_price, "min_price")
        max_value = cls._price(max_price, "max_price")

        if (
            min_value is not None
            and max_value is not None
            and min_value > max_value
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Khoảng giá không hợp lệ.",
                {
                    "max_price": (
                        "Giá trên phải lớn hơn hoặc bằng giá dưới."
                    )
                },
            )

        if (
            not isinstance(sort_by, str)
            or sort_by not in ProductSearchRepository._SORTS
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Sắp xếp không hợp lệ.",
                {"sort_by": "Kiểu sắp xếp không hợp lệ."},
            )

        if (
            type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Phân trang không hợp lệ.",
                {"limit": "Giới hạn từ 1 đến 100."},
            )

        if type(offset) is not int or offset < 0:
            raise AppError(
                "VALIDATION_ERROR",
                "Phân trang không hợp lệ.",
                {
                    "offset": (
                        "Offset phải là số nguyên không âm."
                    )
                },
            )

        return {
            "keyword": normalized_keyword or None,
            "brand_id": brand_id,
            "min_price": min_value,
            "max_price": max_value,
            "sort_by": sort_by,
            "limit": limit,
            "offset": offset,
        }

    def search_public(
        self,
        *,
        keyword: str | None = None,
        brand_id: int | None = None,
        min_price: Decimal | str | int | None = None,
        max_price: Decimal | str | int | None = None,
        only_in_stock: bool = False,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        if type(only_in_stock) is not bool:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc không hợp lệ.",
                {
                    "only_in_stock": (
                        "Phải là true hoặc false."
                    )
                },
            )

        params = self._search_args(
            keyword=keyword,
            brand_id=brand_id,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        with self.session_factory() as session:
            return self.search_repository_factory(
                session
            ).search_public(
                **params,
                only_in_stock=only_in_stock,
            )

    def search_admin(
        self,
        *,
        session_store: AuthSessionStore,
        keyword: str | None = None,
        brand_id: int | None = None,
        min_price: Decimal | str | int | None = None,
        max_price: Decimal | str | int | None = None,
        status: str = "ALL",
        low_stock: bool = False,
        sort_by: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = self._search_args(
            keyword=keyword,
            brand_id=brand_id,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            limit=limit,
            offset=offset,
        )

        if (
            not isinstance(status, str)
            or status not in {
                "ALL", "ACTIVE", "DISCONTINUED"
            }
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Trạng thái không hợp lệ.",
                {
                    "status": (
                        "Chọn ALL, ACTIVE hoặc DISCONTINUED."
                    )
                },
            )

        if type(low_stock) is not bool:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc không hợp lệ.",
                {"low_stock": "Phải là true hoặc false."},
            )

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_PRODUCTS,
            action=lambda session: (
                self.search_repository_factory(
                    session
                ).search_admin(
                    **params,
                    status=(
                        None if status == "ALL" else status
                    ),
                    low_stock=low_stock,
                )
            ),
        )

    def set_status(
        self,
        *,
        session_store: AuthSessionStore,
        product_id: int,
        status: str,
    ) -> dict[str, Any]:
        """Idempotent transition: no delete or inventory modification."""

        self._positive_id(product_id)

        if (
            not isinstance(status, str)
            or status not in {
                "ACTIVE", "DISCONTINUED"
            }
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Trạng thái không hợp lệ.",
                {
                    "status": (
                        "Chọn ACTIVE hoặc DISCONTINUED."
                    )
                },
            )

        def action(session: Session) -> dict[str, Any]:
            repo = self.product_repository_factory(session)

            current = repo.get_by_id(
                product_id,
                for_update=True,
            )

            if current is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm.",
                )

            # Cùng trạng thái: không ghi lại hoặc đổi audit.
            if current["status"] == status:
                return current

            # updated_by luôn lấy từ phiên xác thực.
            actor = self.auth_service.require_user(
                session_store=session_store,
            )

            changed = repo.set_status(
                product_id=product_id,
                status=status,
                now_utc=self.current_time(),
                updated_by=actor.user_id,
            )

            if not changed:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm.",
                )

            result = repo.get_by_id(product_id)

            if result is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy sản phẩm.",
                )

            return result

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_PRODUCTS,
            action=action,
        )

    @classmethod
    def require_active_for_sale(
        cls,
        *,
        repository: ProductRepository,
        product_id: int,
    ) -> dict[str, Any]:
        """Hook for US10: call inside the same order transaction."""

        cls._positive_id(product_id)

        product = repository.get_by_id(
            product_id,
            for_update=True,
        )

        if product is None:
            raise AppError(
                "NOT_FOUND",
                "Không tìm thấy sản phẩm.",
            )

        if product["status"] != "ACTIVE":
            raise AppError(
                "PRODUCT_DISCONTINUED",
                "Sản phẩm đã ngừng kinh doanh.",
            )

        return product
