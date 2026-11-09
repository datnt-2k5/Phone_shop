
"""User Repository: thao tác dữ liệu bảng users.

US01: Đăng ký tài khoản.
US02: Đăng nhập và kiểm tra session.
US03: Đọc và cập nhật hồ sơ cá nhân.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text

from repositories.base_repository import BaseRepository


class UserRepository(BaseRepository):
    """Repository cho bảng users."""

    def get_by_email(
        self,
        email: str,
    ) -> dict[str, Any] | None:
        """Lấy tài khoản theo email phục vụ đăng nhập."""

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
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        """Lấy tài khoản và thông tin hồ sơ bằng ID.

        for_update=True khóa hàng trong transaction,
        sử dụng khi cập nhật hồ sơ.
        """

        sql = """
            SELECT
                id,
                email,
                full_name,
                phone,
                address,
                avatar_url,
                role,
                status,
                created_at,
                updated_at,
                updated_by
            FROM users
            WHERE id = :user_id
            LIMIT 1
        """

        if for_update:
            sql += " FOR UPDATE"

        row = self.session.execute(
            text(sql),
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
        """Tạo tài khoản CUSTOMER/ACTIVE."""

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

    def update_own_profile(
        self,
        *,
        user_id: int,
        full_name: str,
        phone: str,
        address: str | None,
        now_utc: datetime,
    ) -> None:
        """Chỉ cập nhật ba trường hồ sơ và thông tin audit.

        user_id được cung cấp bởi ProfileService sau
        khi xác minh server-side Session.
        """

        self.session.execute(
            text("""
                UPDATE users
                SET
                    full_name = :full_name,
                    phone = :phone,
                    address = :address,
                    updated_at = :now_utc,
                    updated_by = :user_id
                WHERE id = :user_id
                  AND status = 'ACTIVE'
            """),
            {
                "user_id": user_id,
                "full_name": full_name,
                "phone": phone,
                "address": address,
                "now_utc": now_utc,
            },
        )


    def get_security_by_id(
        self,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        """Đọc hash mật khẩu trong Service bảo mật.

        Không sử dụng kết quả này để hiển thị ra giao diện.
        """

        sql = """
            SELECT
                id,
                password_hash,
                status
            FROM users
            WHERE id = :user_id
            LIMIT 1
        """

        if for_update:
            sql += " FOR UPDATE"

        row = self.session.execute(
            text(sql),
            {"user_id": user_id},
        ).mappings().first()

        return dict(row) if row is not None else None

    def update_password_hash(
        self,
        *,
        user_id: int,
        password_hash: str,
        now_utc: datetime,
    ) -> None:
        """Đổi hash và cập nhật audit của chính tài khoản."""

        result = self.session.execute(
            text("""
                UPDATE users
                SET
                    password_hash = :password_hash,
                    updated_at = :now_utc,
                    updated_by = :user_id
                WHERE id = :user_id
                  AND status = 'ACTIVE'
            """),
            {
                "user_id": user_id,
                "password_hash": password_hash,
                "now_utc": now_utc,
            },
        )

        if result.rowcount != 1:
            raise RuntimeError(
                "Không thể cập nhật mật khẩu cho tài khoản."
            )

    def update_avatar_url(
        self,
        *,
        user_id: int,
        avatar_url: str,
        now_utc: datetime,
    ) -> None:
        """Lưu đường dẫn avatar của chính tài khoản."""

        result = self.session.execute(
            text("""
                UPDATE users
                SET
                    avatar_url = :avatar_url,
                    updated_at = :now_utc,
                    updated_by = :user_id
                WHERE id = :user_id
                  AND status = 'ACTIVE'
            """),
            {
                "user_id": user_id,
                "avatar_url": avatar_url,
                "now_utc": now_utc,
            },
        )

        if result.rowcount != 1:
            raise RuntimeError(
                "Không thể cập nhật ảnh đại diện."
            )
