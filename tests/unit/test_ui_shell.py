"""Kiểm thử menu và định dạng VND của Task 6, không cần server Flet/MariaDB."""

from decimal import Decimal

import pytest

from ui.components.money_format import format_vnd
from ui.navigation import ROLE_ROUTES, demo_route_visible, menu_for_role


@pytest.mark.parametrize(
    ("role", "route", "visible"),
    [
        ("GUEST", "/products", True),
        ("GUEST", "/login", True),
        ("GUEST", "/admin/dashboard", False),
        ("CUSTOMER", "/cart", True),
        ("CUSTOMER", "/admin/orders", False),
        ("ADMIN", "/admin/orders", True),
        ("ADMIN", "/super/settings", False),
        ("SUPER_ADMIN", "/super/settings", True),
    ],
)
def test_demo_menu(role, route, visible):
    assert demo_route_visible(role, route) is visible
    assert (route in [x.route for x in menu_for_role(role)]) is visible


def test_each_role_includes_public():
    for role in ROLE_ROUTES:
        assert "/" in ROLE_ROUTES[role]
        assert "/products" in ROLE_ROUTES[role]


def test_invalid_role():
    with pytest.raises(ValueError):
        menu_for_role("ROLE_FAKE")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("12500000.50"), "12.500.001 ₫"),
        (Decimal("12500000.49"), "12.500.000 ₫"),
        ("0", "0 ₫"),
        ("-1250.50", "-1.251 ₫"),
    ],
)
def test_format_vnd(value, expected):
    assert format_vnd(value) == expected


def test_format_vnd_rejects_float():
    with pytest.raises(TypeError):
        format_vnd(1.5)


def test_format_vnd_rejects_invalid_text():
    with pytest.raises(ValueError):
        format_vnd("khong phai so")
