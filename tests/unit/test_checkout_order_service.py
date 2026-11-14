"""Task 54 / US09-T07: PENDING order creation unit tests."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from models.app_error import AppError
from services.checkout_idempotency_service import IdempotencyCheckResult
from services.checkout_order_service import CheckoutOrderService
from services.checkout_request_hash import create_request_hash
from services.checkout_validation import validate_checkout_request
from utils.time_utils import FixedClock

KEY = "123e4567-e89b-42d3-a456-426614174000"
FIXED_TIME = datetime(2026, 11, 13, 9, 30, tzinfo=UTC)


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
        "idempotency_key": KEY,
    }


class FakePreflight:
    def __init__(self, events):
        self.events = events
        self.replay = False
        self.error = None
        self.calls = []

    def check(self, *, session_store, checkout_request):
        self.events.append("idempotency")
        self.calls.append((session_store, checkout_request))

        if self.error is not None:
            raise self.error

        normalized = validate_checkout_request(checkout_request)

        existing = None

        if self.replay:
            existing = {
                "id": 88,
                "code": "ORD-0000000088",
                "status": "PENDING",
                "total_amount": Decimal("1000.00"),
            }

        return IdempotencyCheckResult(
            outcome="REPLAY" if self.replay else "NEW",
            customer_id=7,
            idempotency_key=normalized["idempotency_key"],
            request_hash=create_request_hash(normalized),
            normalized_request=normalized,
            existing_order=existing,
        )


class FakeTransaction:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("begin")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append(
            "rollback" if exc_type else "commit"
        )
        return False


class FakeSession:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("session_enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("session_exit")
        return False

    def begin(self):
        return FakeTransaction(self.events)


class FakeProducts:
    def __init__(self, events):
        self.events = events
        self.calls = []
        self.rows = {
            5: {
                "id": 5,
                "name": "Phone B",
                "brand_name": "Brand B",
                "status": "ACTIVE",
                "sell_price": Decimal("8000000.00"),
                "stock": 0,
                "cost_price": Decimal("1000.00"),
            },
            12: {
                "id": 12,
                "name": "Phone A",
                "brand_name": "Brand A",
                "status": "ACTIVE",
                "sell_price": Decimal("12000000.50"),
                "stock": 0,
                "cost_price": Decimal("1000.00"),
            },
        }

    def get_by_id(self, product_id, *, for_update=False):
        self.events.append("product_lookup")
        self.calls.append((product_id, for_update))

        row = self.rows.get(product_id)
        return dict(row) if row is not None else None


class FakeOrders:
    def __init__(self, events):
        self.events = events
        self.existing = None
        self.created = None
        self.items = []
        self.row = None
        self.failure = None
        self.update_ok = True
        self.missing_after_insert = False
        self.rechecks = []

    def find_by_idempotency_key(
        self,
        *,
        customer_id,
        idempotency_key,
    ):
        self.events.append("recheck")
        self.rechecks.append((customer_id, idempotency_key))
        return self.existing

    def create_pending(self, **kwargs):
        self.events.append("create_pending")

        if self.failure == "order":
            raise RuntimeError("order insert failed")

        self.created = kwargs.copy()
        self.row = {
            "id": 42,
            "code": kwargs["temporary_code"],
            "status": "PENDING",
            "total_amount": kwargs["total_amount"],
            "request_hash": kwargs["request_hash"],
            "customer_id": kwargs["customer_id"],
            "cost_price": Decimal("999.00"),
        }
        return 42

    def create_item(self, **kwargs):
        self.events.append("create_item")

        if self.failure == "item":
            raise RuntimeError("item insert failed")

        self.items.append(kwargs.copy())
        return len(self.items)

    def update_code(self, *, order_id, code):
        self.events.append("update_code")

        if self.update_ok:
            assert order_id == 42
            self.row["code"] = code

        return self.update_ok

    def get_by_id(self, order_id):
        self.events.append("read_created")
        assert order_id == 42

        if self.missing_after_insert:
            return None

        return dict(self.row)


class Harness:
    def __init__(self):
        self.events = []
        self.sessions = []
        self.store = object()

        self.preflight = FakePreflight(self.events)
        self.products = FakeProducts(self.events)
        self.orders = FakeOrders(self.events)

        self.service = CheckoutOrderService(
            session_factory=self.session_factory,
            clock=FixedClock(FIXED_TIME),
            idempotency_service=self.preflight,
            order_repository_factory=self.order_factory,
            product_repository_factory=self.product_factory,
        )

    def session_factory(self):
        session = FakeSession(self.events)
        self.sessions.append(session)
        return session

    def order_factory(self, session):
        assert session in self.sessions
        self.events.append("order_factory")
        return self.orders

    def product_factory(self, session):
        assert session in self.sessions
        self.events.append("product_factory")
        return self.products

    def create(self, request=None):
        payload = valid_request() if request is None else request

        return self.service.create(
            session_store=self.store,
            checkout_request=payload,
        )


def test_new_checkout_creates_pending_with_current_prices():
    h = Harness()

    result = h.create()

    assert result.outcome == "CREATED"
    assert result.order["id"] == 42
    assert result.order["code"] == "DH00000042"
    assert result.order["status"] == "PENDING"
    assert result.order["total_amount"] == Decimal(
        "32000001.00"
    )

    assert h.orders.created["total_amount"] == Decimal(
        "32000001.00"
    )
    assert h.orders.created["customer_id"] == 7
    assert h.orders.created["idempotency_key"] == KEY
    assert h.orders.created["request_hash"] == (
        create_request_hash(valid_request())
    )


def test_snapshot_contains_database_names_and_prices():
    h = Harness()
    h.create()

    assert h.orders.items == [
        {
            "order_id": 42,
            "product_id": 5,
            "product_name": "Phone B",
            "brand_name": "Brand B",
            "quantity": 1,
            "unit_price": Decimal("8000000.00"),
        },
        {
            "order_id": 42,
            "product_id": 12,
            "product_name": "Phone A",
            "brand_name": "Brand A",
            "quantity": 2,
            "unit_price": Decimal("12000000.50"),
        },
    ]


def test_product_rows_are_locked_in_ascending_id_order():
    h = Harness()
    h.create()

    assert h.products.calls == [
        (5, True),
        (12, True),
    ]


def test_temporary_and_official_codes_are_distinct():
    h = Harness()
    h.create()

    temporary = h.orders.created["temporary_code"]
    official = h.orders.row["code"]

    assert temporary.startswith("TMP-")
    assert len(temporary) <= 50
    assert official == "DH00000042"
    assert temporary != official


def test_created_timestamp_uses_injected_utc_clock():
    h = Harness()
    h.create()

    assert h.orders.created["now_utc"] == datetime(
        2026, 11, 13, 9, 30
    )


def test_result_does_not_expose_cost_or_stock():
    h = Harness()
    result = h.create()

    assert set(result.order) == {
        "id",
        "code",
        "status",
        "total_amount",
    }

    assert "cost_price" not in result.order
    assert "stock" not in result.order
    assert "request_hash" not in result.order

    assert all(
        "unit_cost" not in item
        for item in h.orders.items
    )


def test_pending_order_does_not_require_positive_stock():
    h = Harness()

    assert h.products.rows[5]["stock"] == 0
    assert h.products.rows[12]["stock"] == 0

    assert h.create().outcome == "CREATED"


def test_all_order_writes_share_one_transaction():
    h = Harness()
    h.create()

    assert h.events.count("begin") == 1
    assert h.events.count("commit") == 1
    assert h.events.count("rollback") == 0

    assert h.events.index("idempotency") < (
        h.events.index("product_lookup")
    )
    assert h.events.index("recheck") < (
        h.events.index("product_lookup")
    )
    assert h.events.index("create_pending") < (
        h.events.index("create_item")
    )
    assert h.events.index("update_code") < (
        h.events.index("commit")
    )


def test_replay_skips_product_lookup_and_write_transaction():
    h = Harness()
    h.preflight.replay = True

    result = h.create()

    assert result.outcome == "REPLAY"
    assert result.order["id"] == 88
    assert result.order["total_amount"] == Decimal("1000.00")
    assert h.sessions == []
    assert h.products.calls == []
    assert h.orders.created is None


def test_transaction_recheck_returns_existing_order():
    h = Harness()
    h.orders.existing = {
        "id": 91,
        "code": "ORD-0000000091",
        "status": "CONFIRMED",
        "total_amount": Decimal("1500.00"),
        "request_hash": create_request_hash(valid_request()),
    }

    result = h.create()

    assert result.outcome == "REPLAY"
    assert result.order["id"] == 91
    assert h.products.calls == []
    assert h.orders.created is None


def test_transaction_recheck_detects_conflict():
    h = Harness()
    h.orders.existing = {
        "id": 91,
        "code": "ORD-0000000091",
        "status": "PENDING",
        "total_amount": Decimal("1500.00"),
        "request_hash": "b" * 64,
    }

    with pytest.raises(AppError) as caught:
        h.create()

    assert caught.value.error_code == "IDEMPOTENCY_CONFLICT"
    assert h.products.calls == []
    assert h.orders.created is None


def test_missing_product_rolls_back():
    h = Harness()
    h.products.rows.pop(12)

    with pytest.raises(AppError) as caught:
        h.create()

    assert caught.value.error_code == "PRODUCT_UNAVAILABLE"
    assert "rollback" in h.events
    assert h.orders.created is None


def test_discontinued_product_rolls_back():
    h = Harness()
    h.products.rows[12]["status"] = "DISCONTINUED"

    with pytest.raises(AppError) as caught:
        h.create()

    assert caught.value.error_code == "PRODUCT_UNAVAILABLE"
    assert "rollback" in h.events
    assert h.orders.created is None


@pytest.mark.parametrize(
    "bad_price",
    [
        Decimal(0),
        Decimal("-1.00"),
        Decimal("NaN"),
        Decimal("1.001"),
        "1000000",
        1000000.0,
    ],
)
def test_invalid_database_price_is_rejected(bad_price):
    h = Harness()
    h.products.rows[12]["sell_price"] = bad_price

    with pytest.raises(AppError) as caught:
        h.create()

    assert caught.value.error_code == "PRICE_INVALID"
    assert "rollback" in h.events
    assert h.orders.created is None


def test_oversized_order_total_is_rejected():
    h = Harness()

    request = valid_request()
    request["items"] = [
        {
            "product_id": 12,
            "quantity": 2_147_483_647,
        }
    ]

    with pytest.raises(AppError) as caught:
        h.create(request)

    assert caught.value.error_code == "ORDER_TOTAL_EXCEEDED"
    assert h.orders.created is None


@pytest.mark.parametrize(
    "failure",
    ["order", "item"],
)
def test_insert_failure_rolls_back(failure):
    h = Harness()
    h.orders.failure = failure

    with pytest.raises(RuntimeError):
        h.create()

    assert "rollback" in h.events
    assert "commit" not in h.events


def test_code_update_failure_rolls_back():
    h = Harness()
    h.orders.update_ok = False

    with pytest.raises(
        RuntimeError,
        match="mã đơn hàng",
    ):
        h.create()

    assert "rollback" in h.events
    assert "commit" not in h.events


def test_missing_inserted_order_rolls_back():
    h = Harness()
    h.orders.missing_after_insert = True

    with pytest.raises(
        RuntimeError,
        match="Không tìm thấy đơn hàng",
    ):
        h.create()

    assert "rollback" in h.events


def test_authentication_error_stops_before_transaction():
    h = Harness()
    h.preflight.error = AppError(
        "UNAUTHORIZED",
        "Vui lòng đăng nhập.",
    )

    with pytest.raises(AppError) as caught:
        h.create()

    assert caught.value.error_code == "UNAUTHORIZED"
    assert h.sessions == []
    assert h.products.calls == []


def test_original_request_is_not_modified():
    h = Harness()

    request = valid_request()
    original = deepcopy(request)

    h.create(request)

    assert request == original


def test_normalized_note_is_saved():
    h = Harness()

    request = valid_request()
    request["note"] = "  Giao buoi sang  "

    h.create(request)

    assert h.orders.created["note"] == "Giao buoi sang"


def test_result_has_customer_safe_confirmation_message():
    h = Harness()

    result = h.create()

    assert "chờ" in result.message
    assert "chưa được giữ hàng" in result.message
