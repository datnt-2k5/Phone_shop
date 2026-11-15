
"""Task 52: checkout and Customer order-detail route tests."""

import pytest

from ui.navigation import route_available
from ui.route_guard import (
    RouteStatus,
    check_route_access,
    customer_order_id,
)


def test_customer_can_access_checkout():
    result = check_route_access(
        route="/checkout",
        role="CUSTOMER",
    )

    assert result.status == RouteStatus.ALLOW
    assert route_available("CUSTOMER", "/checkout")


def test_guest_is_redirected_to_login_for_checkout():
    result = check_route_access(
        route="/checkout",
        role="GUEST",
    )

    assert result.status == RouteStatus.LOGIN_REQUIRED
    assert result.redirect_to == "/login"


@pytest.mark.parametrize(
    "role",
    ["ADMIN", "SUPER_ADMIN"],
)
def test_admin_roles_cannot_use_customer_checkout(role):
    result = check_route_access(
        route="/checkout",
        role=role,
    )

    assert result.status == RouteStatus.FORBIDDEN
    assert not route_available(role, "/checkout")


def test_customer_order_detail_id_is_parsed():
    assert customer_order_id("/my-orders/42") == 42
    assert customer_order_id("/my-orders/1") == 1


@pytest.mark.parametrize(
    "route",
    [
        "/my-orders/",
        "/my-orders/0",
        "/my-orders/01",
        "/my-orders/-1",
        "/my-orders/abc",
        "/my-orders/1/extra",
        "/my-orders/9223372036854775808",
        "/my-orders/12345678901234567890",
        "/my-orders",
        "/products/42",
    ],
)
def test_invalid_customer_order_detail_paths(route):
    assert customer_order_id(route) is None


def test_customer_can_access_order_detail_route():
    result = check_route_access(
        route="/my-orders/42",
        role="CUSTOMER",
    )

    assert result.status == RouteStatus.ALLOW


def test_guest_order_detail_requires_login():
    result = check_route_access(
        route="/my-orders/42",
        role="GUEST",
    )

    assert result.status == RouteStatus.LOGIN_REQUIRED
    assert result.redirect_to == "/login"


@pytest.mark.parametrize(
    "role",
    ["ADMIN", "SUPER_ADMIN"],
)
def test_admin_cannot_access_customer_order_detail(role):
    result = check_route_access(
        route="/my-orders/42",
        role=role,
    )

    assert result.status == RouteStatus.FORBIDDEN


def test_invalid_order_detail_route_returns_not_found():
    result = check_route_access(
        route="/my-orders/not-an-id",
        role="CUSTOMER",
    )

    assert result.status == RouteStatus.NOT_FOUND


def test_customer_order_detail_has_no_leading_zero():
    assert customer_order_id("/my-orders/00042") is None


def test_max_bigint_order_id_is_accepted():
    assert customer_order_id(
        "/my-orders/9223372036854775807"
    ) == 9_223_372_036_854_775_807


def test_non_string_order_route_is_rejected():
    assert customer_order_id(None) is None
