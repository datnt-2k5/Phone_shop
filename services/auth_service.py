
"""Auth Service - đăng ký và đăng nhập tài khoản.

US01 - Task 9, 10: Register.
US02 - Task 13: Login với bcrypt và server-side session.
"""

from collections.abc import Callable
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
    """Kết quả an toàn sau khi đăng ký."""

    user_id: int
    email: str
    full_name: str
    phone: str
    role: str
    status: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Thông tin tài khoản sau khi xác thực thành công."""

    user_id: int
    email: str
    full_name: str
    role: str


def _invalid_credentials() -> NoReturn:
    """Dùng cùng một lỗi cho email không tồn tại hoặc mật khẩu sai."""

    raise AppError(
        "INVALID_CREDENTIALS",
        "Email hoặc mật khẩu không đúng.",
    )


class AuthService(BaseService):
    """Service xử lý đăng ký và đăng nhập."""

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

        # Task 9-10: Validate dữ liệu đăng ký
        normalized_email = validate_email(email)
        normalized_name = validate_full_name(full_name)
        normalized_phone = validate_phone(phone)

        validated_password = validate_password(password)

        validate_confirm_password(
            validated_password,
            confirm_password,
        )

        # Hash password bằng bcrypt
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
            # MariaDB UNIQUE(email): mã 1062 = trùng dữ liệu
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
        """Đăng nhập và lưu user_id vào session phía server.

        Trình tự:
        1. Chuẩn hóa email.
        2. Truy vấn tài khoản theo email.
        3. Kiểm tra mật khẩu bằng bcrypt.
        4. Kiểm tra trạng thái ACTIVE.
        5. Lưu user_id vào server-side session.
        """

        # 1. Dữ liệu đầu vào phải là chuỗi
        if not isinstance(email, str):
            _invalid_credentials()

        if not isinstance(password, str):
            _invalid_credentials()

        # 2. Email chuẩn hóa theo cùng quy tắc đăng ký
        try:
            normalized_email = validate_email(email)
        except AppError:
            # Không phân biệt email sai định dạng với
            # email chưa tồn tại khi trả lỗi đăng nhập.
            _invalid_credentials()

        # 3. Giữ nguyên password; không strip, không lower.
        try:
            password_bytes = password.encode("utf-8")
        except UnicodeEncodeError:
            _invalid_credentials()

        if not password_bytes or len(password_bytes) > 72:
            _invalid_credentials()

        # 4. Đọc thông tin tài khoản từ MariaDB
        with self.session_factory() as session:
            repository = UserRepository(session)
            user = repository.get_by_email(normalized_email)

        # 5. Email không tồn tại
        if user is None:
            _invalid_credentials()

        # 6. So khớp mật khẩu với password_hash của DB
        stored_hash = user["password_hash"].encode("ascii")

        if not bcrypt.checkpw(
            password_bytes,
            stored_hash,
        ):
            _invalid_credentials()

        # 7. Chỉ tài khoản ACTIVE mới được đăng nhập
        if user["status"] != "ACTIVE":
            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa hoặc không còn hoạt động.",
            )

        # 8. Chỉ lấy user_id đã xác thực từ database
        user_id = int(user["id"])

        # Chỉ lưu danh tính sau khi mọi kiểm tra đều đạt.
        # Không lưu password, hash, email hoặc role ở đây.
        session_store.set(
            AUTH_SESSION_USER_ID_KEY,
            user_id,
        )

        # 9. Trả thông tin cần cho bước giao diện sau này
        return LoginResult(
            user_id=user_id,
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
        )
