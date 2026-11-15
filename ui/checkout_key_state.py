
"""Manage checkout UUID4 keys in Flet server-side Session.

Task 52 according to PM_Tool_Quan_Ly_Dien_Thoai_v2.5.xlsx.
"""

from uuid import UUID, uuid4

from services.auth_session import CHECKOUT_SESSION_KEY
from services.checkout_request_hash import create_request_hash

CHECKOUT_KEY = CHECKOUT_SESSION_KEY
CHECKOUT_HASH = "checkout_business_request_hash"

class CheckoutKeyState:
    def __init__(self, session_store):
        self.session_store = session_store

    @staticmethod
    def _is_valid_uuid4(value):
        if not isinstance(value, str):
            return False

        try:
            return UUID(value).version == 4
        except (ValueError, AttributeError):
            return False

    def prepare(self, business_payload):
        """Return a validated request with a stable checkout key.

        Same normalized business content -> keep key.
        Changed normalized business content -> new key.
        Invalid request -> do not overwrite session state.
        """
        if (
            not isinstance(business_payload, dict)
            or "idempotency_key" in business_payload
        ):
            raise ValueError(
                "Checkout payload không hợp lệ."
            )

        existing_key = self.session_store.get(CHECKOUT_KEY)

        if self._is_valid_uuid4(existing_key):
            key = existing_key
        else:
            key = str(uuid4())

        request = {
            **business_payload,
            "idempotency_key": key,
        }

        # Task 52 reuses the validation and canonical hash
        # already implemented in Tasks 50-51.
        request_hash = create_request_hash(request)
        previous_hash = self.session_store.get(CHECKOUT_HASH)

        if (
            self._is_valid_uuid4(existing_key)
            and previous_hash is not None
            and previous_hash != request_hash
        ):
            key = str(uuid4())
            request["idempotency_key"] = key

        self.session_store.set(CHECKOUT_KEY, key)
        self.session_store.set(CHECKOUT_HASH, request_hash)

        return request

    def clear(self):
        """Clear after successful checkout or logout."""
        self.session_store.remove(CHECKOUT_KEY)
        self.session_store.remove(CHECKOUT_HASH)
