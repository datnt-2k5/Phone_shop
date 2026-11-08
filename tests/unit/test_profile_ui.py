
"""Unit Test Task 18: xem, chỉnh sửa và xác nhận cập nhật.

Không sử dụng MariaDB thật.
"""

from dataclasses import replace
from datetime import datetime

import pytest

from models.app_error import AppError
from services.profile_service import ProfileResult
from ui.pages.profile_page import (
    ProfileForm,
    open_profile_confirmation,
)


def _profile() -> ProfileResult:
    return ProfileResult(
        user_id=42,
        email="customer@example.test",
        full_name="Nguyễn Văn A",
        phone="0912345678",
        address="Đà Nẵng",
        role="CUSTOMER",
        status="ACTIVE",
        created_at=datetime(2026, 11, 8, 5, 0),
        updated_at=datetime(2026, 11, 8, 6, 30),
        updated_by=None,
    )


def _make_form(*, load_action=None, save_action=None):
    events = {
        "saves": [],
        "confirmations": [],
        "notifications": [],
        "saved": [],
        "lost": [],
    }

    if load_action is None:
        load_action = _profile

    if save_action is None:
        def save_action(**values):
            events["saves"].append(values)

            return replace(
                _profile(),
                **values,
                updated_by=42,
            )

    form = ProfileForm(
        load_action=load_action,
        save_action=save_action,
        ask_confirmation=lambda yes, no: (
            events["confirmations"].append((yes, no))
        ),
        notify_user=lambda message, error: (
            events["notifications"].append((message, error))
        ),
        refresh=lambda: None,
        on_saved=lambda: events["saved"].append(True),
        on_auth_lost=lambda: events["lost"].append(True),
    )

    return form, events


def _loaded_form():
    form, events = _make_form()
    form.load()
    return form, events


def _confirm(events):
    """Giả lập nhấn nút Xác nhận cập nhật."""
    yes, _ = events["confirmations"][-1]
    yes()


def _decline(events):
    """Giả lập nhấn nút Quay lại trong hộp thoại."""
    _, no = events["confirmations"][-1]
    no()


def test_initial_profile_is_view_only():
    """Mở trang chỉ hiển thị thông tin, chưa cho sửa."""
    form, _ = _loaded_form()

    assert form.view_section.visible is True
    assert form.edit_section.visible is False
    assert form.view_actions.visible is True

    assert form.view_name.value == "Nguyễn Văn A"
    assert form.view_phone.value == "0912345678"
    assert form.view_address.value == "Đà Nẵng"

    assert form.view_email.value == "customer@example.test"
    assert form.view_role.value == "CUSTOMER"
    assert form.view_status.value == "ACTIVE"
    assert form.view_id.value == "42"

    assert form.view_created_at.value == (
        "08/11/2026 12:00 (VN)"
    )


def test_edit_mode_only_appears_after_click():
    """Bấm Chỉnh sửa mới hiển thị ba ô nhập."""
    form, _ = _loaded_form()

    form.start_edit()

    assert form.view_section.visible is False
    assert form.edit_section.visible is True
    assert form.view_actions.visible is False

    assert form.full_name.value == "Nguyễn Văn A"
    assert form.phone.value == "0912345678"
    assert form.address.value == "Đà Nẵng"
    assert set(form.editable_fields) == {
        "full_name",
        "phone",
        "address",
    }


def test_cancel_edit_discards_unsaved_values():
    """Nút Hủy phải bỏ những thông tin chưa lưu."""
    form, events = _loaded_form()
    form.start_edit()

    form.full_name.value = "Tên chưa lưu"
    form.phone.value = "0901234567"

    form.cancel_edit()

    assert form.view_section.visible is True
    assert form.edit_section.visible is False
    assert form.full_name.value == "Nguyễn Văn A"
    assert form.phone.value == "0912345678"
    assert events["saves"] == []
    assert events["confirmations"] == []


def test_save_button_only_opens_confirmation():
    """Bấm Lưu chưa được ghi xuống database."""
    form, events = _loaded_form()
    form.start_edit()

    form.full_name.value = "Nguyễn Văn B"
    form.request_save()

    assert len(events["confirmations"]) == 1
    assert events["saves"] == []
    assert form.edit_section.visible is True


