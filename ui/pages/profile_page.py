
"""Trang hồ sơ cá nhân - US03 Task 18.

Luồng: Xem -> Chỉnh sửa -> Xác nhận -> Lưu.
UI không được tự sửa email, role, status hoặc user_id.
"""

import logging
from collections.abc import Callable
from datetime import datetime

import flet as ft

from models.app_error import AppError
from services.account_security_service import AccountSecurityService
from services.profile_service import ProfileResult, ProfileService
from ui.components.notifications import notify
from ui.pages.account_security_section import (
    AccountSecuritySection,
    open_security_confirmation,
)
from utils.time_utils import utc_to_vn
from utils.validators import (
    validate_address,
    validate_full_name,
    validate_phone,
)

logger = logging.getLogger(__name__)



def open_profile_confirmation(
    page: ft.Page,
    *,
    on_confirm: Callable[[], None],
    on_cancel: Callable[[], None],
    title: str = "Xác nhận cập nhật hồ sơ",
    message: str = (
        "Bạn có chắc chắn muốn lưu những thay đổi "
        "trong thông tin cá nhân không?"
    ),
) -> None:

    """Mở hộp thoại và chỉ xử lý sau khi đã đóng hoàn toàn.

    Tránh dựng lại page.views trong lúc dialog vẫn đang đóng.
    """

    state = {
        "choice": None,
        "handled": False,
    }

    def close_with_choice(choice: str) -> None:
        """Ghi nhận lựa chọn và yêu cầu Flet đóng dialog."""

        # Ngăn thao tác lặp khi người dùng nhấn nút nhiều lần.
        if state["choice"] is not None:
            return

        state["choice"] = choice

        # Chỉ đóng hộp thoại; chưa cập nhật database.
        page.pop_dialog()

    def confirm_click(e) -> None:
        close_with_choice("confirm")

    def cancel_click(e) -> None:
        close_with_choice("cancel")

    def handle_dismiss(e) -> None:
        """Chạy khi Flet đã kết thúc việc đóng dialog."""

        if state["handled"]:
            return

        state["handled"] = True

        if state["choice"] == "confirm":
            # Bây giờ mới gọi ProfileService để lưu.
            on_confirm()
        else:
            # Quay lại hoặc dialog bị đóng không xác nhận.
            on_cancel()

    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Text(message),
        actions=[
            ft.TextButton(
                "Quay lại",
                on_click=cancel_click,
            ),
            ft.Button(
                "Xác nhận cập nhật",
                on_click=confirm_click,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=handle_dismiss,
    )

    page.show_dialog(dialog)


def _display_time(value: datetime | None) -> str:
    """Hiển thị thời gian UTC theo giờ Việt Nam."""
    if value is None:
        return "Chưa có"

    return utc_to_vn(value).strftime("%d/%m/%Y %H:%M") + " (VN)"


class ProfileForm:
    """Quản lý chế độ xem, chỉnh sửa và xác nhận cập nhật."""

    def __init__(
        self,
        *,
        load_action: Callable[[], ProfileResult],
        save_action: Callable[..., ProfileResult],
        ask_confirmation: Callable[
            [Callable[[], None], Callable[[], None]],
            None,
        ],
        notify_user: Callable[[str, bool], None],
        refresh: Callable[[], None],
        on_saved: Callable[[], None],
        on_auth_lost: Callable[[], None],
    ) -> None:
        self._load_action = load_action
        self._save_action = save_action
        self._ask_confirmation = ask_confirmation
        self._notify_user = notify_user
        self._refresh = refresh
        self._on_saved = on_saved
        self._on_auth_lost = on_auth_lost

        self._profile: ProfileResult | None = None
        self._editing = False
        self._busy = False
        self._pending_values: dict[str, str | None] | None = None

        # ====================================================
        # 1. THÔNG TIN HIỂN THỊ (CHỈ XEM)
        # ====================================================
        self.view_name = ft.Text(
            size=23,
            weight=ft.FontWeight.BOLD,
        )
        self.view_email = ft.Text(
            color=ft.Colors.GREY_700,
        )
        self.view_phone = ft.Text()
        self.view_address = ft.Text()

        self.view_id = ft.Text()
        self.view_role = ft.Text()
        self.view_status = ft.Text()
        self.view_created_at = ft.Text()
        self.view_updated_at = ft.Text()

        def info_item(label: str, value: ft.Text) -> ft.Column:
            """Tạo một dòng thông tin hiển thị đẹp, dễ đọc."""
            return ft.Column(
                controls=[
                    ft.Text(
                        label,
                        size=12,
                        color=ft.Colors.GREY_600,
                    ),
                    value,
                ],
                spacing=4,
            )

        self.view_section = ft.Column(
            controls=[
                ft.Text(
                    "THÔNG TIN CÁ NHÂN",
                    weight=ft.FontWeight.BOLD,
                ),
                info_item("Họ và tên", self.view_name),
                ft.Divider(),
                info_item("Số điện thoại", self.view_phone),
                ft.Divider(),
                info_item("Địa chỉ", self.view_address),
            ],
            spacing=10,
            visible=True,
        )

        # ====================================================
        # 2. FORM CHỈNH SỬA - CHỈ CÓ 3 TRƯỜNG
        # ====================================================
        self.full_name = ft.TextField(
            label="Họ và tên *",
        )
        self.phone = ft.TextField(
            label="Số điện thoại *",
            keyboard_type=ft.KeyboardType.PHONE,
        )
        self.address = ft.TextField(
            label="Địa chỉ",
            multiline=True,
            min_lines=2,
            max_lines=4,
            hint_text="Có thể để trống",
        )

        self.editable_fields = {
            "full_name": self.full_name,
            "phone": self.phone,
            "address": self.address,
        }

        self.error_labels = {
            name: ft.Text(
                value="",
                size=12,
                visible=False,
                color=ft.Colors.RED_700,
            )
            for name in self.editable_fields
        }

        for name, field in self.editable_fields.items():
            field.on_change = (
                lambda e, key=name: self.clear_error(key)
            )

        self.save_button = ft.Button(
            "Lưu thay đổi",
            on_click=self.request_save,
        )
        self.cancel_button = ft.Button(
            "Hủy",
            on_click=self.cancel_edit,
        )

        edit_controls: list[ft.Control] = [
            ft.Text(
                "CHỈNH SỬA THÔNG TIN",
                weight=ft.FontWeight.BOLD,
            )
        ]

        for name, field in self.editable_fields.items():
            edit_controls.extend([
                field,
                self.error_labels[name],
            ])

        edit_controls.append(
            ft.Row(
                controls=[
                    self.save_button,
                    self.cancel_button,
                ],
                spacing=10,
                wrap=True,
            )
        )

        self.edit_section = ft.Column(
            controls=edit_controls,
            spacing=10,
            visible=False,
        )

        # ====================================================
        # 3. NÚT CHỈNH SỬA VÀ THÔNG TIN BẢO VỆ
        # ====================================================
        self.edit_button = ft.Button(
            "Chỉnh sửa thông tin",
            on_click=self.start_edit,
            disabled=True,
        )
        self.reload_button = ft.Button(
            "Làm mới",
            on_click=self.load,
        )

        self.view_actions = ft.Row(
            controls=[
                self.edit_button,
                self.reload_button,
            ],
            wrap=True,
            spacing=10,
            visible=True,
        )

        self.feedback = ft.Text(
            value="",
            visible=False,
        )

        self.account_section = ft.Column(
            controls=[
                ft.Text(
                    "THÔNG TIN TÀI KHOẢN (CHỈ ĐỌC)",
                    weight=ft.FontWeight.BOLD,
                ),
                info_item("ID tài khoản", self.view_id),
                info_item("Email", self.view_email),
                info_item("Vai trò", self.view_role),
                info_item("Trạng thái", self.view_status),
                info_item("Ngày tạo", self.view_created_at),
                info_item("Cập nhật gần nhất", self.view_updated_at),
                ft.Text(
                    "Email, ID, vai trò và trạng thái "
                    "không thể chỉnh sửa tại đây.",
                    size=12,
                    color=ft.Colors.GREY_700,
                ),
            ],
            spacing=12,
        )

        # ====================================================
        # 4. BỐ CỤC TOÀN TRANG
        # ====================================================
        self.content = ft.Column(
            controls=[
                ft.Text(
                    "HỒ SƠ CÁ NHÂN",
                    size=25,
                    weight=ft.FontWeight.BOLD,
                ),
                ft.Text(
                    "Xem và quản lý thông tin của bạn.",
                    color=ft.Colors.GREY_700,
                ),
                ft.Container(
                    content=self.view_section,
                    padding=16,
                    border_radius=12,
                    bgcolor=ft.Colors.BLUE_50,
                ),
                self.edit_section,
                self.view_actions,
                self.feedback,
                ft.Divider(),
                self.account_section,
            ],
            spacing=16,
        )

    def _set_mode(self, editing: bool) -> None:
        """Chuyển giữa chế độ xem và chỉnh sửa."""
        self._editing = editing
        self.view_section.visible = not editing
        self.view_actions.visible = not editing
        self.edit_section.visible = editing

    def _clear_errors(self) -> None:
        for label in self.error_labels.values():
            label.value = ""
            label.visible = False

    def clear_error(self, field_name: str) -> None:
        """Xóa lỗi của ô đang chỉnh sửa."""
        label = self.error_labels[field_name]
        label.value = ""
        label.visible = False

        if self.feedback.color == ft.Colors.RED_700:
            self.feedback.visible = False

        self._refresh()

    def _show_feedback(
        self,
        message: str,
        *,
        error: bool,
    ) -> None:
        self.feedback.value = message
        self.feedback.visible = True
        self.feedback.color = (
            ft.Colors.RED_700
            if error
            else ft.Colors.GREEN_700
        )

    def _apply_profile(self, profile: ProfileResult) -> None:
        """Hiển thị dữ liệu mới nhất do Service trả về."""
        self._profile = profile

        # Chế độ xem.
        self.view_name.value = profile.full_name
        self.view_phone.value = profile.phone
        self.view_address.value = (
            profile.address or "Chưa cập nhật"
        )

        # Thông tin không được sửa.
        self.view_id.value = str(profile.user_id)
        self.view_email.value = profile.email
        self.view_role.value = profile.role
        self.view_status.value = profile.status
        self.view_created_at.value = _display_time(
            profile.created_at
        )
        self.view_updated_at.value = _display_time(
            profile.updated_at
        )

        # Chuẩn bị dữ liệu cho lần chỉnh sửa kế tiếp.
        self.full_name.value = profile.full_name
        self.phone.value = profile.phone
        self.address.value = profile.address or ""

        self.edit_button.disabled = False
        self._pending_values = None
        self._set_mode(False)

    def _clear_profile(self) -> None:
        """Không giữ dữ liệu cũ khi hồ sơ không còn hợp lệ."""
        self._profile = None
        self._pending_values = None

        for value in (
            self.view_name,
            self.view_phone,
            self.view_address,
            self.view_id,
            self.view_email,
            self.view_role,
            self.view_status,
            self.view_created_at,
            self.view_updated_at,
        ):
            value.value = ""

        self.full_name.value = ""
        self.phone.value = ""
        self.address.value = ""
        self.edit_button.disabled = True
        self._set_mode(False)

    def load(self, e=None, *, refresh: bool = True) -> None:
        """Tải lại hồ sơ từ MariaDB thông qua Service."""
        if self._busy:
            return

        self._clear_errors()
        self.feedback.visible = False
        auth_lost = False

        try:
            profile = self._load_action()

        except AppError as exc:
            self._clear_profile()
            self._show_feedback(exc.message, error=True)
            auth_lost = exc.error_code in {
                "UNAUTHORIZED",
                "ACCOUNT_LOCKED",
            }

        except Exception:
            logger.exception("Unexpected error loading profile")
            self._clear_profile()
            self._show_feedback(
                "Không tải được hồ sơ. Vui lòng thử lại.",
                error=True,
            )

        else:
            self._apply_profile(profile)

        if refresh:
            self._refresh()

        if auth_lost:
            self._on_auth_lost()

    def start_edit(self, e=None) -> None:
        """Mở form chỉnh sửa khi người dùng bấm nút."""
        if self._busy or self._profile is None:
            return

        # Luôn bắt đầu từ dữ liệu hồ sơ đã tải.
        self.full_name.value = self._profile.full_name
        self.phone.value = self._profile.phone
        self.address.value = self._profile.address or ""

        self._pending_values = None
        self._clear_errors()
        self.feedback.visible = False
        self._set_mode(True)
        self._refresh()

    def cancel_edit(self, e=None) -> None:
        """Hủy chỉnh sửa và bỏ những giá trị chưa lưu."""
        if self._busy:
            return

        self._pending_values = None
        self._clear_errors()
        self.feedback.visible = False

        if self._profile is not None:
            self.full_name.value = self._profile.full_name
            self.phone.value = self._profile.phone
            self.address.value = self._profile.address or ""

        self._set_mode(False)
        self._refresh()

    def _validated_values(
        self,
    ) -> dict[str, str | None] | None:
        """Kiểm tra đúng ba trường được phép cập nhật."""
        checks = {
            "full_name": (
                validate_full_name,
                self.full_name.value or "",
            ),
            "phone": (
                validate_phone,
                self.phone.value or "",
            ),
            "address": (
                validate_address,
                self.address.value or "",
            ),
        }

        values: dict[str, str | None] = {}
        valid = True

        for name, (validator, raw) in checks.items():
            try:
                values[name] = validator(raw)
            except AppError as exc:
                for field, message in exc.errors.items():
                    if field in self.error_labels:
                        self.error_labels[field].value = str(message)
                        self.error_labels[field].visible = True
                valid = False

        return values if valid else None

    def request_save(self, e=None) -> None:
        """Validate rồi yêu cầu xác nhận, chưa ghi database."""
        if (
            not self._editing
            or self._busy
            or self._profile is None
            or self._pending_values is not None
        ):
            return

        self._clear_errors()
        self.feedback.visible = False

        values = self._validated_values()

        if values is None:
            self._show_feedback(
                "Vui lòng sửa các thông tin không hợp lệ.",
                error=True,
            )
            self._refresh()
            return

        # Chụp giá trị tại thời điểm yêu cầu xác nhận.
        self._pending_values = values

        # Chỉ mở hộp thoại, chưa gọi ProfileService.
        self._ask_confirmation(
            self.confirm_save,
            self.cancel_confirmation,
        )

    def cancel_confirmation(self) -> None:
        """Quay lại form khi chưa đồng ý cập nhật."""
        self._pending_values = None
        self._refresh()

    def confirm_save(self) -> None:
        """Chỉ ghi database sau khi người dùng xác nhận."""
        if (
            not self._editing
            or self._busy
            or self._pending_values is None
        ):
            return

        values = dict(self._pending_values)
        self._pending_values = None

        self._busy = True
        self.save_button.disabled = True
        self.cancel_button.disabled = True
        self._refresh()

        saved = False
        auth_lost = False

        try:
            # Backend chỉ nhận ba trường, không nhận role/ID.
            updated = self._save_action(**values)

        except AppError as exc:
            for field, message in exc.errors.items():
                if field in self.error_labels:
                    self.error_labels[field].value = str(message)
                    self.error_labels[field].visible = True

            self._show_feedback(exc.message, error=True)
            self._notify_user(exc.message, True)

            auth_lost = exc.error_code in {
                "UNAUTHORIZED",
                "ACCOUNT_LOCKED",
            }

            if auth_lost:
                self._clear_profile()

        except Exception:
            logger.exception("Unexpected error updating profile")
            message = (
                "Không thể cập nhật hồ sơ. Vui lòng thử lại."
            )
            self._show_feedback(message, error=True)
            self._notify_user(message, True)

        else:
            self._apply_profile(updated)
            self._show_feedback(
                "Cập nhật thông tin cá nhân thành công!",
                error=False,
            )
            self._notify_user(
                "Cập nhật thông tin cá nhân thành công!",
                False,
            )
            saved = True

        finally:
            self._busy = False
            self.save_button.disabled = False
            self.cancel_button.disabled = False
            self._refresh()

        if auth_lost:
            self._on_auth_lost()
        elif saved:
            # Header sẽ được dựng lại với tên mới từ DB.
            self._on_saved()




def build_profile_page(
    page: ft.Page,
    *,
    on_saved: Callable[[], None],
    file_picker: ft.FilePicker,
) -> ft.Column:
    """Trang hồ sơ P1 kết hợp chức năng bảo mật P2."""

    profile_service = ProfileService()
    security_service = AccountSecurityService()

    # 1. Xác nhận chỉnh sửa hồ sơ P1.
    def confirm_profile(
        on_confirm: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        open_profile_confirmation(
            page,
            on_confirm=on_confirm,
            on_cancel=on_cancel,
        )

    # 2. Giữ nguyên ProfileForm Task 18.
    form = ProfileForm(
        load_action=lambda: profile_service.get_my_profile(
            session_store=page.session.store,
        ),
        save_action=lambda **values: (
            profile_service.update_my_profile(
                session_store=page.session.store,
                **values,
            )
        ),
        ask_confirmation=confirm_profile,
        notify_user=lambda message, error: notify(
            page,
            message,
            error=error,
        ),
        refresh=page.update,
        on_saved=on_saved,
        on_auth_lost=lambda: page.navigate("/login"),
    )

    form.load(refresh=False)

    # Avatar đã lưu trong MariaDB, nếu có.
    initial_avatar_url = (
        form._profile.avatar_url
        if form._profile is not None
        else None
    )

    # 3. Giao diện P2 sử dụng Service Task 20.
    security_section = AccountSecuritySection(
        password_action=lambda **values: (
            security_service.change_password(
                session_store=page.session.store,
                **values,
            )
        ),
        avatar_action=lambda **values: (
            security_service.upload_avatar(
                session_store=page.session.store,
                **values,
            )
        ),
        ask_confirmation=lambda title, message, yes, no: (
            open_security_confirmation(
                page,
                title,
                message,
                yes,
                no,
            )
        ),
        notify_user=lambda message, error: notify(
            page,
            message,
            error=error,
        ),
        refresh=page.update,
        on_password_changed=lambda: page.navigate("/login"),
        on_avatar_saved=on_saved,
        on_auth_lost=lambda: page.navigate("/login"),
        file_picker=file_picker,
        initial_avatar_url=initial_avatar_url,
    )

    # 4. Bố cục: hồ sơ cũ phía trên, bảo mật phía dưới.
    return ft.Column(
        controls=[
            ft.Container(
                content=form.content,
                width=580,
                padding=22,
                border_radius=16,
                bgcolor=ft.Colors.WHITE,
            ),
            ft.Container(
                content=security_section.content,
                width=580,
                padding=22,
                border_radius=16,
                bgcolor=ft.Colors.WHITE,
            ),
            ft.Button(
                "Về trang chủ",
                on_click=lambda e: page.navigate("/"),
            ),
        ],
        spacing=16,
    )
