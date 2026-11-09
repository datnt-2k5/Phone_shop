
"""US04 Task 23: quyết định truy cập trước khi dựng màn hình."""

from dataclasses import dataclass
from enum import StrEnum

from ui.navigation import (
    GUEST,
    MENU,
    ROLE_ROUTES,
    home_route_for_role,
    route_available,
)


class RouteStatus(StrEnum):
    ALLOW = "ALLOW"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    REDIRECT = "REDIRECT"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    status: RouteStatus
    redirect_to: str | None = None


KNOWN_ROUTES = frozenset(item.route for item in MENU)
AUTH_PAGES = frozenset(("/login", "/register"))


def check_route_access(
    *,
    route: str,
    role: str,
) -> RouteDecision:
    """Kiểm tra route với role được xác thực từ database.

    Hàm này không tự đọc dữ liệu client hay Session.
    main.py phải lấy role qua AuthService.require_user().
    """

    # URL chưa được khai báo.
    if route not in KNOWN_ROUTES:
        return RouteDecision(RouteStatus.NOT_FOUND)

    # Vai trò lạ phải bị từ chối.
    if role not in ROLE_ROUTES:
        return RouteDecision(RouteStatus.FORBIDDEN)

    # Guest cố mở trang cần đăng nhập.
    if role == "GUEST" and route not in GUEST:
        return RouteDecision(
            RouteStatus.LOGIN_REQUIRED,
            "/login",
        )

    # Đã đăng nhập thì không mở lại trang login/register.
    if role != "GUEST" and route in AUTH_PAGES:
        return RouteDecision(
            RouteStatus.REDIRECT,
            home_route_for_role(role),
        )

    # Đã đăng nhập nhưng không có quyền với route.
    if not route_available(role, route):
        return RouteDecision(RouteStatus.FORBIDDEN)

    return RouteDecision(RouteStatus.ALLOW)
