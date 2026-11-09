
"""Task 24: kiểm tra role/LOCKED và bảo toàn đơn trên phone_shop_test."""

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
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService

PASSWORD = "MatKhau123!"
TEST_TIME = datetime(2026, 11, 9, 9, 0)


class StrictSessionStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def remove(self, key):
        self.data.pop(key, None)


def make_factory(connection: Connection):
    def create_session() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return create_session


def insert_order(db, customer_id: int, status: str) -> int:
    """Bản ghi thử nghiệm, chưa phải quy trình đặt hàng US10."""
    key = token_hex(12)

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
            )
            VALUES (
                :code,
                :customer_id,
                :key,
                :hash,
                :status,
                :name,
                :phone,
                :address,
                :total,
                :now,
                :confirmed_at,
                :now
            )
        """),
        {
            "code": f"T24-{key}",
            "customer_id": customer_id,
            "key": key,
            "hash": sha256(key.encode("ascii")).hexdigest(),
            "status": status,
            "name": "Khách hàng thử nghiệm",
            "phone": "0912345678",
            "address": "Đà Nẵng",
            "total": Decimal("100000.00"),
            "now": TEST_TIME,
            "confirmed_at": (
                TEST_TIME if status == "CONFIRMED" else None
            ),
        },
    )

    return int(result.lastrowid)


def read_order(db, order_id: int) -> dict:
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
                WHERE id = :id
            """),
            {"id": order_id},
        ).mappings().one()
    )


