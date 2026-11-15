
"""Task 53: Customer order history and secure order details."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.app_error import AppError
from repositories.customer_order_repository import (
    CustomerOrderRepository,
)
from services.auth_service import AuthService
from services.auth_session import AuthSessionStore


class CustomerOrderService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        auth_service: AuthService | None = None,
        repository_factory: Callable[
            [Session], CustomerOrderRepository
        ] = CustomerOrderRepository,
    ) -> None:
        self.session_factory = session_factory
        self.auth_service = (
            auth_service
            if auth_service is not None
            else AuthService(
                session_factory=session_factory,
            )
        )
        self.repository_factory = repository_factory

    def _customer_id(
        self,
        session_store: AuthSessionStore,
    ) -> int:
        user = self.auth_service.require_user(
            session_store=session_store,
            allowed_roles=("CUSTOMER",),
        )
        return user.user_id

    def list_orders(
        self,
        *,
        session_store: AuthSessionStore,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        customer_id = self._customer_id(session_store)

        if type(page) is not int or not 1 <= page <= 100_000:
            raise AppError(
                "VALIDATION_ERROR",
                "Số trang không hợp lệ.",
            )

        if (
            type(page_size) is not int
            or not 1 <= page_size <= 50
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "Số lượng đơn mỗi trang không hợp lệ.",
            )

        offset = (page - 1) * page_size

        with self.session_factory() as session:
            repository = self.repository_factory(session)

            total = repository.count_for_customer(
                customer_id=customer_id,
            )

            orders = repository.list_for_customer(
                customer_id=customer_id,
                limit=page_size,
                offset=offset,
            )

        total_pages = max(
            1,
            (total + page_size - 1) // page_size,
        )

        return {
            "items": orders,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        }

    def get_order(
        self,
        *,
        session_store: AuthSessionStore,
        order_id: int,
    ) -> dict[str, Any]:
        customer_id = self._customer_id(session_store)

        if (
            type(order_id) is not int
            or not 1 <= order_id <= 9_223_372_036_854_775_807
        ):
            raise AppError(
                "VALIDATION_ERROR",
                "ID đơn hàng không hợp lệ.",
            )

        with self.session_factory() as session:
            repository = self.repository_factory(session)

            order = repository.get_owned_order(
                customer_id=customer_id,
                order_id=order_id,
            )

            if order is None:
                # Do not reveal whether another Customer owns it.
                raise AppError(
                    "NOT_FOUND",
                    "Không tìm thấy đơn hàng.",
                )

            items = repository.list_items(
                order_id=order_id,
            )

        return {
            "id": order["id"],
            "code": order["code"],
            "status": order["status"],
            "total_amount": order["total_amount"],
            "created_at": order["created_at"],
            "receiver_name": order["receiver_name"],
            "receiver_phone": order["receiver_phone"],
            "receiver_address": order["receiver_address"],
            "note": order["note"],
            "items": [
                {
                    "product_id": item["product_id"],
                    "product_name": item["product_name"],
                    "brand_name": item["brand_name"],
                    "quantity": item["quantity"],
                    "unit_price": item["unit_price"],
                }
                for item in items
            ],
        }
