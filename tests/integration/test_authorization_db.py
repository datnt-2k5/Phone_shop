
"""US04 Task 22 - quyền theo MariaDB thật, chỉ phone_shop_test."""

from secrets import token_hex

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.authorization_service import AuthorizationService
from services.permissions import Access, Permission, Role

PASSWORD = "MatKhau123!"


class StrictSessionStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


def session_factory(connection: Connection):
    def make_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return make_session


@pytest.fixture
def accounts(test_db: Connection):
    factory = session_factory(test_db)
    auth = AuthService(session_factory=factory)
    service = AuthorizationService(
        session_factory=factory
    )

    stores = []
    users = []

    for suffix in ("a", "b"):
        email = (
            f"task22_{suffix}_{token_hex(8)}@example.test"
        )

        user = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Khách hàng {suffix.upper()}",
            phone="0912345678",
        )

        store = StrictSessionStore()

        auth.login(
            email=email,
            password=PASSWORD,
            session_store=store,
        )

        stores.append(store)
        users.append(user)

    return {
        "db": test_db,
        "users": users,
        "stores": stores,
        "service": service,
    }


def test_customer_can_only_access_own_data(accounts):
    a, b = accounts["users"]
    store_a = accounts["stores"][0]
    service = accounts["service"]

    allowed = service.require_resource_owner(
        permission=Permission.VIEW_ORDERS,
        resource_owner_id=a.user_id,
        session_store=store_a,
    )

    assert allowed.scope == Access.OWN
    assert allowed.owner_filter_id() == a.user_id

    with pytest.raises(AppError) as caught:
        service.require_resource_owner(
            permission=Permission.VIEW_ORDERS,
            resource_owner_id=b.user_id,
            session_store=store_a,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_role_is_reloaded_after_database_change(accounts):
    db = accounts["db"]
    user_a, user_b = accounts["users"]
    store_a = accounts["stores"][0]
    service = accounts["service"]

    before = service.require_permission(
        permission=Permission.VIEW_ORDERS,
        session_store=store_a,
    )

    assert before.role == Role.CUSTOMER
    assert before.scope == Access.OWN

    # Chỉ thay role trong transaction phone_shop_test.
    db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": user_a.user_id},
    )

    after = service.require_resource_owner(
        permission=Permission.VIEW_ORDERS,
        resource_owner_id=user_b.user_id,
        session_store=store_a,
    )

    assert after.role == Role.ADMIN
    assert after.scope == Access.ALL
    assert after.owner_filter_id() is None


def test_client_role_cache_does_not_grant_admin(accounts):
    store_a = accounts["stores"][0]

    store_a.set(
        "phone_shop.auth.role",
        "SUPER_ADMIN",
    )

    with pytest.raises(AppError) as caught:
        accounts["service"].require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store_a,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_only_super_admin_can_manage_accounts(accounts):
    db = accounts["db"]
    a, b = accounts["users"]
    store_a, store_b = accounts["stores"]
    service = accounts["service"]

    db.execute(
        text("""
            UPDATE users
            SET role = 'ADMIN'
            WHERE id = :id
        """),
        {"id": a.user_id},
    )

    db.execute(
        text("""
            UPDATE users
            SET role = 'SUPER_ADMIN'
            WHERE id = :id
        """),
        {"id": b.user_id},
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.MANAGE_ACCOUNTS,
            session_store=store_a,
        )

    assert caught.value.error_code == "FORBIDDEN"

    grant = service.require_permission(
        permission=Permission.MANAGE_ACCOUNTS,
        session_store=store_b,
    )

    assert grant.role == Role.SUPER_ADMIN
    assert grant.scope == Access.ALLOW


def test_locked_account_loses_access_during_session(accounts):
    db = accounts["db"]
    user_a = accounts["users"][0]
    store_a = accounts["stores"][0]
    service = accounts["service"]

    db.execute(
        text("""
            UPDATE users
            SET
                status = 'LOCKED',
                lock_reason = 'Task 22 test'
            WHERE id = :id
        """),
        {"id": user_a.user_id},
    )

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.VIEW_PROFILE,
            session_store=store_a,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert store_a.get(AUTH_SESSION_USER_ID_KEY) is None


def test_guest_can_view_products_but_not_order(accounts):
    service = accounts["service"]
    guest = StrictSessionStore()

    grant = service.require_permission(
        permission=Permission.VIEW_PRODUCTS,
        session_store=guest,
    )

    assert grant.role == Role.GUEST
    assert grant.scope == Access.ALLOW

    with pytest.raises(AppError) as caught:
        service.require_permission(
            permission=Permission.VIEW_ORDERS,
            session_store=guest,
        )

    assert caught.value.error_code == "UNAUTHORIZED"
