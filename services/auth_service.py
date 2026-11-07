
"""Auth Service - nghiệp vụ đăng ký tài khoản.

US01 - Task 9.
Validation sẽ được tách thành module riêng ở Task 10.
"""

import re
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

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9-]+"
    r"(?:\.[A-Za-z0-9-]+)+"
)

PHONE_PATTERN = re.compile(r"0[0-9]{9}")


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Kết quả trả về sau đăng ký thành công."""

    user_id: int
    email: str
    full_name: str
    phone: str
    role: str
    status: str


class AuthService(BaseService):
    """Service xử lý đăng ký Customer."""

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
        full_name: str,
        phone: str,
    ) -> RegistrationResult:
        """Tạo tài khoản Customer trong một transaction."""

        # 1. Kiểm tra kiểu dữ liệu
        fields = {
            "email": email,
            "password": password,
            "full_name": full_name,
            "phone": phone,
        }

        for field_name, value in fields.items():
            if not isinstance(value, str):
                raise AppError(
                    "VALIDATION_ERROR",
                    "Thông tin đăng ký không hợp lệ.",
                    {field_name: "Phải là chuỗi ký tự."},
                )

        # 2. Chuẩn hóa dữ liệu
        normalized_email = email.strip().lower()
        normalized_name = full_name.strip()
        normalized_phone = phone.strip()

        # 3. Kiểm tra email
        if (
            not normalized_email
            or len(normalized_email) > 100
            or EMAIL_PATTERN.fullmatch(normalized_email) is None
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Email không hợp lệ.",
                {"email": "Email không đúng định dạng."},
            )

        # 4. Kiểm tra họ tên
        if (
            not normalized_name
            or len(normalized_name) > 100
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Họ tên không hợp lệ.",
                {"full_name": "Họ tên phải từ 1 đến 100 ký tự."},
            )

        # 5. Kiểm tra số điện thoại
        if PHONE_PATTERN.fullmatch(normalized_phone) is None:
            raise AppError(
                "VALIDATION_ERROR",
                "Số điện thoại không hợp lệ.",
                {"phone": "Phải gồm 10 chữ số, bắt đầu bằng 0."},
            )

        # 6. Kiểm tra mật khẩu
        password_bytes = password.encode("utf-8")

        if (
            len(password) < 8
            or len(password_bytes) > 72
            or not any(ch.isalpha() for ch in password)
            or not any(ch.isdigit() for ch in password)
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Mật khẩu không hợp lệ.",
                {
                    "password": (
                        "Tối thiểu 8 ký tự, có chữ và số, "
                        "tối đa 72 byte UTF-8."
                    )
                },
            )

        # 7. Băm mật khẩu, không lưu mật khẩu gốc
        password_hash = bcrypt.hashpw(
            password_bytes,
            bcrypt.gensalt(),
        ).decode("ascii")

        # 8. Thời gian từ Clock
        now_utc = self.current_time()

        # 9. Thực hiện nghiệp vụ trong transaction
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
            # Ngăn email trùng khi hai yêu cầu đến đồng thời
            code = (
                exc.orig.args[0]
                if exc.orig.args
                else None
            )

            if code == 1062:
                raise AppError(
                    "EMAIL_EXISTS",
                    "Email đã được sử dụng.",
                    {"email": "Email đã tồn tại."},
                ) from exc

            raise

        # 10. Không trả password_hash ra giao diện
        return RegistrationResult(
            user_id=user_id,
            email=normalized_email,
            full_name=normalized_name,
            phone=normalized_phone,
            role="CUSTOMER",
            status="ACTIVE",
        )
