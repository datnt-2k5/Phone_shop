
"""Task 21 - Giao diện đổi mật khẩu và avatar, Flet 1.0.5."""

import logging
import re
from collections.abc import Callable

import flet as ft

from models.app_error import AppError
from services.account_security_service import (
    MAX_AVATAR_BYTES,
    AvatarResult,
    prepare_avatar,
)
from utils.validators import validate_confirm_password, validate_password

logger = logging.getLogger(__name__)

ConfirmAction = Callable[
    [str, str, Callable[[], None], Callable[[], None]],
    None,
]


def avatar_src(url: str | None) -> str | None:
    """Chỉ chấp nhận đường dẫn avatar UUID do Backend tạo."""
    if url and re.fullmatch(
        r"avatars/[0-9a-f]{32}\.(jpg|png)",
        url,
    ):
        return f"/{url}"
    return None


def open_security_confirmation(
    page: ft.Page,
    title: str,
    message: str,
    on_confirm: Callable[[], None],
    on_cancel: Callable[[], None],
) -> None:
    """Chỉ gọi callback khi hộp thoại đã đóng hoàn toàn."""
    choice: str | None = None
    handled = False

    def choose(value: str) -> None:
        nonlocal choice

        if choice is None:
            choice = value
            page.pop_dialog()

    def dismissed(e) -> None:
        nonlocal handled

        if handled:
            return

        handled = True

        if choice == "confirm":
            on_confirm()
        else:
            on_cancel()

    page.show_dialog(
        ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(
                    "Quay lại",
                    on_click=lambda e: choose("cancel"),
                ),
                ft.Button(
                    "Xác nhận",
                    on_click=lambda e: choose("confirm"),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=dismissed,
        )
    )


