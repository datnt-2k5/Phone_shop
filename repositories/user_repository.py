
"""User Repository - thao tác với bảng users.

US01 - Task 9.
Repository chỉ truy vấn dữ liệu, không tự commit.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):
    """Repository quản lý dữ liệu tài khoản."""

    def get_by_email(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Tìm tài khoản bằng email đã chuẩn hóa."""

        row = self.session.execute(
            text("""
                SELECT
                    id,
                    email,
                    password_hash,
                    full_name,
                    phone,
                    role,
                    status
                FROM users
                WHERE email = :email
                LIMIT 1
            """),
            {"email": email},
        ).mappings().first()

        return dict(row) if row is not None else None

    def create_customer(
        self,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        phone: str,
        now_utc: datetime,
    ) -> int:
        """Tạo CUSTOMER/ACTIVE, trả về ID mới."""

        result = self.session.execute(
            text("""
                INSERT INTO users (
                    email,
                    password_hash,
                    full_name,
                    phone,
                    address,
                    role,
                    status,
                    lock_reason,
                    created_at,
                    updated_at,
                    updated_by
                )
                VALUES (
                    :email,
                    :password_hash,
                    :full_name,
                    :phone,
                    NULL,
                    'CUSTOMER',
                    'ACTIVE',
                    NULL,
                    :now_utc,
                    :now_utc,
                    NULL
                )
            """),
            {
                "email": email,
                "password_hash": password_hash,
                "full_name": full_name,
                "phone": phone,
                "now_utc": now_utc,
            },
        )

        if result.lastrowid is None:
            raise RuntimeError(
                "Không lấy được ID tài khoản vừa tạo."
            )

        return int(result.lastrowid)
