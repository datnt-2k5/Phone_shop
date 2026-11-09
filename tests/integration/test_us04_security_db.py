
"""Task 25: US04 regression checks on isolated phone_shop_test."""

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
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
from services.protected_action_service import ProtectedActionService
from ui.route_guard import RouteStatus, check_route_access

PASSWORD = "MatKhau123!"
FIXED_UTC = datetime(2026, 11, 9, 9, 0)


class StrictSessionStore:
    """Server-side session stand-in; never a client role source."""

    def __init__(self) -> None:
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value) -> None:
        self.data[key] = value

    def remove(self, key) -> None:
        self.data.pop(key, None)


def make_factory(connection: Connection):
    def create_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return create_session


def insert_order(db: Connection, *, customer_id: int, status: str) -> int:
    """Test fixture, NOT a production OrderService implementation."""

    token = token_hex(12)

    result = db.execute(
        text("""
            INSERT INTO orders (
                code,
                customer_id,
                idempotency_key,
                request_hash,
                status,
                receiver_name,
                receiver_phone,
                receiver_address,
                total_amount,
                created_at,
                confirmed_at,
                updated_at
            ) VALUES (
                :code,
                :customer_id,
                :idempotency_key,
                :request_hash,
                :status,
                :receiver_name,
                :receiver_phone,
                :receiver_address,
                :total_amount,
                :created_at,
                :confirmed_at,
                :updated_at
            )
        """),
        {
            "code": f"T25-{token}",
            "customer_id": customer_id,
            "idempotency_key": token,
            "request_hash": sha256(token.encode("ascii")).hexdigest(),
            "status": status,
            "receiver_name": "Khách kiểm thử",
            "receiver_phone": "0912345678",
            "receiver_address": "Test DB only",
            "total_amount": Decimal("150000.00"),
            "created_at": FIXED_UTC,
            "confirmed_at": FIXED_UTC if status == "CONFIRMED" else None,
            "updated_at": FIXED_UTC,
        },
    )

    return int(result.lastrowid)


def order_snapshot(db: Connection, order_id: int) -> dict:
    return dict(
        db.execute(
            text("""
                SELECT
                    id,
                    customer_id,
                    status,
                    total_amount,
                    cancelled_at,
                    cancelled_by,
                    cancel_reason,
                    updated_at
                FROM orders
                WHERE id = :order_id
            """),
            {"order_id": order_id},
        ).mappings().one()
    )


def set_user(
    db: Connection,
    user_id: int,
    *,
    role=None,
    status=None,
):
    if role is not None:
        db.execute(
            text("""
                UPDATE users
                SET role = :role
                WHERE id = :user_id
            """),
            {
                "role": role,
                "user_id": user_id,
            },
        )

    if status is not None:
        db.execute(
            text("""
                UPDATE users
                SET
                    status = :status,
                    lock_reason = :reason
                WHERE id = :user_id
            """),
            {
                "status": status,
                "reason": (
                    "Task 25 test"
                    if status == "LOCKED"
                    else None
                ),
                "user_id": user_id,
            },
        )


@pytest.fixture
def users(test_db: Connection):
    """Tạo hai Customer kiểm thử trong phone_shop_test."""

    factory = make_factory(test_db)

    auth = AuthService(session_factory=factory)

    authorization = AuthorizationService(
        session_factory=factory,
        auth_service=auth,
    )

    protected = ProtectedActionService(
        session_factory=factory,
        auth_service=auth,
    )

    result = {
        "db": test_db,
        "auth": auth,
        "authorization": authorization,
        "protected": protected,
    }

    for label in ("a", "b"):
        email = f"task25_{label}_{token_hex(8)}@example.test"

        registered = auth.register(
            email=email,
            password=PASSWORD,
            confirm_password=PASSWORD,
            full_name=f"Khách hàng {label.upper()}",
            phone="0912345678",
        )

        store = StrictSessionStore()

        auth.login(
            email=email,
            password=PASSWORD,
            session_store=store,
        )

        result[label] = {
            "id": registered.user_id,
            "email": email,
            "store": store,
        }

    return result


