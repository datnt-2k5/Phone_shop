
"""Task 53 / US09-T06: checkout idempotency lookup.

Order of operations:
1. Reauthenticate CUSTOMER from the server-side session.
2. Validate and normalize the checkout request.
3. Calculate the canonical SHA-256 request_hash.
4. Look up orders by (customer_id, idempotency_key).
5. Return NEW, REPLAY or IDEMPOTENCY_CONFLICT.

This service intentionally does not:
- Look up current product prices, status or stock.
- Insert orders or order items.
- Change inventory or checkout session keys.
- Commit or roll back order transactions.

Concurrent insert conflicts are handled in US09-T08.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.order_repository import OrderRepository
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore
from services.checkout_request_hash import create_request_hash
from services.checkout_validation import validate_checkout_request


@dataclass(frozen=True, slots=True)
class IdempotencyCheckResult:
    """Result for the next checkout orchestration step."""

    outcome: Literal["NEW", "REPLAY"]
    customer_id: int
    idempotency_key: str
    request_hash: str
    normalized_request: dict[str, Any]
    existing_order: dict[str, Any] | None = None


class CheckoutIdempotencyService:
    """Read-only idempotency decision for an authenticated Customer."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
        order_repository_factory: Callable[
            [Session], OrderRepository
        ] = OrderRepository,
    ) -> None:
        self.session_factory = session_factory
        self.auth_service = auth_service or AuthService(
            session_factory=session_factory,
        )
        self.order_repository_factory = order_repository_factory

    def check(
        self,
        *,
        session_store: AuthSessionStore,
        checkout_request: object,
    ) -> IdempotencyCheckResult:
        """Inspect an incoming checkout before reading product data.

        Authentication is based on the server session, never
        on customer_id supplied by the request.
        """
        # Step 1: AuthService rechecks ACTIVE and CUSTOMER in DB.
        current_user = self.auth_service.require_user(
            session_store=session_store,
            allowed_roles=("CUSTOMER",),
        )

        # Step 2: Validate and normalize untrusted request.
        normalized = validate_checkout_request(
            checkout_request
        )

        # Step 3: Hash canonical business fields.
        # create_request_hash also validates its input.
        digest = create_request_hash(normalized)

        key = normalized["idempotency_key"]

        # Step 4: Only read orders.
        # No current-product query is allowed here.
        with self.session_factory() as session:
            repository = self.order_repository_factory(session)

            previous = repository.find_by_idempotency_key(
                customer_id=current_user.user_id,
                idempotency_key=key,
            )

        # Step 5a: New key. Do not create an order yet.
        if previous is None:
            return IdempotencyCheckResult(
                outcome="NEW",
                customer_id=current_user.user_id,
                idempotency_key=key,
                request_hash=digest,
                normalized_request=normalized,
            )

        # Step 5b: Existing key with different content.
        if previous["request_hash"] != digest:
            raise AppError(
                "IDEMPOTENCY_CONFLICT",
                (
                    "Yêu cầu đặt hàng đã thay đổi nhưng "
                    "vẫn sử dụng khóa checkout cũ."
                ),
                {
                    "idempotency_key": (
                        "Vui lòng sử dụng khóa checkout mới "
                        "khi thay đổi nội dung đặt hàng."
                    )
                },
            )

        # Step 5c: Existing key and same content.
        # Return only safe order-summary fields.
        # Do not return internal repository data.
        order_summary = {
            "id": previous["id"],
            "code": previous["code"],
            "status": previous["status"],
            "total_amount": previous["total_amount"],
        }

        return IdempotencyCheckResult(
            outcome="REPLAY",
            customer_id=current_user.user_id,
            idempotency_key=key,
            request_hash=digest,
            normalized_request=normalized,
            existing_order=order_summary,
        )
