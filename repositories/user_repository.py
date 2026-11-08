
"""User Repository - truy vấn bảng users.

US01 - Task 9: Đăng ký tài khoản.
US02 - Task 14: Tải lại user bằng ID để kiểm tra session.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):
    """Các thao tác dữ liệu liên quan đến tài khoản."""

    def get_by_email(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Tìm tài khoản theo email đã chuẩn hóa."""

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

    def get_by_id(
        self,
        user_id: int,
    ) -> dict[str, Any] | None:
        """Tải tài khoản hiện tại từ database bằng ID."""

        row = self.session.execute(
            text("""
                SELECT
                    id,
                    email,
                    full_name,
                    phone,
                    role,
                    status
                FROM users
                WHERE id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id},
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
        """Tạo tài khoản CUSTOMER/ACTIVE và trả về ID mới."""

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