def test_declining_confirmation_does_not_save():
    """Chọn Quay lại: vẫn giữ form nhưng không lưu."""
    form, events = _loaded_form()
    form.start_edit()

    form.full_name.value = "Nguyễn Văn B"
    form.request_save()

    _decline(events)

    assert events["saves"] == []
    assert events["saved"] == []
    assert form.edit_section.visible is True
    assert form.full_name.value == "Nguyễn Văn B"


def test_confirmed_update_saves_normalized_values():
    """Chỉ sau xác nhận mới gọi Service và cập nhật UI."""
    form, events = _loaded_form()
    form.start_edit()

    form.full_name.value = "  Nguyễn    Văn   Mới "
    form.phone.value = " 0901234567 "
    form.address.value = "  Hồ Chí Minh  "

    form.request_save()

    assert events["saves"] == []

    _confirm(events)

    assert events["saves"] == [
        {
            "full_name": "Nguyễn Văn Mới",
            "phone": "0901234567",
            "address": "Hồ Chí Minh",
        }
    ]
    assert events["saved"] == [True]

    assert form.view_name.value == "Nguyễn Văn Mới"
    assert form.view_phone.value == "0901234567"
    assert form.view_address.value == "Hồ Chí Minh"
    assert form.view_section.visible is True
    assert form.edit_section.visible is False
    assert form.feedback.visible is True


def test_role_email_status_and_id_not_in_save_payload():
    """Không thể tự cấp role hoặc sửa email/ID bằng form."""
    form, events = _loaded_form()
    form.start_edit()

    # Giả lập sửa giá trị hiển thị bằng Python.
    form.view_role.value = "SUPER_ADMIN"
    form.view_email.value = "attacker@example.test"
    form.view_id.value = "999999"
    form.view_status.value = "LOCKED"

    form.request_save()
    _confirm(events)

    assert len(events["saves"]) == 1
    assert set(events["saves"][0]) == {
        "full_name",
        "phone",
        "address",
    }

    # Kết quả Service ghi đè các giá trị giả mạo.
    assert form.view_role.value == "CUSTOMER"
    assert form.view_email.value == "customer@example.test"
    assert form.view_id.value == "42"
    assert form.view_status.value == "ACTIVE"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("full_name", "   "),
        ("phone", "12345"),
        ("address", "A" * 256),
    ],
)
def test_invalid_data_does_not_open_confirmation(
    field,
    value,
):
    """Dữ liệu sai bị chặn trước cả hộp thoại xác nhận."""
    form, events = _loaded_form()
    form.start_edit()

    getattr(form, field).value = value
    form.request_save()

    assert events["confirmations"] == []
    assert events["saves"] == []
    assert form.error_labels[field].visible is True


def test_backend_validation_error_is_visible():
    """Lỗi Service phải được hiển thị rõ ràng."""
    def reject(**values):
        raise AppError(
            "VALIDATION_ERROR",
            "Dữ liệu không hợp lệ.",
            {"phone": "Số điện thoại không hợp lệ."},
        )

    form, events = _make_form(save_action=reject)
    form.load()
    form.start_edit()

    form.request_save()
    _confirm(events)

    assert form.error_labels["phone"].visible is True
    assert form.edit_section.visible is True
    assert events["saved"] == []


def test_unexpected_error_does_not_leak_database_info():
    """Lỗi nội bộ không được hiển thị cho người dùng."""
    def fail(**values):
        raise RuntimeError("SECRET_DATABASE_PASSWORD")

    form, events = _make_form(save_action=fail)
    form.load()
    form.start_edit()

    form.request_save()
    _confirm(events)

    assert "SECRET_DATABASE_PASSWORD" not in (
        form.feedback.value
    )
    assert events["saved"] == []
    assert form.edit_section.visible is True


def test_session_lost_during_save_redirects():
    """Phiên bị khóa khi cập nhật thì không thể tiếp tục."""
    def locked(**values):
        raise AppError(
            "ACCOUNT_LOCKED",
            "Tài khoản đã bị khóa.",
        )

    form, events = _make_form(save_action=locked)
    form.load()
    form.start_edit()

    form.request_save()
    _confirm(events)

    assert events["lost"] == [True]
    assert events["saved"] == []
    assert form.edit_button.disabled is True


