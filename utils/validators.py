
"""Validate dữ liệu đăng ký tài khoản (US01 - Task 10).

Không kết nối database, không hash và không đổi mật khẩu người dùng.
"""

import re

from models.app_error import AppError

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9_%+\-]+(?:\.[A-Za-z0-9_%+\-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
PHONE_PATTERN = re.compile(r"0[0-9]{9}")


def _invalid(field: str, detail: str) -> None:
    raise AppError(
        "VALIDATION_ERROR",
        "Thông tin đăng ký không hợp lệ.",
        {field: detail},
    )


def validate_email(value: str) -> str:
    """Chuẩn hóa email và kiểm tra định dạng/độ dài."""

    if not isinstance(value, str):
        _invalid("email", "Email phải là chuỗi ký tự.")

    email = value.strip().lower()

    if len(email) > 100 or EMAIL_PATTERN.fullmatch(email) is None:
        _invalid(
            "email",
            "Email không hợp lệ hoặc dài quá 100 ký tự.",
        )

    return email


def validate_full_name(value: str) -> str:
    """Loại khoảng trắng dư và kiểm tra họ tên."""

    if not isinstance(value, str):
        _invalid("full_name", "Họ tên phải là chuỗi ký tự.")

    full_name = " ".join(value.split())

    if not full_name or len(full_name) > 100:
        _invalid(
            "full_name",
            "Họ tên phải có từ 1 đến 100 ký tự.",
        )

    return full_name


def validate_phone(value: str) -> str:
    """Số điện thoại: 10 chữ số ASCII, bắt đầu bằng 0."""

    if not isinstance(value, str):
        _invalid(
            "phone",
            "Số điện thoại phải là chuỗi ký tự.",
        )

    phone = value.strip()

    if PHONE_PATTERN.fullmatch(phone) is None:
        _invalid(
            "phone",
            "Số điện thoại phải gồm 10 chữ số, bắt đầu bằng 0.",
        )

    return phone


def validate_password(value: str) -> str:
    """Kiểm tra mật khẩu không quá 72 byte UTF-8 cho bcrypt."""

    if not isinstance(value, str):
        _invalid(
            "password",
            "Mật khẩu phải là chuỗi ký tự.",
        )

    try:
        password_bytes = value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid(
            "password",
            "Mật khẩu không mã hóa được bằng UTF-8.",
        )

    if (
        len(value) < 8
        or len(password_bytes) > 72
        or not any(ch.isalpha() for ch in value)
        or not any(ch.isdigit() for ch in value)
    ):
        _invalid(
            "password",
            "Mật khẩu phải từ 8 ký tự, có chữ và số, "
            "tối đa 72 byte UTF-8.",
        )

    return value


def validate_confirm_password(
    password: str,
    confirmation: str,
) -> None:
    """Xác nhận phải trùng chính xác mật khẩu đã nhập."""

    if (
        not isinstance(confirmation, str)
        or confirmation != password
    ):
        _invalid(
            "confirm_password",
            "Xác nhận mật khẩu không khớp.",
        )
