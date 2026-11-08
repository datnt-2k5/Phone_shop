
"""Các khóa dữ liệu và giao diện Flet Session Store.

US02 - Task 13: Lưu user_id sau đăng nhập.
US02 - Task 14: Đọc session và xóa trạng thái khi đăng xuất.
"""

from typing import Protocol

# Danh tính đã xác thực - tạo ở Task 13.
AUTH_SESSION_USER_ID_KEY = "phone_shop.auth.user_id"

# Giỏ hàng tạm trong phiên hiện tại.
CART_SESSION_KEY = "phone_shop.cart.items"

# Idempotency key cho thao tác checkout.
CHECKOUT_SESSION_KEY = "phone_shop.checkout.key"

# Cache thông tin người dùng theo phiên.
USER_CACHE_SESSION_KEY = "phone_shop.auth.user_cache"


# Chỉ xóa những khóa thuộc trạng thái người dùng.
SESSION_KEYS_TO_CLEAR = (
    AUTH_SESSION_USER_ID_KEY,
    CART_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    USER_CACHE_SESSION_KEY,
)


class AuthSessionStore(Protocol):
    """Giao diện cần thiết của Flet server-side Session Store."""

    def set(self, key: str, value: object) -> None:
        """Ghi dữ liệu vào session."""
        ...

    def get(self, key: str) -> object | None:
        """Đọc dữ liệu từ session."""
        ...

    def remove(self, key: str) -> None:
        """Xóa một khóa khỏi session."""
        ...
