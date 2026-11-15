
"""Task 55: Customer cart synchronized with MariaDB.

MariaDB is the source of truth.
Flet Page Session is only a local mirror.

The API matches CartSession so existing Cart/Checkout pages
need minimal wiring changes.
"""

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.cart_repository import CartRepository
from services.auth_service import AuthService
from services.auth_session import (
    CART_SESSION_KEY,
    CHECKOUT_HASH_SESSION_KEY,
    CHECKOUT_SESSION_KEY,
    AuthSessionStore,
)
from services.cart_session import CartSession
from services.session_store_utils import discard_session_key


class _MemoryStore:
    """Temporary store for reusing CartSession's validation rules."""

    def __init__(self, initial: object = None) -> None:
        self.values: dict[str, Any] = {}

        if initial is not None:
            self.values[CART_SESSION_KEY] = initial

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    def remove(self, key: str) -> None:
        self.values.pop(key, None)


class PersistentCart:
    """A DB-backed cart for the current authenticated Customer."""

    def __init__(
        self,
        store: AuthSessionStore,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
        repository_factory: Callable[
            [Session], CartRepository
        ] = CartRepository,
    ) -> None:
        self.store = store
        self.session_factory = session_factory
        self.auth_service = (
            auth_service
            if auth_service is not None
            else AuthService(session_factory=session_factory)
        )
        self.repository_factory = repository_factory

    def _customer_id(self) -> int:
        user = self.auth_service.require_user(
            session_store=self.store,
            allowed_roles=("CUSTOMER",),
        )
        return user.user_id

    @staticmethod
    def _decode(raw: str | None) -> list[dict[str, int]]:
        if raw is None:
            return []

        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "CART_INVALID",
                "Dữ liệu giỏ hàng database không hợp lệ.",
            ) from exc

        if not isinstance(value, list):
            raise AppError(
                "CART_INVALID",
                "Dữ liệu giỏ hàng database không hợp lệ.",
            )

        try:
            return CartSession(_MemoryStore(value)).items()
        except AppError as exc:
            raise AppError(
                "CART_INVALID",
                "Dữ liệu giỏ hàng database không hợp lệ.",
            ) from exc

    @staticmethod
    def _encode(items: list[dict[str, int]]) -> str:
        return json.dumps(
            items,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _mirror(self, items: list[dict[str, int]]) -> None:
        """Refresh local cart and invalidate stale checkout keys."""
        old = self.store.get(CART_SESSION_KEY)

        if old is None and not items:
            return

        if old == items:
            return

        if items:
            self.store.set(
                CART_SESSION_KEY,
                [dict(item) for item in items],
            )
        else:
            self.store.remove(CART_SESSION_KEY)

        discard_session_key(
            self.store,
            CHECKOUT_SESSION_KEY,
        )
        discard_session_key(
            self.store,
            CHECKOUT_HASH_SESSION_KEY,
        )

    def items(self) -> list[dict[str, int]]:
        """Always read the latest committed cart from MariaDB."""
        customer_id = self._customer_id()

        with self.session_factory() as session:
            repository = self.repository_factory(session)
            raw = repository.read(customer_id=customer_id)

        items = self._decode(raw)
        self._mirror(items)

        return [dict(item) for item in items]

    def _change(
        self,
        operation: Callable[[CartSession], Any],
    ) -> Any:
        """Lock, validate, update and commit atomically."""
        customer_id = self._customer_id()

        with self.session_factory() as session, session.begin():
            repository = self.repository_factory(session)

            before = self._decode(
                repository.lock_or_create(
                    customer_id=customer_id,
                )
            )

            working = CartSession(_MemoryStore(before))

            outcome = operation(working)
            after = working.items()

            if after != before:
                repository.save(
                    customer_id=customer_id,
                    items_json=self._encode(after),
                )

        # Mirror only after a successful transaction.
        self._mirror(after)

        return outcome

    def add(
        self,
        product_id: int,
        quantity: int = 1,
    ) -> list[dict[str, int]]:
        return self._change(
            lambda cart: cart.add(product_id, quantity)
        )

    def set_quantity(
        self,
        product_id: int,
        quantity: int,
    ) -> list[dict[str, int]]:
        return self._change(
            lambda cart: cart.set_quantity(product_id, quantity)
        )

    def remove(self, product_id: int) -> bool:
        return self._change(
            lambda cart: cart.remove(product_id)
        )

    def clear(self) -> None:
        self._change(lambda cart: cart.clear())

    def line_count(self) -> int:
        return len(self.items())

    def total_quantity(self) -> int:
        return sum(
            item["quantity"]
            for item in self.items()
        )

    def has_product(self, product_id: int) -> bool:
        CartSession._positive_int(
            product_id,
            "ID sản phẩm",
        )
        return any(
            item["product_id"] == product_id
            for item in self.items()
        )
