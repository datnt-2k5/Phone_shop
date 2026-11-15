
"""Task 54: deterministic tests of checkout UNIQUE race recovery."""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from models.app_error import AppError
from services.checkout_idempotency_service import IdempotencyCheckResult
from services.checkout_order_service import CheckoutOrderService

KEY = "123e4567-e89b-42d3-a456-426614174000"
HASH = "a" * 64


class FakeDuplicateError(Exception):
    def __init__(self, mysql_code: int):
        super().__init__(mysql_code, "Duplicate entry")


def sql_error(mysql_code: int) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO orders ...",
        {},
        FakeDuplicateError(mysql_code),
    )


class FakePreflight:
    def check(self, *, session_store, checkout_request):
        return IdempotencyCheckResult(
            outcome="NEW",
            customer_id=7,
            idempotency_key=KEY,
            request_hash=HASH,
            normalized_request={"items": []},
        )


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOrders:
    def __init__(self, record):
        self.record = record
        self.lookups = []

    def find_by_idempotency_key(
        self,
        *,
        customer_id,
        idempotency_key,
    ):
        self.lookups.append(
            (customer_id, idempotency_key)
        )
        return self.record


def rig(monkeypatch, *, record, error_code=1062):
    repository = FakeOrders(record)
    session_count = []

    def session_factory():
        session_count.append(1)
        return FakeSession()

    service = CheckoutOrderService(
        session_factory=session_factory,
        idempotency_service=FakePreflight(),
        order_repository_factory=lambda session: repository,
    )

    def duplicate_in_write_transaction(decision):
        raise sql_error(error_code)

    monkeypatch.setattr(
        service,
        "_create_pending_new",
        duplicate_in_write_transaction,
    )

    return service, repository, session_count


def existing_row(request_hash=HASH):
    return {
        "id": 42,
        "code": "DH00000042",
        "status": "PENDING",
        "total_amount": Decimal("12000000.00"),
        "request_hash": request_hash,
        "customer_id": 7,
        "unit_cost": Decimal("999.00"),
    }


def test_unique_same_key_same_hash_returns_replay(monkeypatch):
    service, repository, sessions = rig(
        monkeypatch,
        record=existing_row(),
    )

    result = service.create(
        session_store=object(),
        checkout_request={},
    )

    assert result.outcome == "REPLAY"
    assert result.order == {
        "id": 42,
        "code": "DH00000042",
        "status": "PENDING",
        "total_amount": Decimal("12000000.00"),
    }
    assert repository.lookups == [(7, KEY)]
    assert len(sessions) == 1


def test_unique_same_key_different_hash_returns_conflict(
    monkeypatch,
):
    service, repository, _sessions = rig(
        monkeypatch,
        record=existing_row("b" * 64),
    )

    with pytest.raises(AppError) as caught:
        service.create(
            session_store=object(),
            checkout_request={},
        )

    assert caught.value.error_code == "IDEMPOTENCY_CONFLICT"
    assert repository.lookups == [(7, KEY)]


def test_unrelated_unique_never_invents_a_replay(monkeypatch):
    service, repository, _sessions = rig(
        monkeypatch,
        record=None,
    )

    with pytest.raises(AppError) as caught:
        service.create(
            session_store=object(),
            checkout_request={},
        )

    assert caught.value.error_code == "CHECKOUT_RETRY_REQUIRED"
    assert repository.lookups == [(7, KEY)]


@pytest.mark.parametrize(
    "mysql_code",
    [1048, 1213, 1452],
)
def test_non_duplicate_database_error_is_not_hidden(
    monkeypatch,
    mysql_code,
):
    service, repository, _sessions = rig(
        monkeypatch,
        record=existing_row(),
        error_code=mysql_code,
    )

    with pytest.raises(IntegrityError):
        service.create(
            session_store=object(),
            checkout_request={},
        )

    assert repository.lookups == []
