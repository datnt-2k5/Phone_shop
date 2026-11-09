
"""Unit Test Task 21: không mở Web và không kết nối MariaDB."""

from io import BytesIO
from types import SimpleNamespace

import flet as ft
import pytest
from PIL import Image

from models.app_error import AppError
from services.account_security_service import (
    MAX_AVATAR_BYTES,
    AvatarResult,
)
from ui.pages.account_security_section import (
    AccountSecuritySection,
    avatar_src,
    open_security_confirmation,
)


def png_bytes() -> bytes:
    """Tạo PNG nhỏ để test, không dùng ảnh cá nhân."""
    output = BytesIO()
    Image.new(
        "RGB",
        (24, 24),
        (50, 100, 150),
    ).save(output, "PNG")
    return output.getvalue()


def make_panel(
    *,
    password_error=None,
    avatar_error=None,
    current_avatar=None,
):
    """Tạo giao diện và ghi lại các lần gọi Backend."""
    events = {
        "password": [],
        "avatar": [],
        "confirm": [],
        "changed": [],
        "uploaded": [],
        "lost": [],
        "notify": [],
    }

    def change_password(**values):
        events["password"].append(values)

        if password_error:
            raise password_error

    def upload_avatar(**values):
        events["avatar"].append(values)

        if avatar_error:
            raise avatar_error

        return AvatarResult(
            user_id=7,
            avatar_url="avatars/" + "a" * 32 + ".png",
        )

    # Quan trọng: dùng FilePicker thật, không dùng FakePicker.
    picker = ft.FilePicker()

    panel = AccountSecuritySection(
        password_action=change_password,
        avatar_action=upload_avatar,
        ask_confirmation=lambda title, message, yes, no: (
            events["confirm"].append(
                (title, message, yes, no)
            )
        ),
        notify_user=lambda message, error: (
            events["notify"].append((message, error))
        ),
        refresh=lambda: None,
        on_password_changed=lambda: (
            events["changed"].append(True)
        ),
        on_avatar_saved=lambda: (
            events["uploaded"].append(True)
        ),
        on_auth_lost=lambda: (
            events["lost"].append(True)
        ),
        file_picker=picker,
        initial_avatar_url=current_avatar,
    )

    return panel, events, picker


def enter_passwords(panel) -> None:
    panel.start_password_edit()
    panel.old_password.value = "MatKhau123!"
    panel.new_password.value = "MatKhauMoi456!"
    panel.confirm_password.value = "MatKhauMoi456!"


def select_image(
    panel,
    data,
    *,
    size=None,
) -> None:
    """Mô phỏng sự kiện chọn file từ trình duyệt."""
    file_size = (
        len(data)
        if size is None and data is not None
        else (size or 0)
    )

    selected = SimpleNamespace(
        bytes=data,
        name="avatar.png",
        size=file_size,
    )

    panel.on_files_picked(
        SimpleNamespace(files=[selected])
    )


def confirm(events):
    events["confirm"][-1][2]()


def decline(events):
    events["confirm"][-1][3]()


def test_initial_view_has_hidden_password_form_and_real_picker():
    panel, _, picker = make_panel()

    assert isinstance(picker, ft.FilePicker)
    assert picker.on_result == panel.on_files_picked
    assert panel.password_form.visible is False
    assert panel.save_avatar_button.disabled is True


def test_cancel_password_edit_clears_all_fields():
    panel, events, _ = make_panel()

    enter_passwords(panel)
    panel.cancel_password_edit()

    assert panel.password_form.visible is False
    assert all(
        not field.value
        for field in panel.password_fields.values()
    )
    assert events["password"] == []


def test_password_request_does_not_call_backend():
    panel, events, _ = make_panel()

    enter_passwords(panel)
    panel.request_password_change()

    assert len(events["confirm"]) == 1
    assert events["password"] == []


def test_password_confirmation_cancel_does_not_call_backend():
    panel, events, _ = make_panel()

    enter_passwords(panel)
    panel.request_password_change()
    decline(events)

    assert events["password"] == []
    assert panel.password_form.visible is True


def test_password_confirm_calls_backend_and_redirects():
    panel, events, _ = make_panel()

    enter_passwords(panel)
    panel.request_password_change()
    confirm(events)

    assert events["password"] == [
        {
            "old_password": "MatKhau123!",
            "new_password": "MatKhauMoi456!",
            "confirm_new_password": "MatKhauMoi456!",
        }
    ]

    assert events["changed"] == [True]
    assert all(
        not field.value
        for field in panel.password_fields.values()
    )


def test_password_double_confirm_does_not_submit_twice():
    panel, events, _ = make_panel()

    enter_passwords(panel)
    panel.request_password_change()

    confirm(events)
    confirm(events)

    assert len(events["password"]) == 1


@pytest.mark.parametrize(
    ("old", "new", "confirmation", "field"),
    [
        (
            "",
            "MatKhauMoi456!",
            "MatKhauMoi456!",
            "old_password",
        ),
        (
            "MatKhau123!",
            "abc123",
            "abc123",
            "new_password",
        ),
        (
            "MatKhau123!",
            "MatKhauMoi456!",
            "khac123456!",
            "confirm_new_password",
        ),
        (
            "MatKhau123!",
            "A1" + "é" * 36,
            "A1" + "é" * 36,
            "new_password",
        ),
    ],
)
def test_invalid_password_has_field_error(
    old,
    new,
    confirmation,
    field,
):
    panel, events, _ = make_panel()

    panel.start_password_edit()
    panel.old_password.value = old
    panel.new_password.value = new
    panel.confirm_password.value = confirmation
    panel.request_password_change()

    assert panel.password_errors[field].visible is True
    assert events["confirm"] == []


