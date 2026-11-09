
"""US04 Task 22: kiểm tra quyền tại Service Layer.

Không tin user_id, role do client gửi. Role luôn lấy từ AuthService.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY, AuthSessionStore
from services.permissions import PERMISSION_MATRIX, Access, Permission, Role


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    """Quyền đã được xác thực cho một lần gọi Service."""

    permission: Permission
    role: Role
    scope: Access
    user_id: int | None

    def owner_filter_id(self) -> int | None:
        """OWN trả user_id để lọc SQL; ALL trả None.

        Chỉ dùng cho quyền dữ liệu OWN/ALL.
        Không sử dụng với quyền Y.
        """
        if self.scope == Access.OWN:
            if self.user_id is None:
                raise AppError(
                    "FORBIDDEN",
                    "Bạn không có quyền thao tác dữ liệu này.",
                )
            return self.user_id

        if self.scope == Access.ALL:
            return None

        raise AppError(
            "FORBIDDEN",
            "Quyền này không có phạm vi OWN/ALL.",
        )


class AuthorizationService:
    """Dùng chung cho các Service nghiệp vụ của Phone Shop."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
    ) -> None:
        self.auth_service = auth_service or AuthService(
            session_factory=session_factory
        )

    def require_permission(
        self,
        *,
        permission: Permission,
        session_store: AuthSessionStore | None = None,
    ) -> PermissionGrant:
        """Kiểm tra quyền và lấy role mới nhất từ database.

        Với OWN/ALL cho danh sách, Service gọi owner_filter_id()
        rồi áp dụng kết quả lọc cho truy vấn Repository.
        """
        if not isinstance(permission, Permission):
            raise AppError(
                "FORBIDDEN",
                "Quyền yêu cầu không hợp lệ.",
            )

        if (
            session_store is None
            or session_store.get(AUTH_SESSION_USER_ID_KEY) is None
        ):
            role = Role.GUEST
            user_id = None

        else:
            # Không lấy role từ client hoặc Session cache.
            user = self.auth_service.require_user(
                session_store=session_store,
            )

            try:
                role = Role(user.role)
            except ValueError as exc:
                raise AppError(
                    "FORBIDDEN",
                    "Vai trò tài khoản không hợp lệ.",
                ) from exc

            if role == Role.GUEST:
                raise AppError(
                    "FORBIDDEN",
                    "Vai trò tài khoản không hợp lệ.",
                )

            user_id = user.user_id

        scope = PERMISSION_MATRIX[permission][role]

        if scope == Access.DENY:
            if role == Role.GUEST:
                raise AppError(
                    "UNAUTHORIZED",
                    "Vui lòng đăng nhập để tiếp tục.",
                )

            raise AppError(
                "FORBIDDEN",
                "Bạn không có quyền thực hiện thao tác này.",
            )

        return PermissionGrant(
            permission=permission,
            role=role,
            scope=scope,
            user_id=user_id,
        )

    def require_resource_owner(
        self,
        *,
        permission: Permission,
        resource_owner_id: int,
        session_store: AuthSessionStore | None = None,
    ) -> PermissionGrant:
        """Cho phép bản ghi thuộc mình (OWN) hoặc quyền ALL."""
        grant = self.require_permission(
            permission=permission,
            session_store=session_store,
        )

        if (
            type(resource_owner_id) is not int
            or resource_owner_id <= 0
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "ID chủ sở hữu không hợp lệ.",
                {
                    "resource_owner_id":
                        "ID phải là số nguyên dương."
                },
            )

        if grant.scope == Access.ALL:
            return grant

        if (
            grant.scope == Access.OWN
            and grant.user_id == resource_owner_id
        ):
            return grant

        raise AppError(
            "FORBIDDEN",
            "Bạn không có quyền truy cập dữ liệu này.",
        )
