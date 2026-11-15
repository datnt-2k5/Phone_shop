
"""Task 52: tests for checkout cart/key lifecycle."""

from copy import deepcopy
from decimal import Decimal

import pytest

from models.app_error import AppError
from services.auth_session import CHECKOUT_SESSION_KEY
from services.cart_session import CartSession
from services.checkout_order_service import CheckoutOrderResult
from ui.checkout_flow import CheckoutFlow
from ui.checkout_key_state import (
    CHECKOUT_HASH,
    CHECKOUT_KEY,
    CheckoutKeyState,
)


class FakeStore:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)


class FakeCheckoutService:
    def __init__(self):
        self.calls = []
        self.error = None
        self.result = CheckoutOrderResult(
            outcome="CREATED",
            order={
                "id": 42,
                "code": "DH00000042",
                "status": "PENDING",
                "total_amount": Decimal("1000000.00"),
            },
            message="Đơn hàng đã được tiếp nhận.",
        )

    def create(self, *, session_store, checkout_request):
        self.calls.append(
            {
                "session_store": session_store,
                "request": deepcopy(checkout_request),
            }
        )

        if self.error is not None:
            raise self.error

        return self.result


def build_flow(*, authorized=True):
    store = FakeStore()
    cart = CartSession(store)
    cart.add(5, 1)
    backend = FakeCheckoutService()

    def authorize():
        if not authorized:
            raise AppError(
                "FORBIDDEN",
                "Không có quyền đặt hàng.",
            )

    flow = CheckoutFlow(
        cart=cart,
        keys=CheckoutKeyState(store),
        authorize=authorize,
        service=backend,
    )

    return store, cart, backend, flow


def place(flow, **changes):
    fields = {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "",
    }
    fields.update(changes)

    return flow.place_order(**fields)


def test_checkout_key_uses_cart_session_key():
    assert CHECKOUT_KEY == CHECKOUT_SESSION_KEY


def test_success_clears_cart_and_checkout_key():
    store, cart, backend, flow = build_flow()

    result = place(flow)

    assert result.outcome == "CREATED"
    assert result.order["code"] == "DH00000042"
    assert cart.items() == []
    assert store.get(CHECKOUT_KEY) is None
    assert store.get(CHECKOUT_HASH) is None
    assert len(backend.calls) == 1


def test_replay_is_also_a_successful_checkout():
    store, cart, backend, flow = build_flow()

    backend.result = CheckoutOrderResult(
        outcome="REPLAY",
        order={
            "id": 42,
            "code": "DH00000042",
            "status": "PENDING",
            "total_amount": Decimal("1000000.00"),
        },
        message="Đơn hàng đã được tiếp nhận trước đó.",
    )

    result = place(flow)

    assert result.outcome == "REPLAY"
    assert cart.items() == []
    assert store.get(CHECKOUT_KEY) is None


def test_business_error_keeps_cart_and_key():
    store, cart, backend, flow = build_flow()

    backend.error = AppError(
        "PRODUCT_UNAVAILABLE",
        "Sản phẩm không còn kinh doanh.",
    )

    with pytest.raises(AppError) as caught:
        place(flow)

    assert caught.value.error_code == "PRODUCT_UNAVAILABLE"
    assert cart.items() == [
        {"product_id": 5, "quantity": 1}
    ]
    assert store.get(CHECKOUT_KEY) is not None
    assert len(backend.calls) == 1


def test_unknown_network_error_keeps_cart_and_key():
    store, cart, backend, flow = build_flow()

    backend.error = RuntimeError("network lost")

    with pytest.raises(RuntimeError, match="network lost"):
        place(flow)

    assert cart.line_count() == 1
    assert store.get(CHECKOUT_KEY) is not None
    assert store.get(CHECKOUT_HASH) is not None


def test_retry_same_request_reuses_key():
    store, cart, backend, flow = build_flow()

    backend.error = RuntimeError("network lost")

    with pytest.raises(RuntimeError):
        place(flow)

    old_key = backend.calls[0]["request"]["idempotency_key"]

    backend.error = None
    result = place(flow)

    new_key = backend.calls[1]["request"]["idempotency_key"]

    assert old_key == new_key
    assert result.outcome == "CREATED"
    assert cart.items() == []
    assert store.get(CHECKOUT_KEY) is None


