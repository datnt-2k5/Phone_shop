
"""Trang đăng nhập Phone Shop - US02 Task 15.

UI nhận email/mật khẩu và gọi AuthService.
Không tự xác thực mật khẩu hoặc quyết định role.
"""

import logging
from collections.abc import Callable

import flet as ft

from models.app_error import AppError
from services.auth_service import AuthService, LoginResult
from ui.components.notifications import notify

logger = logging.getLogger(__name__)


class LoginForm:
    """Form đăng nhập, có thể thay Service khi Unit Test."""

    def __init__(
        self,
        *,
        login_action: Callable[..., LoginResult],
        on_success: Callable[[LoginResult], None],
        notify_user: Callable[[str, bool], None],
        refresh: Callable[[], None],
    ) -> None:
        self._login_action = login_action
        self._on_success = on_success
        self._notify_user = notify_user
        self._refresh = refresh
        self._busy = False

        # 1. Hai ô nhập dữ liệu
        self.email = ft.TextField(
            label="Email *",
            hint_text="Ví dụ: nguyenvana@example.com",
            keyboard_type=ft.KeyboardType.EMAIL,
            autocorrect=False,
            autofocus=True,
        )

        self.password = ft.TextField(
            label="Mật khẩu *",
            password=True,
            can_reveal_password=True,
            on_submit=self.submit,
        )

        # 2. Lỗi của từng trường
        self.email_error = ft.Text(
            value="",
            color=ft.Colors.RED_700,
            size=12,
            visible=False,
        )

        self.password_error = ft.Text(
            value="",
            color=ft.Colors.RED_700,
            size=12,
            visible=False,
        )

        self.email.on_change = (
            lambda e: self.clear_field_error("email")
        )
        self.password.on_change = (
            lambda e: self.clear_field_error("password")
        )

        # 3. Thông báo đăng nhập thất bại
        self.feedback = ft.Text(
            value="",
            color=ft.Colors.RED_700,
            visible=False,
        )

        self.submit_button = ft.Button(
            "Đăng nhập",
            on_click=self.submit,
        )

        # 4. Bố cục form
        self.content = ft.Column(
            controls=[
                ft.Text(
                    "ĐĂNG NHẬP",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Sử dụng tài khoản Phone Shop "
                    "để truy cập hệ thống."
                ),
                self.email,
                self.email_error,
                self.password,
                self.password_error,
                self.submit_button,
                self.feedback,
            ],
            spacing=10,
        )

    def clear_field_error(self, field_name: str) -> None:
        """Ẩn thông báo lỗi khi người dùng sửa dữ liệu."""

        label = (
            self.email_error
            if field_name == "email"
            else self.password_error
        )

        label.value = ""
        label.visible = False
        self.feedback.visible = False
        self._refresh()

    def _show_feedback(self, message: str) -> None:
        """Hiển thị lỗi chung trong form."""

        self.feedback.value = message
        self.feedback.visible = True

    def submit(self, e=None) -> None:
        """Xử lý nhấn Đăng nhập hoặc phím Enter."""

        # Không cho gửi lặp trong khi đang xử lý.
        if self._busy:
            return

        self.email_error.visible = False
        self.email_error.value = ""
        self.password_error.visible = False
        self.password_error.value = ""
        self.feedback.visible = False

        email = self.email.value or ""
        password = self.password.value or ""

        # Kiểm tra ô trống trước khi gọi Service.
        missing = False

        if not email.strip():
            self.email_error.value = "Vui lòng nhập email."
            self.email_error.visible = True
            missing = True

        if not password:
            self.password_error.value = "Vui lòng nhập mật khẩu."
            self.password_error.visible = True
            missing = True

        if missing:
            self._show_feedback(
                "Vui lòng nhập đầy đủ email và mật khẩu."
            )
            self._refresh()
            return

        # Khóa nút trong lúc xử lý.
        self._busy = True
        self.submit_button.disabled = True
        self._refresh()

        try:
            # AuthService thật sẽ xác minh mật khẩu,
            # ACTIVE và lưu user_id vào server session.
            result = self._login_action(
                email=email,
                password=password,
            )

        except AppError as exc:
            # INVALID_CREDENTIALS, ACCOUNT_LOCKED...
            # Hiển thị thông báo từ Service.
            self._show_feedback(exc.message)
            self._notify_user(exc.message, True)

        except Exception:
            # Ghi log nội bộ, không lộ thông tin DB cho khách.
            logger.exception("Unexpected login UI error")

            message = (
                "Không thể đăng nhập lúc này. "
                "Vui lòng thử lại."
            )
            self._show_feedback(message)
            self._notify_user(message, True)

        else:
            # Điều hướng chỉ sau khi Service thành công.
            self._on_success(result)

        finally:
            # Không để mật khẩu lưu lại trong ô nhập.
            self.password.value = ""
            self._busy = False
            self.submit_button.disabled = False
            self._refresh()


def build_login_page(
    page: ft.Page,
    *,
    on_success: Callable[[LoginResult], None],
) -> ft.Column:
    """Kết nối LoginForm với AuthService và Flet Session."""

    service = AuthService()

    form = LoginForm(
        login_action=lambda **kwargs: service.login(
            email=kwargs["email"],
            password=kwargs["password"],
            session_store=page.session.store,
        ),
        on_success=on_success,
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
                "Chưa có tài khoản? Đăng ký",
                on_click=lambda e: page.navigate("/register"),
            ),
            ft.Button(
                "Về trang chủ",
                on_click=lambda e: page.navigate("/"),
            ),
        ],
        spacing=12,
    )