def test_wrong_old_password_is_reported():
    error = AppError(
        "INVALID_OLD_PASSWORD",
        "Sai mật khẩu cũ.",
        {"old_password": "Sai."},
    )

    panel, events, _ = make_panel(
        password_error=error
    )

    enter_passwords(panel)
    panel.request_password_change()
    confirm(events)

    assert panel.password_errors["old_password"].visible is True
    assert events["changed"] == []


def test_password_locked_session_redirects():
    panel, events, _ = make_panel(
        password_error=AppError(
            "ACCOUNT_LOCKED",
            "Tài khoản đã khóa.",
        )
    )

    enter_passwords(panel)
    panel.request_password_change()
    confirm(events)

    assert events["lost"] == [True]


def test_selected_png_preview_is_bytes_and_not_yet_uploaded():
    panel, events, _ = make_panel()

    select_image(panel, png_bytes())

    assert panel.avatar_image.visible is True
    assert isinstance(panel.avatar_image.src, bytes)
    assert panel.save_avatar_button.disabled is False
    assert events["avatar"] == []


def test_cancel_image_restores_saved_image():
    existing = "avatars/" + "b" * 32 + ".jpg"

    panel, _, _ = make_panel(
        current_avatar=existing
    )

    select_image(panel, png_bytes())
    panel.cancel_avatar_selection()

    assert panel.avatar_image.src == "/" + existing
    assert panel.save_avatar_button.disabled is True


def test_avatar_request_does_not_upload_before_confirmation():
    panel, events, _ = make_panel()

    select_image(panel, png_bytes())
    panel.request_avatar_save()

    assert len(events["confirm"]) == 1
    assert events["avatar"] == []


def test_cancel_avatar_confirmation_does_not_upload():
    panel, events, _ = make_panel()

    select_image(panel, png_bytes())
    panel.request_avatar_save()
    decline(events)

    assert events["avatar"] == []
    assert panel.save_avatar_button.disabled is False


def test_confirm_avatar_updates_preview_and_refresh():
    panel, events, _ = make_panel()

    payload = png_bytes()
    select_image(panel, payload)

    panel.request_avatar_save()
    confirm(events)

    assert events["avatar"] == [
        {"image_bytes": payload}
    ]
    assert events["uploaded"] == [True]

    assert panel.avatar_image.src == (
        "/avatars/" + "a" * 32 + ".png"
    )


def test_avatar_double_confirm_uploads_only_once():
    panel, events, _ = make_panel()

    select_image(panel, png_bytes())
    panel.request_avatar_save()

    confirm(events)
    confirm(events)

    assert len(events["avatar"]) == 1


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not-an-image",
        b"A" * (MAX_AVATAR_BYTES + 1),
    ],
)
def test_invalid_image_never_calls_backend(payload):
    panel, events, _ = make_panel()

    select_image(panel, payload)
    panel.request_avatar_save()

    assert panel.avatar_feedback.visible is True
    assert events["avatar"] == []
    assert events["confirm"] == []


def test_missing_file_bytes_is_rejected():
    panel, events, _ = make_panel()

    select_image(panel, None, size=100)

    assert panel.avatar_feedback.visible is True
    assert events["avatar"] == []


def test_avatar_backend_error_is_shown():
    panel, events, _ = make_panel(
        avatar_error=AppError(
            "INVALID_AVATAR",
            "Ảnh không hợp lệ.",
        )
    )

    select_image(panel, png_bytes())
    panel.request_avatar_save()
    confirm(events)

    assert panel.avatar_feedback.visible is True
    assert events["uploaded"] == []


def test_avatar_auth_lost_redirects():
    panel, events, _ = make_panel(
        avatar_error=AppError(
            "UNAUTHORIZED",
            "Phiên hết hạn.",
        )
    )

    select_image(panel, png_bytes())
    panel.request_avatar_save()
    confirm(events)

    assert events["lost"] == [True]


def test_avatar_path_allowlist():
    assert avatar_src("../private.png") is None
    assert avatar_src(
        "https://example.com/x.png"
    ) is None

    assert avatar_src(
        "avatars/" + "a" * 32 + ".png"
    ) == (
        "/avatars/" + "a" * 32 + ".png"
    )


class DialogPage:
    """Giả lập Page để kiểm tra thời điểm đóng dialog."""

    def __init__(self):
        self.dialog = None
        self.pop_count = 0

    def show_dialog(self, dialog):
        self.dialog = dialog

    def pop_dialog(self):
        self.pop_count += 1


@pytest.mark.parametrize(
    ("index", "expected"),
    [
        (0, "cancel"),
        (1, "confirm"),
    ],
)
def test_dialog_callbacks_run_only_after_on_dismiss(
    index,
    expected,
):
    page = DialogPage()
    events = []

    open_security_confirmation(
        page,
        "Tiêu đề",
        "Nội dung",
        lambda: events.append("confirm"),
        lambda: events.append("cancel"),
    )

    # Người dùng bấm nút trong hộp thoại.
    page.dialog.actions[index].on_click(None)

    # Chỉ yêu cầu đóng, chưa chạy nghiệp vụ.
    assert page.pop_count == 1
    assert events == []

    # Flet thông báo đã đóng xong.
    page.dialog.on_dismiss(None)

    # Nếu sự kiện phát thêm, không được xử lý hai lần.
    page.dialog.on_dismiss(None)

    assert events == [expected]