def test_receiver_change_creates_new_key_after_failure():
    store, cart, backend, flow = build_flow()

    backend.error = AppError(
        "PRODUCT_UNAVAILABLE",
        "Sản phẩm không còn kinh doanh.",
    )

    with pytest.raises(AppError):
        place(flow)

    old_key = store.get(CHECKOUT_KEY)

    with pytest.raises(AppError):
        place(
            flow,
            receiver_name="Nguyen Van B",
        )

    new_key = store.get(CHECKOUT_KEY)

    assert old_key != new_key
    assert cart.line_count() == 1


def test_cart_change_creates_new_key_after_failure():
    store, cart, backend, flow = build_flow()

    backend.error = AppError(
        "PRODUCT_UNAVAILABLE",
        "Sản phẩm không còn kinh doanh.",
    )

    with pytest.raises(AppError):
        place(flow)

    old_key = store.get(CHECKOUT_KEY)

    cart.set_quantity(5, 2)

    assert store.get(CHECKOUT_KEY) is None

    with pytest.raises(AppError):
        place(flow)

    new_key = store.get(CHECKOUT_KEY)

    assert new_key is not None
    assert new_key != old_key
    assert backend.calls[-1]["request"]["items"] == [
        {"product_id": 5, "quantity": 2}
    ]


def test_unauthorized_checkout_does_not_call_backend():
    store, cart, backend, flow = build_flow(
        authorized=False
    )

    with pytest.raises(AppError) as caught:
        place(flow)

    assert caught.value.error_code == "FORBIDDEN"
    assert backend.calls == []
    assert cart.line_count() == 1
    assert store.get(CHECKOUT_KEY) is None


def test_empty_cart_cannot_checkout():
    _store, cart, backend, flow = build_flow()
    cart.clear()

    with pytest.raises(AppError) as caught:
        place(flow)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert backend.calls == []


def test_invalid_receiver_data_does_not_call_backend():
    _store, cart, backend, flow = build_flow()

    with pytest.raises(AppError) as caught:
        place(flow, receiver_phone="")

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert backend.calls == []
    assert cart.line_count() == 1


def test_request_contains_only_expected_fields():
    _store, _cart, backend, flow = build_flow()

    place(flow)

    request = backend.calls[0]["request"]

    assert set(request) == {
        "receiver_name",
        "receiver_phone",
        "receiver_address",
        "note",
        "items",
        "idempotency_key",
    }

    assert request["items"] == [
        {"product_id": 5, "quantity": 1}
    ]

    assert "customer_id" not in request
    assert "sell_price" not in request
    assert "total_amount" not in request


def test_backend_receives_same_server_session_store():
    store, _cart, backend, flow = build_flow()

    place(flow)

    assert backend.calls[0]["session_store"] is store


def test_unexpected_backend_result_keeps_cart_and_key():
    store, cart, backend, flow = build_flow()

    backend.result = CheckoutOrderResult(
        outcome="UNKNOWN",
        order={},
        message="Unexpected result",
    )

    with pytest.raises(
        RuntimeError,
        match="Kết quả checkout không hợp lệ",
    ):
        place(flow)

    assert cart.line_count() == 1
    assert store.get(CHECKOUT_KEY) is not None


def test_execute_order_preserves_cart_until_ui_finalizes():
    store, cart, backend, flow = build_flow()

    checkout_request = flow.prepare_order(
        receiver_name="Nguyen Van A",
        receiver_phone="0912345678",
        receiver_address="Cao Lanh, Dong Thap",
        note="",
    )

    original_key = store.get(CHECKOUT_KEY)

    result = flow.execute_order(checkout_request)

    assert result.outcome == "CREATED"
    assert cart.line_count() == 1
    assert store.get(CHECKOUT_KEY) == original_key
    assert len(backend.calls) == 1

    flow.finalize_success()

    assert cart.items() == []
    assert store.get(CHECKOUT_KEY) is None
    assert store.get(CHECKOUT_HASH) is None