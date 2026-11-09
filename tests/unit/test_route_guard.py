
"""US04 Task 23: kiểm thử menu và Route Guard."""

import pytest

from services.permissions import PERMISSION_MATRIX, Access, Role
from ui.navigation import (
    LOGIN_DESTINATIONS,
    MENU,
    ROLE_ROUTES,
    ROUTE_PERMISSIONS,
    demo_route_visible,
    home_route_for_role,
    menu_for_role,
    route_available,
)
from ui.route_guard import RouteStatus, check_route_access

EXPECTED = {
    "GUEST": {
        "/", "/products", "/login", "/register",
    },
    "CUSTOMER": {
        "/", "/products", "/profile", "/cart",
        "/my-orders", "/my-invoices",
    },
    "ADMIN": {
        "/", "/products", "/profile", "/admin/dashboard",
        "/admin/products", "/admin/catalog", "/admin/imports",
        "/admin/inventory", "/admin/orders", "/admin/customers",
        "/admin/invoices", "/admin/reports",
    },
    "SUPER_ADMIN": {
        "/", "/products", "/profile", "/admin/dashboard",
        "/admin/products", "/admin/catalog", "/admin/imports",
        "/admin/inventory", "/admin/orders", "/admin/customers",
        "/admin/invoices", "/admin/reports",
        "/super/accounts", "/super/settings",
    },
}


@pytest.mark.parametrize("role", list(EXPECTED))
@pytest.mark.parametrize(
    "route",
    [item.route for item in MENU],
)
def test_route_available_matches_role_plan(role, route):
    """Kiểm tra 19 URL x 4 vai trò."""

    assert route_available(role, route) == (
        route in EXPECTED[role]
    )


@pytest.mark.parametrize("role", list(EXPECTED))
def test_menu_contains_only_allowed_routes(role):
    """Menu không được hiển thị link vượt quyền."""

    routes = {
        item.route
        for item in menu_for_role(role)
    }

    assert routes == EXPECTED[role]
    assert all(
        route_available(role, route)
        for route in routes
    )


def test_every_menu_item_has_a_permission():
    """Mỗi route phải được ánh xạ vào ma trận Task 22."""

    assert {
        item.route
        for item in MENU
    } == set(ROUTE_PERMISSIONS)

    assert len({
        item.route
        for item in MENU
    }) == len(MENU)

    for role in Role:
        for route in ROLE_ROUTES[role.value]:
            permission = ROUTE_PERMISSIONS[route]

            assert (
                PERMISSION_MATRIX[permission][role]
                != Access.DENY
            )


@pytest.mark.parametrize(
    "route",
    [
        "/profile",
        "/cart",
        "/admin/dashboard",
        "/super/accounts",
    ],
)
def test_guest_protected_route_redirects_login(route):
    result = check_route_access(
        route=route,
        role="GUEST",
    )

    assert result.status == RouteStatus.LOGIN_REQUIRED
    assert result.redirect_to == "/login"


@pytest.mark.parametrize(
    "route",
    [
        "/admin/dashboard",
        "/admin/products",
        "/super/accounts",
    ],
)
def test_customer_cannot_open_admin_or_super_url(route):
    result = check_route_access(
        route=route,
        role="CUSTOMER",
    )

    assert result.status == RouteStatus.FORBIDDEN
    assert result.redirect_to is None


@pytest.mark.parametrize(
    "route",
    [
        "/super/accounts",
        "/super/settings",
    ],
)
def test_admin_cannot_open_super_admin_url(route):
    result = check_route_access(
        route=route,
        role="ADMIN",
    )

    assert result.status == RouteStatus.FORBIDDEN


@pytest.mark.parametrize(
    "route",
    [
        "/super/accounts",
        "/super/settings",
    ],
)
def test_super_admin_can_open_super_routes(route):
    result = check_route_access(
        route=route,
        role="SUPER_ADMIN",
    )

    assert result.status == RouteStatus.ALLOW


@pytest.mark.parametrize(
    "role",
    ["CUSTOMER", "ADMIN", "SUPER_ADMIN"],
)
@pytest.mark.parametrize(
    "route",
    ["/login", "/register"],
)
def test_signed_in_user_redirected_from_auth_pages(
    role,
    route,
):
    result = check_route_access(
        route=route,
        role=role,
    )

    assert result.status == RouteStatus.REDIRECT
    assert result.redirect_to == LOGIN_DESTINATIONS[role]


@pytest.mark.parametrize("role", list(EXPECTED))
def test_unknown_url_returns_404(role):
    result = check_route_access(
        route="/not-a-route",
        role=role,
    )

    assert result.status == RouteStatus.NOT_FOUND
    assert result.redirect_to is None


@pytest.mark.parametrize(
    "role",
    ["", "OWNER", "FAKE_ADMIN"],
)
def test_unknown_role_is_denied(role):
    result = check_route_access(
        route="/products",
        role=role,
    )

    assert result.status == RouteStatus.FORBIDDEN


def test_public_route_visible_to_every_role():
    for role in EXPECTED:
        result = check_route_access(
            route="/products",
            role=role,
        )

        assert result.status == RouteStatus.ALLOW


def test_menu_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        menu_for_role("FAKE_ADMIN")


def test_legacy_route_helper_unchanged():
    """Giữ tương thích với test của Task 6."""

    for role in EXPECTED:
        assert demo_route_visible(
            role,
            "/profile",
        ) == route_available(role, "/profile")


def test_home_destinations_are_accessible():
    for role, target in LOGIN_DESTINATIONS.items():
        assert home_route_for_role(role) == target

        result = check_route_access(
            route=target,
            role=role,
        )

        assert result.status == RouteStatus.ALLOW