def test_expired_session_on_load_clears_profile():
    """Không hiển thị thông tin cũ nếu session hết hạn."""
    def unauthorized():
        raise AppError(
            "UNAUTHORIZED",
            "Vui lòng đăng nhập.",
        )

    form, events = _make_form(load_action=unauthorized)
    form.load()

    assert events["lost"] == [True]
    assert form.edit_button.disabled is True
    assert form.view_name.value == ""


def test_unexpected_load_error_uses_generic_message():
    """Lỗi khi tải không được tiết lộ thông tin nội bộ."""
    def fail():
        raise RuntimeError("DATABASE_PASSWORD")

    form, _ = _make_form(load_action=fail)
    form.load()

    assert form.edit_button.disabled is True
    assert "DATABASE_PASSWORD" not in form.feedback.value


def test_second_save_request_waits_for_confirmation():
    """Không mở nhiều hộp thoại khi chưa xử lý hộp thoại đầu."""
    form, events = _loaded_form()
    form.start_edit()

    form.request_save()
    form.request_save()

    assert len(events["confirmations"]) == 1
    assert events["saves"] == []


def test_confirming_twice_only_saves_once():
    """Không thực hiện cập nhật hai lần cho cùng một xác nhận."""
    form, events = _loaded_form()
    form.start_edit()

    form.request_save()
    yes, _ = events["confirmations"][-1]

    yes()
    yes()

    assert len(events["saves"]) == 1
    assert events["saved"] == [True]


def test_cannot_save_when_not_editing():
    """Ở chế độ xem, lệnh lưu không làm gì."""
    form, events = _loaded_form()

    form.request_save()

    assert events["confirmations"] == []
    assert events["saves"] == []


def test_editing_a_field_clears_its_error():
    """Sửa một ô sẽ xóa lỗi validation của ô đó."""
    form, _ = _loaded_form()
    form.start_edit()

    form.phone.value = "123"
    form.request_save()

    assert form.error_labels["phone"].visible is True

    form.phone.value = "0912345678"
    form.clear_error("phone")

    assert form.error_labels["phone"].visible is False



class FakeDialogPage:
    """Giả lập những phương thức dialog cần kiểm tra."""

    def __init__(self):
        self.dialog = None
        self.pop_count = 0

    def show_dialog(self, dialog):
        self.dialog = dialog
        dialog.open = True

    def pop_dialog(self):
        self.pop_count += 1
        self.dialog.open = False
        return self.dialog


@pytest.mark.parametrize(
    ("button_index", "expected"),
    [
        (0, "cancel"),
        (1, "confirm"),
    ],
)
def test_confirmation_callback_runs_after_dialog_dismiss(
    button_index,
    expected,
):
    """Nút bấm chỉ đóng dialog; callback chạy sau on_dismiss."""

    page = FakeDialogPage()
    events = []

    open_profile_confirmation(
        page,
        on_confirm=lambda: events.append("confirm"),
        on_cancel=lambda: events.append("cancel"),
    )

    assert page.dialog.open is True

    # Người dùng nhấn Quay lại hoặc Xác nhận cập nhật.
    page.dialog.actions[button_index].on_click(None)

    # Đã yêu cầu đóng nhưng chưa được phép xử lý nghiệp vụ.
    assert page.pop_count == 1
    assert page.dialog.open is False
    assert events == []

    # Mô phỏng Flet báo hiệu dialog đóng xong.
    page.dialog.on_dismiss(None)

    assert events == [expected]

    # Callback không được chạy hai lần.
    page.dialog.on_dismiss(None)
    assert events == [expected]


def test_confirmation_double_click_only_closes_once():
    """Bấm Xác nhận liên tiếp không được xử lý hai lần."""

    page = FakeDialogPage()
    events = []

    open_profile_confirmation(
        page,
        on_confirm=lambda: events.append("confirm"),
        on_cancel=lambda: events.append("cancel"),
    )

    confirm_button = page.dialog.actions[1]

    confirm_button.on_click(None)
    confirm_button.on_click(None)

    assert page.pop_count == 1
    assert events == []

    page.dialog.on_dismiss(None)

    assert events == ["confirm"]
