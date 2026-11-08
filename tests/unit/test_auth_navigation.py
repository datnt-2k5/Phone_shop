
"""Kiểm thử điều hướng theo role - US02 Task 15."""

import pytest

from ui.navigation import (
    home_route_for_role,
    menu_for_role,
    route_available,
)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("CUSTOMER", "/profile"),
        ("ADMIN", "/admin/dashboard"),
        ("SUPER_ADMIN", "/super/accounts"),
    ],
)
def test_login_destination_by_role(
    role: str,
    expected: str,
) -> None:
    """Đăng nhập xong phải đến đúng trang theo role."""

    assert home_route_for_role(role) == expected


@pytest.mark.parametrize(
    ("role", "route", "allowed"),
    [
        ("GUEST", "/", True),
        ("GUEST", "/products", True),
        ("GUEST", "/login", True),
        ("GUEST", "/admin/dashboard", False),
        ("CUSTOMER", "/profile", True),
        ("CUSTOMER", "/admin/dashboard", False),
        ("CUSTOMER", "/register", False),
        ("ADMIN", "/admin/dashboard", True),
        ("ADMIN", "/super/accounts", False),
        ("SUPER_ADMIN", "/super/accounts", True),
        ("SUPER_ADMIN", "/admin/dashboard", True),
    ],
)
def test_route_access_by_role(
    role: str,
    route: str,
    allowed: bool,
) -> None:
    """Không hiển thị route ngoài phạm vi role."""

    assert route_available(role, route) is allowed


def test_unknown_role_has_no_login_destination() -> None:
    """Role không hợp lệ không được cấp trang quản trị."""

    with pytest.raises(ValueError):
        home_route_for_role("FAKE_ADMIN")


def test_authenticated_menu_hides_login_and_register() -> None:
    """Menu đã đăng nhập không còn mục Login/Register."""

    for role in (
        "CUSTOMER",
        "ADMIN",
        "SUPER_ADMIN",
    ):
        routes = {
            item.route
            for item in menu_for_role(role)
        }

        assert "/login" not in routes
        assert "/register" not in routes
