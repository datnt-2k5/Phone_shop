
"""US05 Task 30: tạo sản phẩm và đọc danh sách hãng cho Admin UI."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.product_repository import ProductRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from services.permissions import Permission
from services.product_edit_service import ProductEditService
from services.product_validation_service import ProductValidationService
from services.protected_action_service import ProtectedActionService
from utils.time_utils import Clock


class ProductCreateService(BaseService):
    """Chỉ Admin/Super Admin được tạo sản phẩm."""

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

    def list_brands(
        self,
        *,
        session_store: AuthSessionStore,
    ) -> list[dict[str, Any]]:
        """Chỉ đọc hãng đang có; Catalog CRUD sẽ thuộc US06."""

        def action(session: Session) -> list[dict[str, Any]]:
            rows = session.execute(
                text("""
                    SELECT id, name
                    FROM brands
                    ORDER BY name ASC, id ASC
                """)
            ).mappings().all()

            return [dict(row) for row in rows]

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.MANAGE_PRODUCTS,
            action=action,
        )

    def create(
        self,
        *,
        session_store: AuthSessionStore,
        sku: str,
        name: str,
        brand_id: int,
        storage: str,
        color: str,
        sell_price: Decimal | str | int,
        min_stock: int = 0,
        description: str | None = None,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        """Tạo SKU mới; tồn và giá vốn ban đầu luôn bằng 0."""

        def action(session: Session) -> dict[str, Any]:
            repo = self.repository_factory(session)

            identity = self.validator.validate_create(
                repo,
                sku=sku,
                name=name,
                brand_id=brand_id,
                storage=storage,
                color=color,
            )

            price = ProductEditService._validate_price(
                sell_price
            )
            minimum = ProductEditService._validate_min_stock(
                min_stock
            )
            detail = ProductEditService._validate_description(
                description
            )
            image = ProductEditService._validate_image_url(
                image_url
            )

            # Kiểm tra hãng trong cùng transaction tạo sản phẩm.
            brand_exists = session.execute(
                text("""
                    SELECT id
                    FROM brands
                    WHERE id = :brand_id
                    LIMIT 1
                """),
                {"brand_id": identity.brand_id},
            ).scalar_one_or_none()

            if brand_exists is None:
                raise AppError(
                    "VALIDATION_ERROR",
                    "Hãng sản phẩm không tồn tại.",
                    {"brand_id": "Hãy chọn hãng hợp lệ."},
                )

            # Không nhận updated_by do client tự khai báo.
            actor = self.auth_service.require_user(
                session_store=session_store,
            )

            product_id = repo.create(
                sku=identity.sku,
                name=identity.name,
                brand_id=identity.brand_id,
                storage=identity.storage,
                color=identity.color,
                sell_price=price,
                min_stock=minimum,
                description=detail,
                image_url=image,
                now_utc=self.current_time(),
                updated_by=actor.user_id,
            )

            product = repo.get_by_id(product_id)

            if product is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không đọc được sản phẩm vừa tạo.",
                )

            return product

        try:
            return self.protected_actions.run_allowed(
                session_store=session_store,
                permission=Permission.MANAGE_PRODUCTS,
                action=action,
            )
        except IntegrityError as exc:
            # Transaction đã rollback khi run_allowed() thoát.
            mapped = self.validator.translate_unique_error(exc)

            if mapped is not None:
                raise mapped from exc

            raise
