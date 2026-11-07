"""Cấu hình menu dùng cho UI demo Task 6, KHÔNG phải kiểm tra bảo mật."""

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
CUSTOMER = PUBLIC + ("/profile", "/cart", "/my-orders", "/my-invoices")
ADMIN = PUBLIC + ("/profile",) + tuple(
    item.route for item in MENU if item.route.startswith("/admin/")
)
SUPER_ADMIN = ADMIN + ("/super/accounts", "/super/settings")

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


def menu_for_role(role: str) -> tuple[MenuItem, ...]:
    """Trả menu để hiển thị. Tuyệt đối không dùng làm xác thực/ủy quyền."""
    if role not in ROLE_ROUTES:
        raise ValueError(f"Vai trò không hợp lệ: {role}")
    routes = ROLE_ROUTES[role]
    return tuple(item for item in MENU if item.route in routes)


def demo_route_visible(role: str, route: str) -> bool:
    """Chỉ dùng để hiển thị trang mẫu; bảo mật thật sẽ nằm ở Service Layer."""
    return route in ROLE_ROUTES.get(role, ())
