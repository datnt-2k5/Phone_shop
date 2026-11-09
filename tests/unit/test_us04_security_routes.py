
"""Task 25 / US04: regression security tests without database."""

from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.authorization_service import AuthorizationService
from services.permissions import PERMISSION_MATRIX, Access, Permission, Role
from ui.navigation import menu_for_role
from ui.route_guard import RouteStatus, check_route_access


class FakeStore:
    def __init__(self, user_id: int | None = 7) -> None:
        self.data = {}
        if user_id is not None:
            self.data[AUTH_SESSION_USER_ID_KEY] = user_id

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value) -> None:
        self.data[key] = value

    def remove(self, key) -> None:
        self.data.pop(key, None)


class FakeAuth:
    """Identity returned by a trusted AuthService (not client data)."""

    def __init__(self, role: str = "CUSTOMER") -> None:
        self.role = role
        self.calls = 0

    def require_user(self, *, session_store):
        self.calls += 1
        return SimpleNamespace(
            user_id=session_store.get(AUTH_SESSION_USER_ID_KEY),
            role=self.role,
            status="ACTIVE",
        )


@pytest.mark.parametrize(
    ("role", "route", "status", "redirect"),
    [
        ("GUEST", "/admin/dashboard", RouteStatus.LOGIN_REQUIRED, "/login"),
        ("GUEST", "/super/accounts", RouteStatus.LOGIN_REQUIRED, "/login"),
        ("CUSTOMER", "/admin/dashboard", RouteStatus.FORBIDDEN, None),
        ("CUSTOMER", "/admin/products", RouteStatus.FORBIDDEN, None),
        ("CUSTOMER", "/super/accounts", RouteStatus.FORBIDDEN, None),
        ("ADMIN", "/super/accounts", RouteStatus.FORBIDDEN, None),
        ("ADMIN", "/super/settings", RouteStatus.FORBIDDEN, None),
        ("ADMIN", "/admin/dashboard", RouteStatus.ALLOW, None),
        ("SUPER_ADMIN", "/admin/dashboard", RouteStatus.ALLOW, None),
        ("SUPER_ADMIN", "/super/accounts", RouteStatus.ALLOW, None),
    ],
)
def test_role01_to_role03_routes(role, route, status, redirect):
    decision = check_route_access(route=route, role=role)
    assert decision.status == status
    assert decision.redirect_to == redirect


@pytest.mark.parametrize("role", ["GUEST", "CUSTOMER", "ADMIN"])
def test_menu_never_exposes_super_admin_links(role):
    routes = {item.route for item in menu_for_role(role)}
    assert all(not route.startswith("/super/") for route in routes)


@pytest.mark.parametrize("role", ["GUEST", "CUSTOMER"])
def test_guest_customer_menu_never_exposes_admin_links(role):
    routes = {item.route for item in menu_for_role(role)}
    assert all(not route.startswith("/admin/") for route in routes)


@pytest.mark.parametrize("role", [Role.GUEST, Role.CUSTOMER, Role.ADMIN])
@pytest.mark.parametrize(
    "permission",
    [
        Permission.MANAGE_ACCOUNTS,
        Permission.LOCK_UNLOCK_ACCOUNTS,
        Permission.CHANGE_ROLE,
        Permission.MANAGE_SETTINGS,
    ],
)
def test_account_admin_privileges_are_super_admin_only(role, permission):
    assert PERMISSION_MATRIX[permission][role] == Access.DENY
    assert PERMISSION_MATRIX[permission][Role.SUPER_ADMIN] == Access.ALLOW


@pytest.mark.parametrize("claimed_role", ["ADMIN", "SUPER_ADMIN"])
def test_role06_forged_session_role_cannot_grant_admin_rights(claimed_role):
    store = FakeStore()
    store.set("phone_shop.auth.role", claimed_role)
    store.set("role", claimed_role)
    auth = FakeAuth("CUSTOMER")
    service = AuthorizationService(auth_service=auth)

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert auth.calls == 1


def test_role04_customer_may_not_claim_ownership_of_another_account():
    service = AuthorizationService(auth_service=FakeAuth("CUSTOMER"))

    with pytest.raises(AppError) as caught:
        service.require_resource_owner(
            permission=Permission.VIEW_ORDERS,
            resource_owner_id=8,
            session_store=FakeStore(user_id=7),
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_session_role_change_is_rechecked_by_backend():
    auth = FakeAuth("CUSTOMER")
    service = AuthorizationService(auth_service=auth)
    store = FakeStore()

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.MANAGE_PRODUCTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"

    auth.role = "ADMIN"

    grant = service.require_permission(
        permission=Permission.MANAGE_PRODUCTS,
        session_store=store,
    )

    assert grant.role == Role.ADMIN
    assert grant.scope == Access.ALLOW
    assert auth.calls == 2


def test_guest_role_spoof_without_authenticated_id_is_rejected():
    store = FakeStore(user_id=None)
    store.set("phone_shop.auth.role", "SUPER_ADMIN")
    service = AuthorizationService(auth_service=FakeAuth())

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.LOCK_UNLOCK_ACCOUNTS,
            session_store=store,
        )

    assert caught.value.error_code == "UNAUTHORIZED"


@pytest.mark.parametrize("role", ["FAKE_ADMIN", "", "ROOT"])
def test_unrecognized_role_fails_closed_at_route_guard(role):
    result = check_route_access(
        route="/admin/dashboard",
        role=role,
    )

    assert result.status == RouteStatus.FORBIDDEN
    assert result.redirect_to is None