def change_account(
    db,
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
                WHERE id = :id
            """),
            {"role": role, "id": user_id},
        )

    if status is not None:
        db.execute(
            text("""
                UPDATE users
                SET
                    status = :status,
                    lock_reason = :reason
                WHERE id = :id
            """),
            {
                "status": status,
                "reason": (
                    "Task 24 test"
                    if status == "LOCKED"
                    else None
                ),
                "id": user_id,
            },
        )


@pytest.fixture
def accounts(test_db: Connection):
    """Tạo hai Customer trong transaction phone_shop_test."""

    factory = make_factory(test_db)
    auth = AuthService(session_factory=factory)

    guard = ProtectedActionService(
        session_factory=factory,
        auth_service=auth,
    )

    users = []
    stores = []

    for suffix in ("a", "b"):
        email = (
            f"task24_{suffix}_{token_hex(8)}@example.test"
        )

        created = auth.register(
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

        users.append(created)
        stores.append(store)

    return {
        "db": test_db,
        "guard": guard,
        "auth": auth,
        "a": users[0],
        "b": users[1],
        "sa": stores[0],
        "sb": stores[1],
    }


def test_active_customer_can_create_pending_order(accounts):
    a = accounts["a"]

    new_id = accounts["guard"].run_allowed(
        session_store=accounts["sa"],
        permission=Permission.PLACE_ORDER,
        action=lambda session: insert_order(
            session,
            a.user_id,
            "PENDING",
        ),
    )

    assert read_order(
        accounts["db"],
        new_id,
    )["status"] == "PENDING"


def test_locked_account_cannot_create_order_and_session_is_cleared(
    accounts,
):
    a = accounts["a"]

    change_account(
        accounts["db"],
        a.user_id,
        status="LOCKED",
    )

    called = []

    with pytest.raises(AppError) as caught:
        accounts["guard"].run_allowed(
            session_store=accounts["sa"],
            permission=Permission.PLACE_ORDER,
            action=lambda session: called.append("created"),
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert called == []

    assert accounts["sa"].get(
        AUTH_SESSION_USER_ID_KEY
    ) is None


def test_locked_customer_does_not_cancel_pending_or_confirmed_orders(
    accounts,
):
    a = accounts["a"]
    db = accounts["db"]

    pending = insert_order(
        db,
        a.user_id,
        "PENDING",
    )
    confirmed = insert_order(
        db,
        a.user_id,
        "CONFIRMED",
    )

    before = {
        i: read_order(db, i)
        for i in (pending, confirmed)
    }

    change_account(
        db,
        a.user_id,
        status="LOCKED",
    )

    for order_id in (pending, confirmed):
        called = []

        with pytest.raises(AppError) as caught:
            accounts["guard"].run_for_owner(
                session_store=accounts["sa"],
                permission=Permission.CANCEL_ORDER,
                resource_owner_id=a.user_id,
                action=lambda session, calls=called, target_id=order_id: calls.append(
                    target_id
                ),
            )

        # Lần đầu phát hiện LOCKED; lần sau Session đã bị xóa.
        assert caught.value.error_code in {
            "ACCOUNT_LOCKED",
            "UNAUTHORIZED",
        }
        assert called == []

    after = {
        i: read_order(db, i)
        for i in before
    }

    assert after == before


def test_customer_to_admin_changes_permission_without_relogin(
    accounts,
):
    a = accounts["a"]

    change_account(
        accounts["db"],
        a.user_id,
        role="ADMIN",
    )

    assert accounts["guard"].run_allowed(
        session_store=accounts["sa"],
        permission=Permission.MANAGE_PRODUCTS,
        action=lambda session: "allowed",
    ) == "allowed"

    with pytest.raises(AppError) as caught:
        accounts["guard"].run_allowed(
            session_store=accounts["sa"],
            permission=Permission.PLACE_ORDER,
            action=lambda session: "denied",
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_admin_to_customer_revokes_admin_permission(accounts):
    a = accounts["a"]
    db = accounts["db"]

    change_account(
        db,
        a.user_id,
        role="ADMIN",
    )

    accounts["guard"].run_allowed(
        session_store=accounts["sa"],
        permission=Permission.MANAGE_PRODUCTS,
        action=lambda session: True,
    )

    change_account(
        db,
        a.user_id,
        role="CUSTOMER",
    )

    with pytest.raises(AppError) as caught:
        accounts["guard"].run_allowed(
            session_store=accounts["sa"],
            permission=Permission.MANAGE_PRODUCTS,
            action=lambda session: True,
        )

    assert caught.value.error_code == "FORBIDDEN"

    assert accounts["sa"].get(
        AUTH_SESSION_USER_ID_KEY
    ) == a.user_id


def test_customer_list_is_filtered_by_verified_owner(accounts):
    a = accounts["a"]
    b = accounts["b"]
    db = accounts["db"]

    insert_order(db, a.user_id, "PENDING")
    insert_order(db, b.user_id, "PENDING")

    def query(session, owner_filter):
        assert owner_filter is not None

        return [
            row[0]
            for row in session.execute(
                text("""
                    SELECT customer_id
                    FROM orders
                    WHERE customer_id = :id
                """),
                {"id": owner_filter},
            ).all()
        ]

    owners = accounts["guard"].run_scoped_list(
        session_store=accounts["sa"],
        permission=Permission.VIEW_ORDERS,
        action=query,
    )

    assert owners == [a.user_id]


def test_admin_can_view_orders_of_locked_customer(accounts):
    a = accounts["a"]
    b = accounts["b"]
    db = accounts["db"]

    order_id = insert_order(
        db,
        a.user_id,
        "CONFIRMED",
    )

    before = read_order(db, order_id)

    change_account(
        db,
        a.user_id,
        status="LOCKED",
    )
    change_account(
        db,
        b.user_id,
        role="ADMIN",
    )

    def query(session, owner_filter):
        assert owner_filter is None  # Quyền ALL.

        return session.execute(
            text("""
                SELECT status
                FROM orders
                WHERE id = :id
            """),
            {"id": order_id},
        ).scalar_one()

    result = accounts["guard"].run_scoped_list(
        session_store=accounts["sb"],
        permission=Permission.VIEW_ORDERS,
        action=query,
    )

    assert result == "CONFIRMED"
    assert read_order(db, order_id) == before


def test_locked_customer_orders_not_touched_by_role_change(
    accounts,
):
    a = accounts["a"]
    db = accounts["db"]

    order_id = insert_order(
        db,
        a.user_id,
        "PENDING",
    )

    before = read_order(db, order_id)

    change_account(
        db,
        a.user_id,
        role="ADMIN",
    )
    change_account(
        db,
        a.user_id,
        status="LOCKED",
    )

    assert read_order(db, order_id) == before


def test_forged_session_role_does_not_override_database(accounts):
    accounts["sa"].set(
        "phone_shop.auth.role",
        "SUPER_ADMIN",
    )

    with pytest.raises(AppError) as caught:
        accounts["guard"].run_allowed(
            session_store=accounts["sa"],
            permission=Permission.MANAGE_ACCOUNTS,
            action=lambda session: True,
        )

    assert caught.value.error_code == "FORBIDDEN"


def test_callback_failure_rolls_back_written_order(accounts):
    a = accounts["a"]
    db = accounts["db"]

    before = db.execute(
        text("""
            SELECT COUNT(*)
            FROM orders
            WHERE customer_id = :id
        """),
        {"id": a.user_id},
    ).scalar_one()

    def failed_action(session):
        insert_order(
            session,
            a.user_id,
            "PENDING",
        )
        raise RuntimeError("Simulated order failure")

    with pytest.raises(
        RuntimeError,
        match="Simulated order failure",
    ):
        accounts["guard"].run_allowed(
            session_store=accounts["sa"],
            permission=Permission.PLACE_ORDER,
            action=failed_action,
        )

    after = db.execute(
        text("""
            SELECT COUNT(*)
            FROM orders
            WHERE customer_id = :id
        """),
        {"id": a.user_id},
    ).scalar_one()

    assert after == before
