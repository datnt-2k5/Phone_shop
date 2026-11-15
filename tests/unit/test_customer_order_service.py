
"""Task 53: Customer order service unit tests."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.app_error import AppError
from services.customer_order_service import CustomerOrderService

NOW = datetime(2026, 11, 15, 5, 0)


class FakeAuth:
    def __init__(self, user_id=7, error=None):
        self.user_id = user_id
        self.error = error
        self.calls = 0

    def require_user(self, *, session_store, allowed_roles):
        self.calls += 1
        assert allowed_roles == ("CUSTOMER",)

        if self.error is not None:
            raise self.error

        return SimpleNamespace(user_id=self.user_id)


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRepository:
    def __init__(self):
        self.calls = []
        self.orders = {
            10: {
                "id": 10,
                "customer_id": 7,
                "code": "DH00000010",
                "status": "PENDING",
                "total_amount": Decimal("12000000.00"),
                "receiver_name": "Nguyen Van A",
                "receiver_phone": "0912345678",
                "receiver_address": "Da Nang",
                "note": "",
                "created_at": NOW,
                "request_hash": "sensitive",
            },
            11: {
                "id": 11,
                "customer_id": 8,
                "code": "DH00000011",
                "status": "PENDING",
                "total_amount": Decimal("8000000.00"),
                "receiver_name": "Nguyen Van B",
                "receiver_phone": "0987654321",
                "receiver_address": "Ha Noi",
                "note": "",
                "created_at": NOW,
            },
        }

    def count_for_customer(self, *, customer_id):
        self.calls.append(("count", customer_id))
        return sum(
            row["customer_id"] == customer_id
            for row in self.orders.values()
        )

    def list_for_customer(
        self,
        *,
        customer_id,
        limit,
        offset,
    ):
        self.calls.append(
            ("list", customer_id, limit, offset)
        )

        rows = [
            row
            for row in self.orders.values()
            if row["customer_id"] == customer_id
        ]
        rows.sort(key=lambda row: row["id"], reverse=True)

        return [
            {
                "id": row["id"],
                "code": row["code"],
                "status": row["status"],
                "total_amount": row["total_amount"],
                "created_at": row["created_at"],
            }
            for row in rows[offset:offset + limit]
        ]

    def get_owned_order(
        self,
        *,
        customer_id,
        order_id,
    ):
        self.calls.append(
            ("detail", customer_id, order_id)
        )

        row = self.orders.get(order_id)

        if row is None or row["customer_id"] != customer_id:
            return None

        return dict(row)

    def list_items(self, *, order_id):
        self.calls.append(("items", order_id))

        return [
            {
                "product_id": 5,
                "product_name": "Demo Phone",
                "brand_name": "Demo Brand",
                "quantity": 1,
                "unit_price": Decimal("12000000.00"),
                "unit_cost": Decimal("5000000.00"),
            }
        ]


def build_service(*, user_id=7, error=None):
    auth = FakeAuth(user_id=user_id, error=error)
    repository = FakeRepository()
    sessions = []
    store = object()

    def factory():
        session = FakeSession()
        sessions.append(session)
        return session

    service = CustomerOrderService(
        session_factory=factory,
        auth_service=auth,
        repository_factory=lambda session: repository,
    )

    return service, auth, repository, sessions, store


def test_customer_lists_only_own_orders():
    service, auth, _repository, _sessions, store = (
        build_service()
    )

    result = service.list_orders(
        session_store=store,
    )

    assert result["total"] == 1
    assert result["total_pages"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == 10
    assert auth.calls == 1


def test_different_customer_sees_different_orders():
    service, _, _, _, store = build_service(user_id=8)

    result = service.list_orders(session_store=store)

    assert result["total"] == 1
    assert result["items"][0]["id"] == 11


def test_pagination_uses_correct_offset():
    service, _, repository, _, store = build_service()

    service.list_orders(
        session_store=store,
        page=2,
        page_size=1,
    )

    assert ("list", 7, 1, 1) in repository.calls


def test_empty_order_page_returns_empty_list():
    service, _, _, _, store = build_service()

    result = service.list_orders(
        session_store=store,
        page=2,
        page_size=1,
    )

    assert result["items"] == []
    assert result["total"] == 1


def test_order_detail_uses_owner_scope():
    service, _, repository, _, store = build_service()

    result = service.get_order(
        session_store=store,
        order_id=10,
    )

    assert result["code"] == "DH00000010"
    assert result["status"] == "PENDING"
    assert len(result["items"]) == 1
    assert ("detail", 7, 10) in repository.calls
    assert ("items", 10) in repository.calls


def test_detail_never_exposes_cost_or_hash():
    service, _, _, _, store = build_service()

    result = service.get_order(
        session_store=store,
        order_id=10,
    )

    assert "request_hash" not in result
    assert "idempotency_key" not in result
    assert "customer_id" not in result
    assert "unit_cost" not in result["items"][0]


def test_other_customer_order_returns_not_found():
    service, _, repository, _, store = build_service()

    with pytest.raises(AppError) as caught:
        service.get_order(
            session_store=store,
            order_id=11,
        )

    assert caught.value.error_code == "NOT_FOUND"
    assert ("items", 11) not in repository.calls


def test_missing_order_returns_same_not_found():
    service, _, _, _, store = build_service()

    with pytest.raises(AppError) as caught:
        service.get_order(
            session_store=store,
            order_id=999,
        )

    assert caught.value.error_code == "NOT_FOUND"


@pytest.mark.parametrize(
    "bad_id",
    [0, -1, True, "10", 9_223_372_036_854_775_808],
)
def test_invalid_order_id_is_rejected(bad_id):
    service, _, repository, _, store = build_service()

    with pytest.raises(AppError) as caught:
        service.get_order(
            session_store=store,
            order_id=bad_id,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert repository.calls == []


@pytest.mark.parametrize(
    "bad_page",
    [0, -1, True, "1", 100_001],
)
def test_invalid_page_is_rejected(bad_page):
    service, _, _, _, store = build_service()

    with pytest.raises(AppError) as caught:
        service.list_orders(
            session_store=store,
            page=bad_page,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "bad_size",
    [0, -1, True, "10", 51],
)
def test_invalid_page_size_is_rejected(bad_size):
    service, _, _, _, store = build_service()

    with pytest.raises(AppError) as caught:
        service.list_orders(
            session_store=store,
            page_size=bad_size,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"


def test_authentication_happens_before_database_read():
    unauthorized = AppError(
        "UNAUTHORIZED",
        "Vui lòng đăng nhập.",
    )
    service, _, repository, sessions, store = build_service(
        error=unauthorized,
    )

    with pytest.raises(AppError) as caught:
        service.list_orders(session_store=store)

    assert caught.value.error_code == "UNAUTHORIZED"
    assert sessions == []
    assert repository.calls == []


def test_forbidden_customer_detail_never_reads_database():
    forbidden = AppError(
        "FORBIDDEN",
        "Không có quyền truy cập.",
    )
    service, _, repository, sessions, store = build_service(
        error=forbidden,
    )

    with pytest.raises(AppError) as caught:
        service.get_order(
            session_store=store,
            order_id=10,
        )

    assert caught.value.error_code == "FORBIDDEN"
    assert sessions == []
    assert repository.calls == []
