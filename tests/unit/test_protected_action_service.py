
"""Task 24: kiểm thử chặn callback theo ACTIVE và role."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import services.protected_action_service as guard_module
from models.app_error import AppError
from services.auth_session import AUTH_SESSION_USER_ID_KEY
from services.permissions import Permission
from services.protected_action_service import ProtectedActionService


class FakeStore:
    def __init__(self, user_id=7):
        self.data = {}
        if user_id is not None:
            self.data[AUTH_SESSION_USER_ID_KEY] = user_id

    def get(self, key):
        return self.data.get(key)

    def remove(self, key):
        self.data.pop(key, None)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return nullcontext()


@pytest.fixture
def guard(monkeypatch):
    state = {
        "record": {
            "id": 7,
            "role": "CUSTOMER",
            "status": "ACTIVE",
        },
        "locks": [],
        "actions": [],
        "auth_calls": 0,
    }

    class FakeRepo:
        def __init__(self, session):
            assert isinstance(session, FakeSession)

        def get_by_id(self, user_id, *, for_update=False):
            state["locks"].append(for_update)
            row = state["record"]

            if row is None or user_id != row["id"]:
                return None

            return dict(row)

    class FakeAuth:
        def require_user(self, *, session_store):
            state["auth_calls"] += 1

            user_id = session_store.get(
                AUTH_SESSION_USER_ID_KEY
            )

            if user_id is None:
                raise AppError(
                    "UNAUTHORIZED",
                    "Yêu cầu đăng nhập.",
                )

            return SimpleNamespace(user_id=user_id)

        def logout(self, *, session_store):
            session_store.remove(AUTH_SESSION_USER_ID_KEY)

    monkeypatch.setattr(
        guard_module,
        "UserRepository",
        FakeRepo,
    )

    service = ProtectedActionService(
        session_factory=FakeSession,
        auth_service=FakeAuth(),
    )

    return service, state, FakeStore()


def record_action(state, value="ok"):
    def action(session):
        state["actions"].append("called")
        return value

    return action


def test_customer_place_order_allowed_with_row_lock(guard):
    service, state, store = guard

    result = service.run_allowed(
        session_store=store,
        permission=Permission.PLACE_ORDER,
        action=record_action(state),
    )

    assert result == "ok"
    assert state["actions"] == ["called"]
    assert state["locks"] == [True]


def test_locked_account_stops_callback_and_clears_session(guard):
    service, state, store = guard

    service.run_allowed(
        session_store=store,
        permission=Permission.PLACE_ORDER,
        action=record_action(state),
    )

    state["record"]["status"] = "LOCKED"

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.PLACE_ORDER,
            action=record_action(state),
        )

    assert caught.value.error_code == "ACCOUNT_LOCKED"
    assert state["actions"] == ["called"]
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None


def test_missing_account_stops_callback_and_clears_session(guard):
    service, state, store = guard
    state["record"] = None

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.PLACE_ORDER,
            action=record_action(state),
        )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert state["actions"] == []
    assert store.get(AUTH_SESSION_USER_ID_KEY) is None


def test_customer_promoted_to_admin_loses_order_permission(guard):
    service, state, store = guard
    state["record"]["role"] = "ADMIN"

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.PLACE_ORDER,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []
    assert store.get(AUTH_SESSION_USER_ID_KEY) == 7


def test_customer_promoted_to_admin_gains_management_permission(guard):
    service, state, store = guard
    state["record"]["role"] = "ADMIN"

    assert service.run_allowed(
        session_store=store,
        permission=Permission.MANAGE_PRODUCTS,
        action=record_action(state),
    ) == "ok"


def test_admin_demoted_to_customer_loses_management_permission(guard):
    service, state, store = guard

    state["record"]["role"] = "ADMIN"

    service.run_allowed(
        session_store=store,
        permission=Permission.MANAGE_PRODUCTS,
        action=record_action(state),
    )

    state["record"]["role"] = "CUSTOMER"

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.MANAGE_PRODUCTS,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert len(state["actions"]) == 1


def test_forged_role_in_store_does_not_grant_super_admin(guard):
    service, state, store = guard

    store.data["phone_shop.auth.role"] = "SUPER_ADMIN"

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.MANAGE_ACCOUNTS,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []


def test_unknown_role_fails_closed(guard):
    service, state, store = guard
    state["record"]["role"] = "FAKE_ADMIN"

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.MANAGE_PRODUCTS,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []


def test_guest_cannot_run_action(guard):
    service, state, _ = guard

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=FakeStore(user_id=None),
            permission=Permission.PLACE_ORDER,
            action=record_action(state),
        )

    assert caught.value.error_code == "UNAUTHORIZED"
    assert state["actions"] == []


def test_invalid_permission_fails_closed(guard):
    service, state, store = guard

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission="MANAGE_PRODUCTS",
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []


def test_customer_may_modify_own_resource(guard):
    service, state, store = guard

    assert service.run_for_owner(
        session_store=store,
        permission=Permission.CANCEL_ORDER,
        resource_owner_id=7,
        action=record_action(state),
    ) == "ok"


def test_customer_cannot_modify_anothers_resource(guard):
    service, state, store = guard

    with pytest.raises(AppError) as caught:
        service.run_for_owner(
            session_store=store,
            permission=Permission.CANCEL_ORDER,
            resource_owner_id=8,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []


def test_admin_allows_foreign_resource_if_permission_all(guard):
    service, state, store = guard
    state["record"]["role"] = "ADMIN"

    assert service.run_for_owner(
        session_store=store,
        permission=Permission.CANCEL_ORDER,
        resource_owner_id=8,
        action=record_action(state),
    ) == "ok"


@pytest.mark.parametrize(
    "bad_id",
    [True, "7", 0, -1, 7.0],
)
def test_invalid_resource_owner_id_is_rejected(guard, bad_id):
    service, state, store = guard

    with pytest.raises(AppError) as caught:
        service.run_for_owner(
            session_store=store,
            permission=Permission.CANCEL_ORDER,
            resource_owner_id=bad_id,
            action=record_action(state),
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert state["actions"] == []


def test_customer_list_gets_own_filter(guard):
    service, _state, store = guard

    result = service.run_scoped_list(
        session_store=store,
        permission=Permission.VIEW_ORDERS,
        action=lambda session, owner_id: owner_id,
    )

    assert result == 7


def test_admin_list_gets_all_filter(guard):
    service, state, store = guard
    state["record"]["role"] = "ADMIN"

    result = service.run_scoped_list(
        session_store=store,
        permission=Permission.VIEW_ORDERS,
        action=lambda session, owner_id: owner_id,
    )

    assert result is None


def test_allow_scope_cannot_be_used_as_unrestricted_list(guard):
    service, state, store = guard

    with pytest.raises(AppError) as caught:
        service.run_scoped_list(
            session_store=store,
            permission=Permission.PLACE_ORDER,
            action=lambda session, owner_id: (
                state["actions"].append("called")
            ),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []


def test_own_scope_cannot_be_used_as_simple_allow(guard):
    service, state, store = guard

    with pytest.raises(AppError) as caught:
        service.run_allowed(
            session_store=store,
            permission=Permission.VIEW_ORDERS,
            action=record_action(state),
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert state["actions"] == []
