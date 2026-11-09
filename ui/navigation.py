
"""Menu và Route theo vai trò, đồng bộ ma trận US04."""

from dataclasses import dataclass
from types import MappingProxyType

from services.permissions import PERMISSION_MATRIX, Access, Permission, Role


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

# Giữ các hằng số cũ để không phá vỡ Task 1–22.
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

LOGIN_DESTINATIONS = {
    "CUSTOMER": "/profile",
    "ADMIN": "/admin/dashboard",
    "SUPER_ADMIN": "/super/accounts",
}

# Map mỗi route tới quyền nghiệp vụ đã khai báo ở Task 22.
# ROLE_ROUTES vẫn xác định loại giao diện được phép truy cập.
ROUTE_PERMISSIONS = MappingProxyType({
    "/": Permission.VIEW_PRODUCTS,
    "/products": Permission.VIEW_PRODUCTS,
    "/login": Permission.LOGIN,
    "/register": Permission.REGISTER,
    "/profile": Permission.VIEW_PROFILE,
    "/cart": Permission.PLACE_ORDER,
    "/my-orders": Permission.VIEW_ORDERS,
    "/my-invoices": Permission.VIEW_INVOICES,
    "/admin/dashboard": Permission.VIEW_STATISTICS,
    "/admin/products": Permission.MANAGE_PRODUCTS,
    "/admin/catalog": Permission.MANAGE_BRANDS,
    "/admin/imports": Permission.IMPORT_STOCK,
    "/admin/inventory": Permission.VIEW_INVENTORY,
    "/admin/orders": Permission.VIEW_ORDERS,
    "/admin/customers": Permission.VIEW_CUSTOMERS,
    "/admin/invoices": Permission.VIEW_INVOICES,
    "/admin/reports": Permission.VIEW_STATISTICS,
    "/super/accounts": Permission.MANAGE_ACCOUNTS,
    "/super/settings": Permission.MANAGE_SETTINGS,
})


def route_available(role: str, route: str) -> bool:
    """Kiểm tra đồng thời giới hạn route và ma trận quyền."""
    if role not in ROLE_ROUTES or route not in ROLE_ROUTES[role]:
        return False

    permission = ROUTE_PERMISSIONS.get(route)

    return (
        permission is not None
        and PERMISSION_MATRIX[permission][Role(role)] != Access.DENY
    )


def menu_for_role(role: str) -> tuple[MenuItem, ...]:
    """Chỉ trả về menu được phép theo role."""
    if role not in ROLE_ROUTES:
        raise ValueError(f"Vai trò không hợp lệ: {role}")

    return tuple(
        item
        for item in MENU
        if route_available(role, item.route)
    )


def demo_route_visible(role: str, route: str) -> bool:
    """Giữ tương thích các bài test của Task 6."""
    return route_available(role, route)


def home_route_for_role(role: str) -> str:
    """Trang đích sau khi đăng nhập thành công."""
    if role not in LOGIN_DESTINATIONS:
        raise ValueError(
            f"Không có trang đích cho role: {role}"
        )

    return LOGIN_DESTINATIONS[role]
