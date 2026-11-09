
"""US04 Task 24: transactional guard for protected database actions.

Guard locks the acting user's row in the *same* SQL transaction as the
callback. Future services must use the supplied Session for all writes.
"""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.authorization_service import PermissionGrant
from services.permissions import PERMISSION_MATRIX, Access, Permission, Role

ResultT = TypeVar("ResultT")


class ProtectedActionService:
    """Recheck ACTIVE/role before a protected database action."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
        )

    def _locked_grant(
        self,
        *,
        session: Session,
        session_store: AuthSessionStore,
        permission: Permission,
    ) -> PermissionGrant:
        if not isinstance(permission, Permission):
            raise AppError(
                "FORBIDDEN",
                "Quyền yêu cầu không hợp lệ.",
            )

        # Xác thực lại Session, ACTIVE và role từ MariaDB.
        current = self.auth_service.require_user(
            session_store=session_store,
        )

        # Khóa bản ghi trong cùng transaction với hành động.
        record = UserRepository(session).get_by_id(
            current.user_id,
            for_update=True,
        )

        if record is None:
            self.auth_service.logout(
                session_store=session_store,
            )
            raise AppError(
                "UNAUTHORIZED",
                "Phiên đăng nhập không còn hợp lệ.",
            )

        if record["status"] != "ACTIVE":
            self.auth_service.logout(
                session_store=session_store,
            )
            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa.",
            )

        try:
            role = Role(record["role"])
        except ValueError as exc:
            raise AppError(
                "FORBIDDEN",
                "Vai trò không hợp lệ.",
            ) from exc

        if role == Role.GUEST:
            raise AppError(
                "FORBIDDEN",
                "Vai trò không hợp lệ.",
            )

        scope = PERMISSION_MATRIX[permission][role]

        if scope == Access.DENY:
            raise AppError(
                "FORBIDDEN",
                "Không có quyền thực hiện thao tác này.",
            )

        return PermissionGrant(
            permission=permission,
            role=role,
            scope=scope,
            user_id=int(record["id"]),
        )

    def run_allowed(
        self,
        *,
        session_store: AuthSessionStore,
        permission: Permission,
        action: Callable[[Session], ResultT],
    ) -> ResultT:
        """Thao tác quyền Y: đặt hàng, quản lý sản phẩm..."""

        with self.session_factory() as session, session.begin():
            grant = self._locked_grant(
                session=session,
                session_store=session_store,
                permission=permission,
            )

            if grant.scope != Access.ALLOW:
                raise AppError(
                    "FORBIDDEN",
                    "Thao tác yêu cầu quyền Y.",
                )

            return action(session)

    def run_for_owner(
        self,
        *,
        session_store: AuthSessionStore,
        permission: Permission,
        resource_owner_id: int,
        action: Callable[[Session], ResultT],
    ) -> ResultT:
        """Thao tác trên dữ liệu thuộc OWN hoặc ALL.

        resource_owner_id phải được Backend đọc từ database.
        Không nhận giá trị này như bằng chứng sở hữu từ client.
        """

        with self.session_factory() as session, session.begin():
            grant = self._locked_grant(
                session=session,
                session_store=session_store,
                permission=permission,
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

            if grant.scope == Access.ALL or (
                grant.scope == Access.OWN
                and grant.user_id == resource_owner_id
            ):
                return action(session)

            raise AppError(
                "FORBIDDEN",
                "Dữ liệu không thuộc phạm vi được phép.",
            )

    def run_scoped_list(
        self,
        *,
        session_store: AuthSessionStore,
        permission: Permission,
        action: Callable[[Session, int | None], ResultT],
    ) -> ResultT:
        """Danh sách OWN có lọc user_id; ALL không lọc chủ sở hữu."""

        with self.session_factory() as session, session.begin():
            grant = self._locked_grant(
                session=session,
                session_store=session_store,
                permission=permission,
            )

            # owner_filter_id() từ Task 22 sẽ từ chối
            # quyền Y nếu dùng sai cho danh sách OWN/ALL.
            owner_id = grant.owner_filter_id()

            return action(session, owner_id)
