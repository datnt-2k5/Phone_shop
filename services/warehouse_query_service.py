
"""Task 39 / US07: authorized read-only warehouse history and stock lists."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.warehouse_query_repository import WarehouseQueryRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService

MOVEMENT_TYPES = frozenset({"IMPORT", "SALE", "CANCEL_RESTORE", "ADJUST"})
INVENTORY_LEVELS = frozenset({"ALL", "ALERT", "LOW", "OUT"})


class WarehouseQueryService:
    """Admin-only warehouse reads; no stock or receipt mutations."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
        protected_actions: ProtectedActionService | None = None,
        repository_factory: Callable[
            [Session], WarehouseQueryRepository
        ] = WarehouseQueryRepository,
    ) -> None:
        auth = auth_service or AuthService(session_factory=session_factory)
        self.protected_actions = (
            protected_actions
            if protected_actions is not None
            else ProtectedActionService(
                session_factory=session_factory,
                auth_service=auth,
            )
        )
        self.repository_factory = repository_factory

    @staticmethod
    def _page(limit: object, offset: object) -> None:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AppError(
                "VALIDATION_ERROR",
                "Giới hạn phân trang phải từ 1 đến 100.",
                {"limit": "Phải là số nguyên từ 1 đến 100."},
            )
        if type(offset) is not int or offset < 0:
            raise AppError(
                "VALIDATION_ERROR",
                "Vị trí phân trang không hợp lệ.",
                {"offset": "Phải là số nguyên không âm."},
            )

    @staticmethod
    def _positive_id(value: object, field: str) -> int:
        if type(value) is not int or value <= 0:
            raise AppError(
                "VALIDATION_ERROR",
                "ID không hợp lệ.",
                {field: "Phải là số nguyên dương."},
            )
        return value

    @staticmethod
    def _choice(
        value: object,
        *,
        field: str,
        allowed: frozenset[str],
    ) -> str:
        if type(value) is not str:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc không hợp lệ.",
                {field: "Phải là chuỗi."},
            )
        cleaned = value.strip().upper()
        if cleaned not in allowed:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc không hợp lệ.",
                {field: "Giá trị không được hỗ trợ."},
            )
        return cleaned

    def list_receipts(
        self,
        *,
        session_store: AuthSessionStore,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._page(limit, offset)
        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.VIEW_INVENTORY,
            action=lambda session: self.repository_factory(
                session
            ).list_receipts(limit=limit, offset=offset),
        )

    def get_receipt(
        self,
        *,
        session_store: AuthSessionStore,
        receipt_id: int,
    ) -> dict[str, Any]:
        receipt_id = self._positive_id(receipt_id, "receipt_id")

        def action(session: Session) -> dict[str, Any]:
            repo = self.repository_factory(session)
            receipt = repo.get_receipt(receipt_id)
            if receipt is None:
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy phiếu nhập.",
                )
            return {
                "receipt": receipt,
                "items": repo.list_receipt_items(receipt_id),
            }

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.VIEW_INVENTORY,
            action=action,
        )

    def list_movements(
        self,
        *,
        session_store: AuthSessionStore,
        product_id: int | None = None,
        movement_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._page(limit, offset)
        if product_id is not None:
            product_id = self._positive_id(
                product_id, "product_id"
            )
        if movement_type is not None:
            movement_type = self._choice(
                movement_type,
                field="movement_type",
                allowed=MOVEMENT_TYPES,
            )

        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.VIEW_INVENTORY,
            action=lambda session: self.repository_factory(
                session
            ).list_movements(
                product_id=product_id,
                movement_type=movement_type,
                limit=limit,
                offset=offset,
            ),
        )

    def list_inventory(
        self,
        *,
        session_store: AuthSessionStore,
        level: str = "ALL",
        include_discontinued: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        self._page(limit, offset)
        level = self._choice(
            level,
            field="level",
            allowed=INVENTORY_LEVELS,
        )
        if type(include_discontinued) is not bool:
            raise AppError(
                "VALIDATION_ERROR",
                "Bộ lọc trạng thái không hợp lệ.",
                {
                    "include_discontinued": (
                        "Phải là True hoặc False."
                    )
                },
            )
        return self.protected_actions.run_allowed(
            session_store=session_store,
            permission=Permission.VIEW_INVENTORY,
            action=lambda session: self.repository_factory(
                session
            ).list_inventory(
                level=level,
                include_discontinued=include_discontinued,
                limit=limit,
                offset=offset,
            ),
        )
