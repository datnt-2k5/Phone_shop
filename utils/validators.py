
"""Các hàm validation dùng chung của Phone Shop.

Task 10: Đăng ký tài khoản.
Task 17: Địa chỉ hồ sơ cá nhân.
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
    """Chuẩn hóa họ tên và kiểm tra độ dài."""

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
    """Số điện thoại gồm 10 chữ số ASCII, bắt đầu bằng 0."""

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
    """Mật khẩu từ 8 ký tự, tối đa 72 byte UTF-8."""

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
    """Xác nhận mật khẩu phải trùng chính xác."""

    if (
        not isinstance(confirmation, str)
        or confirmation != password
    ):
        _invalid(
            "confirm_password",
            "Xác nhận mật khẩu không khớp.",
        )


def validate_address(value: str | None) -> str | None:
    """Địa chỉ cho phép NULL, tối đa 255 ký tự."""

    if value is None:
        return None

    if not isinstance(value, str):
        _invalid(
            "address",
            "Địa chỉ phải là chuỗi ký tự.",
        )

    address = value.strip()

    if len(address) > 255:
        _invalid(
            "address",
            "Địa chỉ không được vượt quá 255 ký tự.",
        )

    return address or None
