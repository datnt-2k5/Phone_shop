
"""Trang đăng ký Flet - US01 Task 11.

Tách xử lý UI khỏi AuthService để kiểm thử mà không ghi vào DB.
"""

import logging
from collections.abc import Callable

import flet as ft

from models.app_error import AppError
from services.auth_service import AuthService, RegistrationResult
from ui.components.notifications import notify
from utils.validators import (
    validate_confirm_password,
    validate_email,
    validate_full_name,
    validate_password,
    validate_phone,
)

logger = logging.getLogger(__name__)

class RegistrationForm:
    """Form đăng ký, nhận callback để dễ kiểm thử độc lập."""

    def __init__(
        self,
        *,
        register_action: Callable[..., RegistrationResult],
        notify_user: Callable[[str, bool], None],
        refresh: Callable[[], None],
    ) -> None:
        self._register_action = register_action
        self._notify_user = notify_user
        self._refresh = refresh
        self._busy = False

        # 1. Tạo 5 ô nhập liệu
        self.full_name = ft.TextField(
            label="Họ và tên *",
            hint_text="Ví dụ: Nguyễn Văn A",
            keyboard_type=ft.KeyboardType.NAME,
            autofocus=True,
        )
        self.email = ft.TextField(
            label="Email *",
            hint_text="Ví dụ: nguyenvana@example.com",
            keyboard_type=ft.KeyboardType.EMAIL,
            autocorrect=False,
        )
        self.phone = ft.TextField(
            label="Số điện thoại *",
            hint_text="Ví dụ: 0912345678",
            keyboard_type=ft.KeyboardType.PHONE,
        )
        self.password = ft.TextField(
            label="Mật khẩu *",
            password=True,
            can_reveal_password=True,
        )
        self.confirm_password = ft.TextField(
            label="Xác nhận mật khẩu *",
            password=True,
            can_reveal_password=True,
            on_submit=self.submit,
        )

        self.fields = {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "password": self.password,
            "confirm_password": self.confirm_password,
        }

        # 2. Mỗi trường có một dòng thông báo lỗi riêng
        self.error_labels = {
            key: ft.Text(
                value="",
                size=12,
                color=ft.Colors.RED_700,
                visible=False,
            )
            for key in self.fields
        }

        # Khi sửa một ô, xóa thông báo lỗi cũ của ô đó
        for key, field in self.fields.items():
            field.on_change = (
                lambda e, name=key: self.clear_error(name)
            )

        # 3. Thông báo chung và nút đăng ký
        self.feedback = ft.Text(
            value="",
            visible=False,
        )
        self.submit_button = ft.Button(
            "Tạo tài khoản",
            on_click=self.submit,
        )

        # 4. Sắp xếp các thành phần giao diện
        controls: list[ft.Control] = [
            ft.Text(
                "ĐĂNG KÝ TÀI KHOẢN",
                size=25,
                weight=ft.FontWeight.BOLD,
            ),
            ft.Text(
                "Tài khoản mới mặc định có vai trò Khách hàng."
            ),
        ]

        for field_name in self.fields:
            controls.extend(
                [
                    self.fields[field_name],
                    self.error_labels[field_name],
                ]
            )

        controls.extend(
            [
                ft.Text(
                    "Mật khẩu tối thiểu 8 ký tự, "
                    "có chữ và số, tối đa 72 byte UTF-8.",
                    size=12,
                ),
                self.submit_button,
                self.feedback,
            ]
        )

        self.content = ft.Column(
            controls=controls,
            spacing=8,
        )

    def clear_error(self, field_name: str) -> None:
        """Ẩn lỗi của một trường khi người dùng sửa dữ liệu."""

        label = self.error_labels[field_name]
        label.value = ""
        label.visible = False

        if (
            self.feedback.visible
            and self.feedback.color == ft.Colors.RED_700
        ):
            self.feedback.visible = False

        self._refresh()

    def _show_errors(self, errors: dict) -> None:
        """Hiển thị lỗi ở ngay dưới trường tương ứng."""

        for key, message in errors.items():
            if key in self.error_labels:
                self.error_labels[key].value = str(message)
                self.error_labels[key].visible = True

    def _show_feedback(
        self,
        message: str,
        *,
        error: bool,
    ) -> None:
        """Thông báo tổng quát trong trang đăng ký."""

        self.feedback.value = message
        self.feedback.color = (
            ft.Colors.RED_700
            if error
            else ft.Colors.GREEN_700
        )
        self.feedback.visible = True

    def _validate_inputs(self) -> bool:
        """Kiểm tra trên UI để hiện nhiều lỗi cùng một lần."""

        checks = (
            lambda: validate_full_name(
                self.full_name.value or ""
            ),
            lambda: validate_email(
                self.email.value or ""
            ),
            lambda: validate_phone(
                self.phone.value or ""
            ),
            lambda: validate_password(
                self.password.value or ""
            ),
        )

        is_valid = True

        for validate in checks:
            try:
                validate()
            except AppError as exc:
                self._show_errors(exc.errors)
                is_valid = False

        # Xác nhận mật khẩu là trường bắt buộc
        if not self.confirm_password.value:
            self._show_errors(
                {
                    "confirm_password":
                        "Vui lòng xác nhận mật khẩu."
                }
            )
            is_valid = False
        else:
            try:
                validate_confirm_password(
                    self.password.value or "",
                    self.confirm_password.value,
                )
            except AppError as exc:
                self._show_errors(exc.errors)
                is_valid = False

        return is_valid

    def submit(self, e=None) -> None:
        """Xử lý nhấn Tạo tài khoản hoặc Enter."""

        if self._busy:
            return

        # 1. Xóa lỗi cũ
        for field_name in self.fields:
            label = self.error_labels[field_name]
            label.value = ""
            label.visible = False

        self.feedback.visible = False

        # 2. Kiểm tra trước khi gọi Service
        if not self._validate_inputs():
            self._show_feedback(
                "Vui lòng sửa thông tin được đánh dấu.",
                error=True,
            )
            self._refresh()
            return

        # 3. Chặn gửi liên tục trong lúc xử lý
        self._busy = True
        self.submit_button.disabled = True
        self._refresh()

        try:
            # 4. Gọi AuthService thật của Task 9–10
            self._register_action(
                full_name=self.full_name.value or "",
                email=self.email.value or "",
                phone=self.phone.value or "",
                password=self.password.value or "",
                confirm_password=(
                    self.confirm_password.value or ""
                ),
            )

        except AppError as exc:
            # 5. Lỗi nghiệp vụ: email trùng, validate...
            self._show_errors(exc.errors)
            self._show_feedback(
                exc.message,
                error=True,
            )
            self._notify_user(exc.message, True)

        except Exception:
            # Ghi log nội bộ, không tiết lộ lỗi cho người dùng.
            logger.exception("Unexpected error during account registration")

            message = "Đăng ký chưa thành công. Vui lòng thử lại."
            self._show_feedback(
                message,
                error=True,
            )
            self._notify_user(message, True)

        else:
            # 6. Thành công: xóa dữ liệu đã nhập
            for field in self.fields.values():
                field.value = ""

            message = (
                "Tạo tài khoản thành công! "
                "Bạn có thể đăng nhập sau."
            )
            self._show_feedback(
                message,
                error=False,
            )
            self._notify_user(message, False)

        finally:
            # 7. Khôi phục nút và cập nhật giao diện
            self._busy = False
            self.submit_button.disabled = False
            self._refresh()


def build_register_page(page: ft.Page) -> ft.Column:
    """Tạo nội dung thật cho route /register."""

    service = AuthService()

    form = RegistrationForm(
        register_action=service.register,
        notify_user=lambda message, error: notify(
            page,
            message,
            error=error,
        ),
        refresh=page.update,
    )

    return ft.Column(
        controls=[
            ft.Container(
                content=form.content,
                width=520,
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.WHITE,
            ),
            ft.Button(
                "Về trang chủ",
                on_click=lambda e: page.navigate("/"),
            ),
        ],
        spacing=12,
    )