
"""US03 - Task 17: Xem và cập nhật hồ sơ của chính mình.

Không nhận user_id của tài khoản cần sửa từ client.
Chỉ cho phép sửa full_name, phone, address.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.base_service import BaseService
from utils.time_utils import Clock
from utils.validators import (
    validate_address,
    validate_full_name,
    validate_phone,
)


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Thông tin hồ sơ an toàn để trả cho giao diện."""

    user_id: int
    email: str
    full_name: str
    phone: str
    address: str | None
    role: str
    status: str
    created_at: datetime
    updated_at: datetime
    updated_by: int | None
    avatar_url: str | None = None


class ProfileService(BaseService):
    """Service xử lý hồ sơ cá nhân."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(clock=clock)
        self.session_factory = session_factory

        # Cùng một session_factory với ProfileService.
        # Integration Test sẽ chỉ truy cập phone_shop_test.
        self.auth_service = AuthService(
            session_factory=session_factory,
            clock=clock,
        )

    def _profile_from_row(
        self,
        row: dict | None,
        session_store: AuthSessionStore,
    ) -> ProfileResult:
        """Kiểm tra dữ liệu và tạo kết quả hồ sơ."""

        if row is None:
            self.auth_service.logout(
                session_store=session_store,
            )
            raise AppError(
                "UNAUTHORIZED",
                "Phiên đăng nhập không còn hợp lệ.",
            )

        if row["status"] != "ACTIVE":
            self.auth_service.logout(
                session_store=session_store,
            )
            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa hoặc không còn hoạt động.",
            )

        return ProfileResult(
            user_id=int(row["id"]),
            email=row["email"],
            full_name=row["full_name"],
            phone=row["phone"],
            address=row["address"],
            role=row["role"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
            avatar_url=row.get("avatar_url"),
        )

    def get_my_profile(
        self,
        *,
        session_store: AuthSessionStore,
    ) -> ProfileResult:
        """Xem hồ sơ của tài khoản đang đăng nhập."""

        # 1. Tải và kiểm tra danh tính từ server session.
        current_user = self.auth_service.require_user(
            session_store=session_store,
        )

        # 2. Chỉ truy vấn chính ID vừa được xác thực.
        with self.session_factory() as session:
            repository = UserRepository(session)
            row = repository.get_by_id(current_user.user_id)

        # 3. Không trả mật khẩu hoặc password_hash.
        return self._profile_from_row(
            row,
            session_store,
        )

    def update_my_profile(
        self,
        *,
        session_store: AuthSessionStore,
        full_name: str,
        phone: str,
        address: str | None,
    ) -> ProfileResult:
        """Cập nhật hồ sơ của chính tài khoản đăng nhập."""

        # 1. Xác thực tài khoản và trạng thái ACTIVE.
        current_user = self.auth_service.require_user(
            session_store=session_store,
        )

        # 2. Validate đúng ba trường được phép sửa.
        normalized_name = validate_full_name(full_name)
        normalized_phone = validate_phone(phone)
        normalized_address = validate_address(address)

        # 3. Thời gian UTC từ Clock chung của dự án.
        now_utc = self.current_time()

        # 4. Dùng một transaction cho kiểm tra và cập nhật.
        with (
            self.session_factory() as session,
            session.begin(),
        ):
            repository = UserRepository(session)

            # Khóa bản ghi để kiểm tra lại ACTIVE trước UPDATE.
            existing = repository.get_by_id(
                current_user.user_id,
                for_update=True,
            )

            self._profile_from_row(
                existing,
                session_store,
            )

            # 5. Chỉ cập nhật tài khoản đã xác thực.
            # updated_by cũng là chính current_user.user_id.
            repository.update_own_profile(
                user_id=current_user.user_id,
                full_name=normalized_name,
                phone=normalized_phone,
                address=normalized_address,
                now_utc=now_utc,
            )

            # 6. Đọc lại bản ghi trong cùng transaction.
            updated_row = repository.get_by_id(
                current_user.user_id,
            )

            result = self._profile_from_row(
                updated_row,
                session_store,
            )

        # Transaction commit thành công trước khi trả kết quả.
        return result
