
"""Task 22: kiểm thử AuthorizationService không dùng MariaDB."""

from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.authorization_service import AuthorizationService
from services.permissions import Access, Permission, Role


class FakeSessionStore:
    def __init__(self, user_id=None):
        self.data = {}
        if user_id is not None:
            self.data[AUTH_SESSION_USER_ID_KEY] = user_id

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


class FakeAuth:
    def __init__(self, role="CUSTOMER", error=None):
        self.role = role
        self.error = error
        self.calls = 0

    def require_user(self, *, session_store):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return SimpleNamespace(
            user_id=7,
            role=self.role,
            status="ACTIVE",
        )


def make_service(role="CUSTOMER", error=None):
    fake_auth = FakeAuth(role=role, error=error)
    service = AuthorizationService(
        auth_service=fake_auth
    )
    store = FakeSessionStore(user_id=7)
    return service, store, fake_auth


@pytest.mark.parametrize(
    "permission",
    [
        Permission.VIEW_PRODUCTS,
        Permission.REGISTER,
        Permission.LOGIN,
    ],
)
def test_guest_public_permissions(permission):
    service, _, auth = make_service()

    result = service.require_permission(
        permission=permission
    )

    assert result.role == Role.GUEST
    assert result.user_id is None
    assert result.scope == Access.ALLOW
    assert auth.calls == 0


@pytest.mark.parametrize(
    "permission",
    [
        Permission.VIEW_PROFILE,
        Permission.PLACE_ORDER,
        Permission.MANAGE_ACCOUNTS,
    ],
)
def test_guest_protected_permissions_rejected(permission):
    service, _, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=permission
        )

    assert caught.value.error_code == "UNAUTHORIZED"


@pytest.mark.parametrize(
    ("permission", "scope"),
    [
        (Permission.VIEW_PRODUCTS, Access.ALLOW),
        (Permission.VIEW_PROFILE, Access.OWN),
        (Permission.EDIT_PROFILE, Access.OWN),
        (Permission.VIEW_ORDERS, Access.OWN),
        (Permission.PLACE_ORDER, Access.ALLOW),
    ],
)
def test_customer_allowed_scopes(permission, scope):
    service, store, auth = make_service()

    grant = service.require_permission(
        permission=permission,
        session_store=store,
    )

    assert grant.role == Role.CUSTOMER
    assert grant.user_id == 7
    assert grant.scope == scope
    assert auth.calls == 1


@pytest.mark.parametrize(
    "permission",
    [
        Permission.MANAGE_PRODUCTS,
        Permission.CONFIRM_ORDER,
        Permission.MANAGE_ACCOUNTS,
    ],
)
def test_customer_admin_actions_forbidden(permission):
    service, store, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=permission,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_admin_can_view_all_orders_but_cannot_manage_accounts():
    service, store, _ = make_service(role="ADMIN")

    grant = service.require_permission(
        permission=Permission.VIEW_ORDERS,
        session_store=store,
    )

    assert grant.scope == Access.ALL
    assert grant.owner_filter_id() is None

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_super_admin_can_manage_accounts():
    service, store, _ = make_service(
        role="SUPER_ADMIN"
    )

    grant = service.require_permission(
        permission=Permission.MANAGE_ACCOUNTS,
        session_store=store,
    )

    assert grant.scope == Access.ALLOW


def test_customer_own_resource_allowed():
    service, store, _ = make_service()

    grant = service.require_resource_owner(
        permission=Permission.VIEW_ORDERS,
        resource_owner_id=7,
        session_store=store,
    )

    assert grant.scope == Access.OWN
    assert grant.owner_filter_id() == 7


def test_customer_other_resource_forbidden():
    service, store, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_resource_owner(
            permission=Permission.VIEW_ORDERS,
            resource_owner_id=8,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_admin_other_resource_allowed():
    service, store, _ = make_service(role="ADMIN")

    grant = service.require_resource_owner(
        permission=Permission.VIEW_ORDERS,
        resource_owner_id=8,
        session_store=store,
    )

    assert grant.scope == Access.ALL


@pytest.mark.parametrize(
    "bad_owner",
    [True, "7", 7.0, 0, -1],
)
def test_invalid_resource_owner_id_rejected(bad_owner):
    service, store, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_resource_owner(
            permission=Permission.VIEW_ORDERS,
            resource_owner_id=bad_owner,
            session_store=store,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_allow_scope_cannot_be_used_as_owner_permission():
    service, store, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_resource_owner(
            permission=Permission.PLACE_ORDER,
            resource_owner_id=7,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_allow_scope_cannot_be_used_as_owner_filter():
    service, store, _ = make_service()

    grant = service.require_permission(
        permission=Permission.PLACE_ORDER,
        session_store=store,
    )

    with pytest.raises(AppError) as caught:
        grant.owner_filter_id()

    assert caught.value.error_code == "FORBIDDEN"


def test_role_in_session_cache_is_ignored():
    service, store, _ = make_service(
        role="CUSTOMER"
    )

    store.set(
        "phone_shop.auth.role",
        "SUPER_ADMIN",
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_forged_role_argument_rejected():
    service, store, _ = make_service()

    with pytest.raises(TypeError):
        service.require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store,
            role="SUPER_ADMIN",
        )


def test_permission_string_is_rejected():
    service, store, _ = make_service()

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission="MANAGE_ACCOUNTS",
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_unknown_database_role_rejected():
    service, store, _ = make_service(
        role="SOME_UNKNOWN_ROLE"
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.VIEW_PRODUCTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_database_role_guest_cannot_be_authenticated_role():
    service, store, _ = make_service(
        role="GUEST"
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.VIEW_PRODUCTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_permission_rechecks_identity_on_each_call():
    service, store, auth = make_service(
        role="CUSTOMER"
    )

    service.require_permission(
        permission=Permission.VIEW_PROFILE,
        session_store=store,
    )

    auth.role = "ADMIN"

    grant = service.require_permission(
        permission=Permission.VIEW_ORDERS,
        session_store=store,
    )

    assert grant.scope == Access.ALL
    assert auth.calls == 2


def test_locked_error_from_auth_is_propagated():
    service, store, _ = make_service(
        error=AppError(
            "ACCOUNT_LOCKED",
            "Tài khoản đã khóa.",
        ),
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.VIEW_ORDERS,
            session_store=store,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
