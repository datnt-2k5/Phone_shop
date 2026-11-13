
"""Task 53 / US09-T06: checkout idempotency unit tests."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.checkout_idempotency_service import (
    CheckoutIdempotencyService,
)
from services.checkout_request_hash import create_request_hash

KEY_A = "123e4567-e89b-42d3-a456-426614174000"
KEY_B = "123e4567-e89b-42d3-a456-426614174111"


def valid_request():
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "",
        "items": [
            {"product_id": 12, "quantity": 2},
            {"product_id": 5, "quantity": 1},
        ],
        "idempotency_key": KEY_A,
    }


def previous_order(
    request=None,
    *,
    customer_id=7,
    status="PENDING",
):
    payload = request if request is not None else valid_request()

    return {
        "id": 501,
        "code": "ORD-000501",
        "customer_id": customer_id,
        "idempotency_key": payload["idempotency_key"],
        "request_hash": create_request_hash(payload),
        "status": status,
        "total_amount": Decimal("25000000.00"),
        "receiver_name": "Private User Data",
        "password_hash": "must-not-be-exposed",
        "unit_cost": Decimal("5000000.00"),
    }


class FakeAuth:
    def __init__(
        self,
        events,
        *,
        user_id=7,
        role="CUSTOMER",
        status="ACTIVE",
    ):
        self.events = events
        self.user_id = user_id
        self.role = role
        self.status = status
        self.calls = []

    def require_user(
        self,
        *,
        session_store,
        allowed_roles=None,
    ):
        self.events.append("authenticate")
        self.calls.append(
            {
                "session_store": session_store,
                "allowed_roles": allowed_roles,
            }
        )

        if self.user_id is None:
            raise AppError(
                "UNAUTHORIZED",
                "Vui lòng đăng nhập để tiếp tục.",
            )

        if self.status != "ACTIVE":
            raise AppError(
                "ACCOUNT_LOCKED",
                "Tài khoản đã bị khóa.",
            )

        if (
            allowed_roles is not None
            and self.role not in allowed_roles
        ):
            raise AppError(
                "FORBIDDEN",
                "Không có quyền đặt hàng.",
            )

        return SimpleNamespace(user_id=self.user_id)


class FakeSession:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __enter__(self):
        self.events.append("session_enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        self.events.append("session_exit")
        return False

    def commit(self):
        pytest.fail("Idempotency check cannot commit.")

    def rollback(self):
        pytest.fail("Idempotency check cannot roll back.")


class FakeOrders:
    def __init__(self, events, row=None):
        self.events = events
        self.row = row
        self.calls = []
        self.error = None

    def find_by_idempotency_key(
        self,
        *,
        customer_id,
        idempotency_key,
    ):
        self.events.append("order_lookup")

        self.calls.append(
            {
                "customer_id": customer_id,
                "idempotency_key": idempotency_key,
            }
        )

        if self.error is not None:
            raise self.error

        if self.row is None:
            return None

        if (
            self.row["customer_id"] == customer_id
            and self.row["idempotency_key"] == idempotency_key
        ):
            return dict(self.row)

        return None

    def create_pending(self, **kwargs):
        pytest.fail("Task 53 must not create orders.")

    def create_item(self, **kwargs):
        pytest.fail("Task 53 must not create order items.")


class Harness:
    def __init__(
        self,
        row=None,
        *,
        user_id=7,
        role="CUSTOMER",
        status="ACTIVE",
    ):
        self.events = []
        self.sessions = []
        self.store = object()

        self.auth = FakeAuth(
            self.events,
            user_id=user_id,
            role=role,
            status=status,
        )

        self.orders = FakeOrders(
            self.events,
            row=row,
        )

        self.service = CheckoutIdempotencyService(
            session_factory=self.session_factory,
            auth_service=self.auth,
            order_repository_factory=self.repository_factory,
        )

    def session_factory(self):
        session = FakeSession(self.events)
        self.sessions.append(session)
        return session

    def repository_factory(self, session):
        self.events.append("repository_factory")
        assert session in self.sessions
        return self.orders

    def check(self, request=None):
        return self.service.check(
            session_store=self.store,
            checkout_request=(
                valid_request()
                if request is None
                else request
            ),
        )


def assert_error(harness, request, error_code):
    with pytest.raises(AppError) as caught:
        harness.service.check(
            session_store=harness.store,
            checkout_request=request,
        )

    assert caught.value.error_code == error_code
    return caught.value


def test_new_key_returns_new_without_creating_order():
    harness = Harness()

    result = harness.check()

    assert result.outcome == "NEW"
    assert result.customer_id == 7
    assert result.idempotency_key == KEY_A
    assert result.request_hash == create_request_hash(
        valid_request()
    )
    assert result.existing_order is None
    assert result.normalized_request == valid_request()

    assert harness.orders.calls == [
        {
            "customer_id": 7,
            "idempotency_key": KEY_A,
        }
    ]


def test_same_key_same_hash_returns_existing_order():
    harness = Harness(previous_order())

    result = harness.check()

    assert result.outcome == "REPLAY"
    assert result.customer_id == 7
    assert result.existing_order == {
        "id": 501,
        "code": "ORD-000501",
        "status": "PENDING",
        "total_amount": Decimal("25000000.00"),
    }


def test_replay_does_not_expose_internal_repository_data():
    harness = Harness(previous_order())

    result = harness.check()

    assert "password_hash" not in result.existing_order
    assert "unit_cost" not in result.existing_order
    assert "receiver_name" not in result.existing_order
    assert "request_hash" not in result.existing_order


def test_same_key_different_hash_raises_conflict():
    harness = Harness(previous_order())

    changed = valid_request()
    changed["items"][0]["quantity"] = 3

    error = assert_error(
        harness,
        changed,
        "IDEMPOTENCY_CONFLICT",
    )

    assert "idempotency_key" in error.errors


def test_new_key_does_not_reuse_a_different_key_order():
    harness = Harness(previous_order())

    request = valid_request()
    request["idempotency_key"] = KEY_B

    result = harness.check(request)

    assert result.outcome == "NEW"
    assert result.existing_order is None
    assert result.request_hash == create_request_hash(
        valid_request()
    )


def test_same_key_from_different_customer_is_not_a_replay():
    harness = Harness(
        previous_order(customer_id=7),
        user_id=8,
    )

    result = harness.check()

    assert result.outcome == "NEW"
    assert result.customer_id == 8
    assert result.existing_order is None


def test_uppercase_key_is_normalized_before_lookup():
    harness = Harness(previous_order())

    request = valid_request()
    request["idempotency_key"] = KEY_A.upper()

    result = harness.check(request)

    assert result.outcome == "REPLAY"
    assert result.idempotency_key == KEY_A
    assert harness.orders.calls[0]["idempotency_key"] == KEY_A


def test_reordered_items_return_existing_order():
    harness = Harness(previous_order())

    request = valid_request()
    request["items"].reverse()

    assert harness.check(request).outcome == "REPLAY"


def test_normalized_whitespace_returns_existing_order():
    harness = Harness(previous_order())

    request = valid_request()
    request["receiver_name"] = "  Nguyen   Van  A  "
    request["receiver_address"] = " Cao Lanh,   Dong Thap "
    request["receiver_phone"] = " 0912345678 "

    assert harness.check(request).outcome == "REPLAY"


def test_missing_note_and_empty_note_are_equivalent():
    harness = Harness(previous_order())

    request = valid_request()
    request.pop("note")

    result = harness.check(request)

    assert result.outcome == "REPLAY"
    assert result.normalized_request["note"] == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("receiver_name", "Nguyen Van B"),
        ("receiver_phone", "0987654321"),
        ("receiver_address", "Da Nang"),
        ("note", "Giao buoi sang"),
    ],
)
def test_changed_business_field_causes_conflict(field, value):
    harness = Harness(previous_order())

    request = valid_request()
    request[field] = value

    assert_error(
        harness,
        request,
        "IDEMPOTENCY_CONFLICT",
    )


def test_changed_product_causes_conflict():
    harness = Harness(previous_order())

    request = valid_request()
    request["items"][0]["product_id"] = 13

    assert_error(
        harness,
        request,
        "IDEMPOTENCY_CONFLICT",
    )


@pytest.mark.parametrize(
    "status",
    [
        "PENDING",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
    ],
)
def test_replay_returns_saved_order_in_any_status(status):
    harness = Harness(previous_order(status=status))

    result = harness.check()

    assert result.outcome == "REPLAY"
    assert result.existing_order["status"] == status
    assert result.existing_order["id"] == 501


@pytest.mark.parametrize(
    "role",
    [
        "GUEST",
        "ADMIN",
        "SUPER_ADMIN",
    ],
)
def test_non_customer_is_rejected_before_order_lookup(role):
    harness = Harness(role=role)

    assert_error(
        harness,
        valid_request(),
        "FORBIDDEN",
    )

    assert harness.orders.calls == []
    assert harness.sessions == []


def test_unauthenticated_user_is_rejected():
    harness = Harness(user_id=None)

    assert_error(
        harness,
        valid_request(),
        "UNAUTHORIZED",
    )

    assert harness.orders.calls == []
    assert harness.sessions == []


def test_locked_account_is_rejected():
    harness = Harness(status="LOCKED")

    assert_error(
        harness,
        valid_request(),
        "ACCOUNT_LOCKED",
    )

    assert harness.orders.calls == []
    assert harness.sessions == []


@pytest.mark.parametrize(
    "bad_request",
    [
        None,
        [],
        "checkout",
        {"unexpected": "data"},
    ],
)
def test_invalid_request_fails_before_order_lookup(bad_request):
    harness = Harness()

    assert_error(
        harness,
        bad_request,
        "VALIDATION_ERROR",
    )

    assert harness.orders.calls == []
    assert harness.sessions == []


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "not-uuid",
        "123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_invalid_key_fails_before_order_lookup(bad_key):
    harness = Harness()

    request = valid_request()
    request["idempotency_key"] = bad_key

    assert_error(
        harness,
        request,
        "VALIDATION_ERROR",
    )

    assert harness.orders.calls == []


def test_request_is_not_mutated():
    harness = Harness()

    request = valid_request()
    original = deepcopy(request)

    harness.check(request)

    assert request == original


def test_normalized_result_contains_no_client_price():
    harness = Harness()

    result = harness.check()

    assert set(result.normalized_request) == {
        "receiver_name",
        "receiver_phone",
        "receiver_address",
        "note",
        "items",
        "idempotency_key",
    }

    assert result.normalized_request["items"] == [
        {"product_id": 12, "quantity": 2},
        {"product_id": 5, "quantity": 1},
    ]


def test_authentication_happens_before_order_lookup():
    harness = Harness()

    harness.check()

    assert harness.events == [
        "authenticate",
        "session_enter",
        "repository_factory",
        "order_lookup",
        "session_exit",
    ]


def test_repository_session_is_closed_after_read():
    harness = Harness()

    harness.check()

    assert len(harness.sessions) == 1
    assert harness.sessions[0].closed


def test_repository_error_is_not_silently_treated_as_new():
    harness = Harness()
    harness.orders.error = RuntimeError("Database offline")

    with pytest.raises(RuntimeError, match="Database offline"):
        harness.check()

    assert harness.sessions[0].closed


def test_invalid_checkout_does_not_calculate_hash(monkeypatch):
    harness = Harness()

    def fail_hash(payload):
        pytest.fail("Invalid checkout must not be hashed.")

    monkeypatch.setattr(
        "services.checkout_idempotency_service.create_request_hash",
        fail_hash,
    )

    request = valid_request()
    request["items"] = []

    assert_error(
        harness,
        request,
        "VALIDATION_ERROR",
    )


def test_request_hash_is_calculated_before_order_lookup(monkeypatch):
    harness = Harness()

    def hash_spy(payload):
        harness.events.append("calculate_hash")
        return create_request_hash(payload)

    monkeypatch.setattr(
        "services.checkout_idempotency_service.create_request_hash",
        hash_spy,
    )

    harness.check()

    assert harness.events.index("calculate_hash") < (
        harness.events.index("order_lookup")
    )


def test_service_never_needs_current_product_data():
    harness = Harness()

    request = valid_request()
    request["items"] = [
        {
            "product_id": 9_223_372_036_854_775_807,
            "quantity": 1,
        }
    ]

    result = harness.check(request)

    # The product ID does not have to exist for this read-only step.
    # Product validation is required only for NEW in the next task.
    assert result.outcome == "NEW"
    assert len(harness.orders.calls) == 1