class AccountSecuritySection:
    """Quản lý đổi mật khẩu và upload avatar."""

    def __init__(
        self,
        *,
        password_action: Callable[..., None],
        avatar_action: Callable[..., AvatarResult],
        ask_confirmation: ConfirmAction,
        notify_user: Callable[[str, bool], None],
        refresh: Callable[[], None],
        on_password_changed: Callable[[], None],
        on_avatar_saved: Callable[[], None],
        on_auth_lost: Callable[[], None],
        file_picker: ft.FilePicker,
        initial_avatar_url: str | None = None,
    ) -> None:
        self._password_action = password_action
        self._avatar_action = avatar_action
        self._ask_confirmation = ask_confirmation
        self._notify_user = notify_user
        self._refresh = refresh
        self._on_password_changed = on_password_changed
        self._on_avatar_saved = on_avatar_saved
        self._on_auth_lost = on_auth_lost

        self._pending_password: dict[str, str] | None = None
        self._selected_avatar: bytes | None = None
        self._avatar_confirmation_pending = False
        self._busy = False
        self._current_avatar = initial_avatar_url

        # ==================================================
        # 1. FORM ĐỔI MẬT KHẨU
        # ==================================================
        self.old_password = ft.TextField(
            label="Mật khẩu hiện tại *",
            password=True,
            can_reveal_password=True,
        )
        self.new_password = ft.TextField(
            label="Mật khẩu mới *",
            password=True,
            can_reveal_password=True,
        )
        self.confirm_password = ft.TextField(
            label="Xác nhận mật khẩu mới *",
            password=True,
            can_reveal_password=True,
        )

        self.password_fields = {
            "old_password": self.old_password,
            "new_password": self.new_password,
            "confirm_new_password": self.confirm_password,
        }

        self.password_errors = {
            name: ft.Text(
                value="",
                visible=False,
                color=ft.Colors.RED_700,
                size=12,
            )
            for name in self.password_fields
        }

        for name, field in self.password_fields.items():
            field.on_change = (
                lambda e, key=name: self.clear_password_error(key)
            )

        self.open_password_button = ft.Button(
            "Đổi mật khẩu",
            on_click=self.start_password_edit,
        )
        self.save_password_button = ft.Button(
            "Tiếp tục",
            on_click=self.request_password_change,
        )
        self.cancel_password_button = ft.Button(
            "Hủy",
            on_click=self.cancel_password_edit,
        )
        self.password_feedback = ft.Text(
            value="",
            visible=False,
        )

        password_controls: list[ft.Control] = []

        for name, field in self.password_fields.items():
            password_controls.extend(
                [field, self.password_errors[name]]
            )

        password_controls.extend(
            [
                ft.Text(
                    "Mật khẩu mới tối thiểu 8 ký tự, có chữ và số, "
                    "tối đa 72 byte UTF-8.",
                    size=12,
                ),
                ft.Row(
                    controls=[
                        self.save_password_button,
                        self.cancel_password_button,
                    ],
                    wrap=True,
                ),
            ]
        )

        self.password_form = ft.Column(
            controls=password_controls,
            spacing=8,
            visible=False,
        )

        # ==================================================
        # 2. ẢNH ĐẠI DIỆN
        # ==================================================
        current_src = avatar_src(initial_avatar_url)

        self.avatar_image = ft.Image(
            src=current_src or "",
            width=112,
            height=112,
            fit=ft.BoxFit.COVER,
            border_radius=56,
            visible=current_src is not None,
        )

        self.avatar_placeholder = ft.Icon(
            ft.Icons.PERSON,
            size=64,
            color=ft.Colors.GREY_600,
            visible=current_src is None,
        )

        self.avatar_label = ft.Text(
            "JPG/PNG, tối đa 2 MiB",
            size=12,
        )
        self.avatar_feedback = ft.Text(
            value="",
            visible=False,
        )

        # Quan trọng: dùng ft.FilePicker THẬT.
        self.file_picker = file_picker
        file_picker.on_result = self.on_files_picked

        self.pick_button = ft.Button(
            "Chọn ảnh",
            action=ft.PickFiles(
                file_picker,
                allow_multiple=False,
                with_data=True,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["jpg", "jpeg", "png"],
                cancel_upload_on_window_blur=False,
            ),
        )

        self.save_avatar_button = ft.Button(
            "Lưu ảnh",
            on_click=self.request_avatar_save,
            disabled=True,
        )
        self.cancel_avatar_button = ft.Button(
            "Bỏ ảnh đã chọn",
            on_click=self.cancel_avatar_selection,
            disabled=True,
        )

        # ==================================================
        # 3. BỐ CỤC CHUNG
        # ==================================================
        self.content = ft.Column(
            spacing=14,
            controls=[
                ft.Text(
                    "ẢNH ĐẠI DIỆN",
                    weight=ft.FontWeight.BOLD,
                    size=17,
                ),
                ft.Row(
                    controls=[
                        self.avatar_image,
                        self.avatar_placeholder,
                    ],
                    wrap=True,
                ),
                self.avatar_label,
                ft.Row(
                    controls=[
                        self.pick_button,
                        self.save_avatar_button,
                        self.cancel_avatar_button,
                    ],
                    wrap=True,
                ),
                self.avatar_feedback,
                ft.Divider(),
                ft.Text(
                    "BẢO MẬT TÀI KHOẢN",
                    weight=ft.FontWeight.BOLD,
                    size=17,
                ),
                ft.Text(
                    "Đổi mật khẩu thành công sẽ "
                    "đăng xuất phiên hiện tại."
                ),
                self.open_password_button,
                self.password_form,
                self.password_feedback,
            ],
        )

    def _feedback(
        self,
        control: ft.Text,
        message: str,
        error: bool,
    ) -> None:
        """Thông báo thành công hoặc thất bại."""
        control.value = message
        control.visible = True
        control.color = (
            ft.Colors.RED_700
            if error
            else ft.Colors.GREEN_700
        )

    # ======================================================
    # 4. ĐỔI MẬT KHẨU
    # ======================================================
    def _clear_password_values(self) -> None:
        """Xóa dữ liệu mật khẩu, giữ thông báo lỗi nếu có."""
        self._pending_password = None

        for control in self.password_fields.values():
            control.value = ""

    def _clear_passwords(self) -> None:
        """Xóa cả giá trị và thông báo lỗi."""
        self._clear_password_values()

        for label in self.password_errors.values():
            label.value = ""
            label.visible = False

    def clear_password_error(self, name: str) -> None:
        label = self.password_errors[name]
        label.visible = False
        label.value = ""

        if self.password_feedback.color == ft.Colors.RED_700:
            self.password_feedback.visible = False

        self._refresh()

    def start_password_edit(self, e=None) -> None:
        if self._busy:
            return

        self._clear_passwords()
        self.password_feedback.visible = False
        self.password_form.visible = True
        self.open_password_button.visible = False
        self._refresh()

    def cancel_password_edit(self, e=None) -> None:
        if self._busy or self._pending_password is not None:
            return

        self._clear_passwords()
        self.password_feedback.visible = False
        self.password_form.visible = False
        self.open_password_button.visible = True
        self._refresh()

    def request_password_change(self, e=None) -> None:
        """Kiểm tra dữ liệu rồi mở xác nhận, chưa gọi Backend."""
        if (
            self._busy
            or not self.password_form.visible
            or self._pending_password is not None
        ):
            return

        for label in self.password_errors.values():
            label.visible = False

        self.password_feedback.visible = False

        old = self.old_password.value or ""
        new = self.new_password.value or ""
        confirm = self.confirm_password.value or ""

        if not old:
            label = self.password_errors["old_password"]
            label.value = "Nhập mật khẩu hiện tại."
            label.visible = True

        try:
            validate_password(new)
        except AppError as exc:
            label = self.password_errors["new_password"]
            label.value = str(
                exc.errors.get("password", exc.message)
            )
            label.visible = True

        try:
            validate_confirm_password(new, confirm)
        except AppError as exc:
            label = self.password_errors[
                "confirm_new_password"
            ]
            label.value = str(
                exc.errors.get("confirm_password", exc.message)
            )
            label.visible = True

        if any(
            label.visible
            for label in self.password_errors.values()
        ):
            self._refresh()
            return

        self._pending_password = {
            "old_password": old,
            "new_password": new,
            "confirm_new_password": confirm,
        }

        self._ask_confirmation(
            "Xác nhận đổi mật khẩu",
            "Đổi mật khẩu sẽ đăng xuất phiên hiện tại. "
            "Bạn đồng ý?",
            self.confirm_password_change,
            self.cancel_password_confirmation,
        )

    def cancel_password_confirmation(self) -> None:
        """Quay lại mà không cập nhật mật khẩu."""
        self._pending_password = None
        self._refresh()

    def confirm_password_change(self) -> None:
        """Chỉ gọi Backend sau khi người dùng xác nhận."""
        if (
            self._busy
            or self._pending_password is None
        ):
            return

        data = self._pending_password
        self._pending_password = None

        self._busy = True
        self.save_password_button.disabled = True
        self._refresh()

        succeeded = False
        auth_lost = False

        try:
            self._password_action(**data)

        except AppError as exc:
            self._feedback(
                self.password_feedback,
                exc.message,
                True,
            )

            aliases = {
                "password": "new_password",
                "confirm_password": "confirm_new_password",
            }

            for key, message in exc.errors.items():
                target = aliases.get(key, key)

                if target in self.password_errors:
                    label = self.password_errors[target]
                    label.value = str(message)
                    label.visible = True

            self._notify_user(exc.message, True)

            auth_lost = exc.error_code in {
                "UNAUTHORIZED",
                "ACCOUNT_LOCKED",
            }

        except Exception:
            logger.exception("Failed to change password")

            message = "Không thể đổi mật khẩu."
            self._feedback(
                self.password_feedback,
                message,
                True,
            )
            self._notify_user(message, True)

        else:
            succeeded = True
            self._notify_user(
                "Đổi mật khẩu thành công. Đăng nhập lại.",
                False,
            )

        finally:
            # Xóa mật khẩu, không xóa thông báo lỗi Backend.
            self._clear_password_values()

            self._busy = False
            self.save_password_button.disabled = False
            self._refresh()

        if succeeded:
            self._on_password_changed()
        elif auth_lost:
            self._on_auth_lost()

    # ======================================================
    # 5. ẢNH ĐẠI DIỆN
    # ======================================================
    def _preview(
        self,
        src: str | bytes | None,
    ) -> None:
        self.avatar_image.src = src or ""
        self.avatar_image.visible = src is not None
        self.avatar_placeholder.visible = src is None

    def on_files_picked(self, e) -> None:
        """Nhận file từ trình duyệt và xem trước."""
        if self._busy or self._avatar_confirmation_pending:
            return

        files = e.files or []

        if not files:
            self.cancel_avatar_selection()
            return

        self._selected_avatar = None
        self.save_avatar_button.disabled = True
        self.avatar_feedback.visible = False

        if len(files) != 1:
            self._feedback(
                self.avatar_feedback,
                "Chỉ chọn một ảnh.",
                True,
            )
            self._refresh()
            return

        selected = files[0]
        raw = selected.bytes

        try:
            if raw is None:
                raise AppError(
                    "INVALID_AVATAR",
                    "Không đọc được dữ liệu ảnh.",
                )

            if (
                selected.size > MAX_AVATAR_BYTES
                or len(raw) > MAX_AVATAR_BYTES
            ):
                raise AppError(
                    "AVATAR_TOO_LARGE",
                    "Ảnh vượt quá 2 MiB.",
                )

            # Kiểm tra nội dung thật bằng Pillow.
            cleaned, _extension = prepare_avatar(raw)

        except AppError as exc:
            self._feedback(
                self.avatar_feedback,
                exc.message,
                True,
            )
            self._preview(
                avatar_src(self._current_avatar)
            )
            self.cancel_avatar_button.disabled = True

        else:
            # Chỉ giữ ảnh tạm, chưa cập nhật database.
            self._selected_avatar = raw
            self._preview(cleaned)

            self.avatar_label.value = (
                f"Ảnh đã chọn: {selected.name} "
                f"({selected.size} byte)"
            )

            self.save_avatar_button.disabled = False
            self.cancel_avatar_button.disabled = False

        self._refresh()

    def cancel_avatar_selection(self, e=None) -> None:
        """Bỏ ảnh đã chọn, không thay ảnh đã lưu."""
        if self._busy or self._avatar_confirmation_pending:
            return

        self._selected_avatar = None
        self.avatar_feedback.visible = False
        self.avatar_label.value = "JPG/PNG, tối đa 2 MiB"

        self.save_avatar_button.disabled = True
        self.cancel_avatar_button.disabled = True

        self._preview(
            avatar_src(self._current_avatar)
        )
        self._refresh()

    def request_avatar_save(self, e=None) -> None:
        """Mở xác nhận; chưa gọi Service."""
        if (
            self._busy
            or self._avatar_confirmation_pending
            or self._selected_avatar is None
        ):
            return

        self._avatar_confirmation_pending = True

        self._ask_confirmation(
            "Xác nhận ảnh đại diện",
            "Bạn có chắc chắn muốn thay ảnh đại diện?",
            self.confirm_avatar_save,
            self.cancel_avatar_confirmation,
        )

    def cancel_avatar_confirmation(self) -> None:
        """Quay lại, không lưu ảnh."""
        self._avatar_confirmation_pending = False
        self._refresh()

    def confirm_avatar_save(self) -> None:
        """Gọi Backend sau khi hộp thoại đóng."""
        if (
            not self._avatar_confirmation_pending
            or self._busy
            or self._selected_avatar is None
        ):
            return

        data = self._selected_avatar
        self._avatar_confirmation_pending = False

        self._busy = True
        self.save_avatar_button.disabled = True
        self._refresh()

        succeeded = False
        auth_lost = False

        try:
            result = self._avatar_action(
                image_bytes=data,
            )

        except AppError as exc:
            self._feedback(
                self.avatar_feedback,
                exc.message,
                True,
            )
            self._notify_user(exc.message, True)

            auth_lost = exc.error_code in {
                "UNAUTHORIZED",
                "ACCOUNT_LOCKED",
            }

        except Exception:
            logger.exception("Failed to update avatar")

            message = "Không cập nhật được ảnh."
            self._feedback(
                self.avatar_feedback,
                message,
                True,
            )
            self._notify_user(message, True)

        else:
            succeeded = True
            self._current_avatar = result.avatar_url
            self._selected_avatar = None

            self._preview(
                avatar_src(result.avatar_url)
            )
            self.avatar_label.value = (
                "Ảnh đại diện đã được cập nhật."
            )

            self._notify_user(
                "Cập nhật ảnh đại diện thành công!",
                False,
            )

        finally:
            self._busy = False

            self.save_avatar_button.disabled = (
                self._selected_avatar is None
            )
            self.cancel_avatar_button.disabled = (
                self._selected_avatar is None
            )
            self._refresh()

        if succeeded:
            self._on_avatar_saved()
        elif auth_lost:
            self._on_auth_lost()
