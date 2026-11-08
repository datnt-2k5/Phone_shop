
"""Auth Service: đăng ký, đăng nhập, kiểm tra session, đăng xuất.

US01 - Task 9-10: Register.
US02 - Task 13: Login.
US02 - Task 14: require_user và logout.
"""

from collections.abc import Callable, Collection
from contextlib import suppress
from dataclasses import dataclass
from typing import NoReturn

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.user_repository import UserRepository
from services.auth_session import (
    AUTH_SESSION_USER_ID_KEY,
    SESSION_KEYS_TO_CLEAR,
    AuthSessionStore,
)
from services.base_service import BaseService
from utils.time_utils import Clock
from utils.validators import (
    validate_confirm_password,
    validate_email,
    validate_full_name,
    validate_password,
    validate_phone,
)


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Kết quả an toàn sau đăng ký."""

    user_id: int
    email: str
    full_name: str
    phone: str
    role: str
    status: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Thông tin trả về sau đăng nhập thành công."""

    user_id: int
    email: str
    full_name: str
    role: str


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Tài khoản đã được xác thực lại từ database."""

    user_id: int
    email: str
    full_name: str
    role: str
    status: str


def _invalid_credentials() -> NoReturn:
    """Không tiết lộ email hay mật khẩu nào bị sai."""

    raise AppError(
        "INVALID_CREDENTIALS",
        "Email hoặc mật khẩu không đúng.",
    )


def _unauthorized() -> NoReturn:
    """Người dùng chưa có phiên đăng nhập hợp lệ."""

    raise AppError(
        "UNAUTHORIZED",
        "Vui lòng đăng nhập để tiếp tục.",
    )


class AuthService(BaseService):
    """Nghiệp vụ xác thực tài khoản."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(clock=clock)
        self.session_factory = session_factory

    def register(
        self,
        *,
        email: str,
        password: str,
        confirm_password: str,
        full_name: str,
        phone: str,
    ) -> RegistrationResult:
        """Đăng ký tài khoản CUSTOMER/ACTIVE."""

        normalized_email = validate_email(email)
        normalized_name = validate_full_name(full_name)
        normalized_phone = validate_phone(phone)

        validated_password = validate_password(password)

        validate_confirm_password(
            validated_password,
            confirm_password,
        )

        password_hash = bcrypt.hashpw(
            validated_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("ascii")

        now_utc = self.current_time()

        try:
            with (
                self.session_factory() as session,
                session.begin(),
            ):
                repository = UserRepository(session)

                existing = repository.get_by_email(
                    normalized_email
                )

                if existing is not None:
                    raise AppError(
                        "EMAIL_EXISTS",
                        "Email đã được sử dụng.",
                        {"email": "Email đã tồn tại."},
                    )

                user_id = repository.create_customer(
                    email=normalized_email,
                    password_hash=password_hash,
                    full_name=normalized_name,
                    phone=normalized_phone,
                    now_utc=now_utc,
                )

        except IntegrityError as exc:
            error_code = (
                exc.orig.args[0]
                if exc.orig.args
                else None
            )

            if error_code == 1062:
                raise AppError(
                    "EMAIL_EXISTS",
                    "Email đã được sử dụng.",
                    {"email": "Email đã tồn tại."},
                ) from exc

            raise

        return RegistrationResult(
            user_id=user_id,
            email=normalized_email,
            full_name=normalized_name,
            phone=normalized_phone,
            role="CUSTOMER",
            status="ACTIVE",
        )

    def login(
        self,
        *,
        email: str,
        password: str,
        session_store: AuthSessionStore,
    ) -> LoginResult:
        """Đăng nhập và lưu user_id vào server-side session."""

        if not isinstance(email, str):
            _invalid_credentials()

        if not isinstance(password, str):
            _invalid_credentials()

        try:
            normalized_email = validate_email(email)
        except AppError:
            _invalid_credentials()

        try:
            password_bytes = password.encode("utf-8")
        except UnicodeEncodeError:
            _invalid_credentials()

        if not password_bytes or len(password_bytes) > 72:
            _invalid_credentials()

        with self.session_factory() as session:
            repository = UserRepository(session)
            user = repository.get_by_email(normalized_email)

        if user is None:
            _invalid_credentials()

        stored_hash = user["password_hash"].encode("ascii")

        if not bcrypt.checkpw(
            password_bytes,
            stored_hash,
        ):
            _invalid_credentials()

        if user["status"] != "ACTIVE":
            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa hoặc không còn hoạt động.",
            )

        user_id = int(user["id"])

        session_store.set(
            AUTH_SESSION_USER_ID_KEY,
            user_id,
        )

        return LoginResult(
            user_id=user_id,
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
        )

    def require_user(
        self,
        *,
        session_store: AuthSessionStore,
        allowed_roles: Collection[str] | None = None,
    ) -> AuthenticatedUser:
        """Kiểm tra phiên đăng nhập và trạng thái ACTIVE mới nhất.

        Chỉ tin user_id từ session phía server.
        Luôn tải lại status và role từ MariaDB.

        allowed_roles phải do code Service phía server quy định,
        không lấy trực tiếp từ lựa chọn của người dùng.
        """

        # 1. Lấy user_id đã xác thực trong server session.
        raw_user_id = session_store.get(
            AUTH_SESSION_USER_ID_KEY
        )

        # Chưa đăng nhập: từ chối, không xóa giỏ của khách.
        if raw_user_id is None:
            _unauthorized()

        # 2. Kiểm tra ID, từ chối cả bool, float và string.
        if (
            type(raw_user_id) is not int
            or raw_user_id <= 0
        ):
            self.logout(session_store=session_store)
            _unauthorized()

        # 3. Truy vấn lại tài khoản từ MariaDB.
        with self.session_factory() as session:
            repository = UserRepository(session)
            user = repository.get_by_id(raw_user_id)

        # 4. User đã bị xóa hoặc không tồn tại.
        if user is None:
            self.logout(session_store=session_store)
            _unauthorized()

        # 5. Tài khoản không còn ACTIVE.
        if user["status"] != "ACTIVE":
            self.logout(session_store=session_store)

            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa hoặc không còn hoạt động.",
            )

        # 6. Kiểm tra vai trò từ database, không từ UI.
        if (
            allowed_roles is not None
            and user["role"] not in allowed_roles
        ):
            raise AppError(
                "FORBIDDEN",
                "Bạn không có quyền thực hiện thao tác này.",
            )

        # 7. Trả về danh tính và role được xác thực lại.
        return AuthenticatedUser(
            user_id=int(user["id"]),
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
            status=user["status"],
        )


    @staticmethod
    def logout(
        *,
        session_store: AuthSessionStore,
    ) -> None:
        """Đăng xuất và xóa trạng thái người dùng trong session.

        Khóa chưa tồn tại được bỏ qua để logout luôn an toàn.
        Không xóa các tùy chọn giao diện không liên quan.
        """

        for key in SESSION_KEYS_TO_CLEAR:
            with suppress(KeyError):
                session_store.remove(key)