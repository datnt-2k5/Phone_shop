
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



def public_product_id(route: str) -> int | None:
    """Parse /products/{positive BIGINT}, rejecting malformed paths."""
    prefix = "/products/"

    if not isinstance(route, str) or not route.startswith(prefix):
        return None

    raw_id = route[len(prefix):]

    if (
        not raw_id
        or len(raw_id) > 19
        or not raw_id.isascii()
        or not raw_id.isdecimal()
        or raw_id.startswith("0")
    ):
        return None

    product_id = int(raw_id)

    if product_id > 9_223_372_036_854_775_807:
        return None

    return product_id


def check_route_access(
    *,
    route: str,
    role: str,
) -> RouteDecision:
    """Kiểm tra route với role được xác thực từ database.

    Hàm này không tự đọc dữ liệu client hay Session.
    main.py phải lấy role qua AuthService.require_user().
    """


    # Task 46: map valid product-detail routes to public
    # product permission without adding dynamic IDs to MENU.
    detail_id = public_product_id(route)

    permission_route = (
        "/products"
        if detail_id is not None
        else route
    )

    if permission_route not in KNOWN_ROUTES:
        return RouteDecision(RouteStatus.NOT_FOUND)

    # Vai trò lạ phải bị từ chối.
    if role not in ROLE_ROUTES:
        return RouteDecision(RouteStatus.FORBIDDEN)

    # Guest cố mở trang cần đăng nhập.
    if role == "GUEST" and permission_route not in GUEST:
        return RouteDecision(
            RouteStatus.LOGIN_REQUIRED,
            "/login",
        )

    # Đã đăng nhập thì không mở lại trang login/register.
    if role != "GUEST" and permission_route in AUTH_PAGES:
        return RouteDecision(
            RouteStatus.REDIRECT,
            home_route_for_role(role),
        )

    # Đã đăng nhập nhưng không có quyền với route.
    if not route_available(role, permission_route):
        return RouteDecision(RouteStatus.FORBIDDEN)

    return RouteDecision(RouteStatus.ALLOW)
