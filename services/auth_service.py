
"""Auth Service - nghiệp vụ đăng ký tài khoản.

US01 - Task 9 và Task 10.
Validation tập trung trong utils.validators.
"""

from collections.abc import Callable
from dataclasses import dataclass

import bcrypt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.user_repository import UserRepository
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
    """Thông tin an toàn trả về sau đăng ký."""

    user_id: int
    email: str
    full_name: str
    phone: str
    role: str
    status: str


class AuthService(BaseService):
    """Xử lý nghiệp vụ đăng ký Customer."""

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
        """Đăng ký Customer mới trong một transaction."""

        # 1. Validate và chuẩn hóa dữ liệu
        normalized_email = validate_email(email)
        normalized_name = validate_full_name(full_name)
        normalized_phone = validate_phone(phone)

        validated_password = validate_password(password)

        # 2. Xác nhận mật khẩu phải trùng khớp
        validate_confirm_password(
            validated_password,
            confirm_password,
        )

        # 3. Chỉ hash sau khi mật khẩu đã hợp lệ
        password_hash = bcrypt.hashpw(
            validated_password.encode("utf-8"),
            bcrypt.gensalt(),
        ).decode("ascii")

        # 4. Lấy thời gian UTC
        now_utc = self.current_time()

        # 5. Kiểm tra email và tạo tài khoản
        try:
            with self.session_factory() as session, session.begin():
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
            # Database UNIQUE(email) bảo vệ khi
            # hai yêu cầu đăng ký xảy ra đồng thời.
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

        # 6. Trả kết quả, không trả mật khẩu/hash
        return RegistrationResult(
            user_id=user_id,
            email=normalized_email,
            full_name=normalized_name,
            phone=normalized_phone,
            role="CUSTOMER",
            status="ACTIVE",
        )