def test_role04_customer_cannot_view_another_customers_order(users):
    db = users["db"]

    order_id = insert_order(
        db,
        customer_id=users["b"]["id"],
        status="PENDING",
    )

    owner_id = int(
        order_snapshot(db, order_id)["customer_id"]
    )

    with pytest.raises(AppError) as caught:
        users["authorization"].require_resource_owner(
            permission=Permission.VIEW_ORDERS,
            resource_owner_id=owner_id,
            session_store=users["a"]["store"],
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_role06_forged_role_is_ignored_by_database_permission(users):
    store = users["a"]["store"]

    store.set("phone_shop.auth.role", "SUPER_ADMIN")
    store.set("role", "SUPER_ADMIN")

    with pytest.raises(AppError) as caught:
        users["authorization"].require_permission(
            permission=Permission.LOCK_UNLOCK_ACCOUNTS,
            session_store=store,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_role06_route_uses_database_role_not_forged_cache(users):
    db = users["db"]
    a = users["a"]

    a["store"].set(
        "phone_shop.auth.role",
        "SUPER_ADMIN",
    )

    actual = users["auth"].require_user(
        session_store=a["store"],
    )

    assert check_route_access(
        route="/super/accounts",
        role=actual.role,
    ).status == RouteStatus.FORBIDDEN

    set_user(
        db,
        a["id"],
        role="ADMIN",
    )

    actual = users["auth"].require_user(
        session_store=a["store"],
    )

    assert check_route_access(
        route="/admin/dashboard",
        role=actual.role,
    ).status == RouteStatus.ALLOW

    assert check_route_access(
        route="/super/accounts",
        role=actual.role,
    ).status == RouteStatus.FORBIDDEN


def test_role07_locked_between_session_and_next_action(users):
    a = users["a"]
    guard = users["protected"]
    calls = []

    assert guard.run_allowed(
        session_store=a["store"],
        permission=Permission.PLACE_ORDER,
        action=lambda session: "before-lock",
    ) == "before-lock"

    set_user(
        users["db"],
        a["id"],
        status="LOCKED",
    )

    with pytest.raises(AppError) as caught:
        guard.run_allowed(
            session_store=a["store"],
            permission=Permission.PLACE_ORDER,
            action=lambda session: calls.append("forbidden"),
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert calls == []

    assert a["store"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None


def test_role07_lock_invalidates_two_independent_sessions(users):
    a = users["a"]

    second = StrictSessionStore()

    users["auth"].login(
        email=a["email"],
        password=PASSWORD,
        session_store=second,
    )

    set_user(
        users["db"],
        a["id"],
        status="LOCKED",
    )

    for store in (a["store"], second):
        with pytest.raises(AppError) as caught:
            users["auth"].require_user(
                session_store=store,
            )

        assert caught.value.error_code == "ACCOUNT_LOCKED"

        assert store.get(
            AUTH_SESSION_USER_ID_KEY
        ) is None


def test_locked_account_cannot_login_again(users):
    a = users["a"]

    set_user(
        users["db"],
        a["id"],
        status="LOCKED",
    )

    new_store = StrictSessionStore()

    with pytest.raises(AppError) as caught:
        users["auth"].login(
            email=a["email"],
            password=PASSWORD,
            session_store=new_store,
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"

    assert new_store.get(
        AUTH_SESSION_USER_ID_KEY
    ) is None


@pytest.mark.parametrize("status", ["PENDING", "CONFIRMED"])
def test_role10_lock_does_not_mutate_existing_order(users, status):
    a = users["a"]

    order_id = insert_order(
        users["db"],
        customer_id=a["id"],
        status=status,
    )

    before = order_snapshot(
        users["db"],
        order_id,
    )

    set_user(
        users["db"],
        a["id"],
        status="LOCKED",
    )

    assert order_snapshot(
        users["db"],
        order_id,
    ) == before


@pytest.mark.parametrize("status", ["PENDING", "CONFIRMED"])
def test_locked_customer_cannot_cancel_existing_order(users, status):
    a = users["a"]

    order_id = insert_order(
        users["db"],
        customer_id=a["id"],
        status=status,
    )

    before = order_snapshot(
        users["db"],
        order_id,
    )

    set_user(
        users["db"],
        a["id"],
        status="LOCKED",
    )

    calls = []

    with pytest.raises(AppError) as caught:
        users["protected"].run_for_owner(
            session_store=a["store"],
            permission=Permission.CANCEL_ORDER,
            resource_owner_id=before["customer_id"],
            action=lambda session: calls.append("cancelled"),
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert calls == []

    assert order_snapshot(
        users["db"],
        order_id,
    ) == before


@pytest.mark.parametrize("status", ["PENDING", "CONFIRMED"])
def test_admin_can_view_locked_customer_orders_without_changing_them(
    users,
    status,
):
    db = users["db"]
    a = users["a"]
    b = users["b"]

    order_id = insert_order(
        db,
        customer_id=a["id"],
        status=status,
    )

    before = order_snapshot(
        db,
        order_id,
    )

    set_user(
        db,
        a["id"],
        status="LOCKED",
    )

    set_user(
        db,
        b["id"],
        role="ADMIN",
    )

    def read_order(session, owner_filter):
        assert owner_filter is None  # Admin có quyền ALL.

        return session.execute(
            text("""
                SELECT status
                FROM orders
                WHERE id = :order_id
            """),
            {"order_id": order_id},
        ).scalar_one()

    assert users["protected"].run_scoped_list(
        session_store=b["store"],
        permission=Permission.VIEW_ORDERS,
        action=read_order,
    ) == status

    assert order_snapshot(
        db,
        order_id,
    ) == before


@pytest.mark.parametrize(
    ("status", "permission"),
    [
        ("PENDING", Permission.CONFIRM_ORDER),
        ("CONFIRMED", Permission.COMPLETE_ORDER),
    ],
)
def test_admin_authorization_for_locked_customer_order(
    users,
    status,
    permission,
):
    """Only permission/read checks; US10 implements transitions."""

    db = users["db"]
    a = users["a"]
    b = users["b"]

    order_id = insert_order(
        db,
        customer_id=a["id"],
        status=status,
    )

    before = order_snapshot(
        db,
        order_id,
    )

    set_user(
        db,
        a["id"],
        status="LOCKED",
    )

    set_user(
        db,
        b["id"],
        role="ADMIN",
    )

    actual_status = users["protected"].run_allowed(
        session_store=b["store"],
        permission=permission,
        action=lambda session: session.execute(
            text("""
                SELECT status
                FROM orders
                WHERE id = :order_id
            """),
            {"order_id": order_id},
        ).scalar_one(),
    )

    assert actual_status == status

    assert order_snapshot(
        db,
        order_id,
    ) == before


def test_admin_can_authorize_cancel_of_locked_customer_order(users):
    db = users["db"]
    a = users["a"]
    b = users["b"]

    order_id = insert_order(
        db,
        customer_id=a["id"],
        status="PENDING",
    )

    before = order_snapshot(
        db,
        order_id,
    )

    set_user(
        db,
        a["id"],
        status="LOCKED",
    )

    set_user(
        db,
        b["id"],
        role="ADMIN",
    )

    result = users["protected"].run_for_owner(
        session_store=b["store"],
        permission=Permission.CANCEL_ORDER,
        resource_owner_id=before["customer_id"],
        action=lambda session: session.execute(
            text("""
                SELECT status
                FROM orders
                WHERE id = :order_id
            """),
            {"order_id": order_id},
        ).scalar_one(),
    )

    assert result == "PENDING"

    assert order_snapshot(
        db,
        order_id,
    ) == before


def test_role_changed_from_admin_to_customer_is_revoked(users):
    db = users["db"]
    b = users["b"]

    set_user(
        db,
        b["id"],
        role="ADMIN",
    )

    assert users["protected"].run_allowed(
        session_store=b["store"],
        permission=Permission.MANAGE_PRODUCTS,
        action=lambda session: "authorized",
    ) == "authorized"

    set_user(
        db,
        b["id"],
        role="CUSTOMER",
    )

    with pytest.raises(AppError) as caught:
        users["protected"].run_allowed(
            session_store=b["store"],
            permission=Permission.MANAGE_PRODUCTS,
            action=lambda session: "forbidden",
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_admin_customer_order_permission_is_all(users):
    b = users["b"]

    set_user(
        users["db"],
        b["id"],
        role="ADMIN",
    )

    grant = users["authorization"].require_permission(
        permission=Permission.VIEW_ORDERS,
        session_store=b["store"],
    )

    assert grant.role == Role.ADMIN
    assert grant.scope == Access.ALL
    assert grant.owner_filter_id() is None
