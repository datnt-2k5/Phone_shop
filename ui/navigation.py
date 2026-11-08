
"""Menu và quy tắc điều hướng của Phone Shop.

Task 6: Cấu hình menu mẫu.
Task 15: Điều hướng theo role đã xác thực.
Bảo vệ nghiệp vụ thật luôn nằm tại Service Layer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MenuItem:
    label: str
    route: str


MENU: tuple[MenuItem, ...] = (
    MenuItem("Trang chủ", "/"),
    MenuItem("Sản phẩm", "/products"),
    MenuItem("Đăng nhập", "/login"),
    MenuItem("Đăng ký", "/register"),
    MenuItem("Hồ sơ", "/profile"),
    MenuItem("Giỏ hàng", "/cart"),
    MenuItem("Đơn của tôi", "/my-orders"),
    MenuItem("Hóa đơn của tôi", "/my-invoices"),
    MenuItem("Dashboard", "/admin/dashboard"),
    MenuItem("Quản lý sản phẩm", "/admin/products"),
    MenuItem("Hãng và nhà cung cấp", "/admin/catalog"),
    MenuItem("Nhập kho", "/admin/imports"),
    MenuItem("Tồn kho", "/admin/inventory"),
    MenuItem("Quản lý đơn hàng", "/admin/orders"),
    MenuItem("Khách hàng", "/admin/customers"),
    MenuItem("Quản lý hóa đơn", "/admin/invoices"),
    MenuItem("Báo cáo", "/admin/reports"),
    MenuItem("Tài khoản", "/super/accounts"),
    MenuItem("Cấu hình hệ thống", "/super/settings"),
)

PUBLIC = ("/", "/products")
GUEST = PUBLIC + ("/login", "/register")

CUSTOMER = PUBLIC + (
    "/profile",
    "/cart",
    "/my-orders",
    "/my-invoices",
)

ADMIN = PUBLIC + ("/profile",) + tuple(
    item.route
    for item in MENU
    if item.route.startswith("/admin/")
)

SUPER_ADMIN = ADMIN + (
    "/super/accounts",
    "/super/settings",
)


ROLE_ROUTES = {
    "GUEST": GUEST,
    "CUSTOMER": CUSTOMER,
    "ADMIN": ADMIN,
    "SUPER_ADMIN": SUPER_ADMIN,
}

ROLE_LABELS = {
    "GUEST": "Khách vãng lai",
    "CUSTOMER": "Khách hàng",
    "ADMIN": "Quản trị viên",
    "SUPER_ADMIN": "Quản trị cấp cao",
}


# Nơi điều hướng ngay sau khi đăng nhập thành công.
LOGIN_DESTINATIONS = {
    "CUSTOMER": "/profile",
    "ADMIN": "/admin/dashboard",
    "SUPER_ADMIN": "/super/accounts",
}


def menu_for_role(role: str) -> tuple[MenuItem, ...]:
    """Menu hiển thị theo role; không thay Service Guard."""

    if role not in ROLE_ROUTES:
        raise ValueError(f"Vai trò không hợp lệ: {role}")

    routes = ROLE_ROUTES[role]
    return tuple(
        item
        for item in MENU
        if item.route in routes
    )


def demo_route_visible(role: str, route: str) -> bool:
    """Giữ tương thích với kiểm thử Task 6."""

    return route in ROLE_ROUTES.get(role, ())


def home_route_for_role(role: str) -> str:
    """Trả trang đích cho role sau đăng nhập."""

    if role not in LOGIN_DESTINATIONS:
        raise ValueError(
            f"Không có trang đích cho role: {role}"
        )

    return LOGIN_DESTINATIONS[role]


def route_available(role: str, route: str) -> bool:
    """Kiểm tra quyền hiển thị route ở tầng giao diện.

    Role phải được lấy từ require_user(), không lấy từ
    nút chọn vai trò hay dữ liệu client tự khai báo.
    """

    return route in ROLE_ROUTES.get(role, ())
