
"""Quy ước lưu danh tính xác thực trong Flet Session.

US02 - Task 13.

Chỉ lưu user_id sau khi AuthService xác minh thành công.
Không lưu password, password_hash hay role do client cung cấp.
"""

from typing import Protocol

AUTH_SESSION_USER_ID_KEY = "phone_shop.auth.user_id"


class AuthSessionStore(Protocol):
    """Giao diện tối thiểu của Flet server-side Session Store."""

    def set(self, key: str, value: int) -> None:
        """Lưu ID người dùng vào session phía server."""
        ...
