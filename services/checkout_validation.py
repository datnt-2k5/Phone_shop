
"""Task 50 / US09-T03: validate a customer checkout request.

Pure validation and input normalization only.

This module:
- Does not authenticate a customer.
- Does not query product prices, stock or status.
- Does not use MariaDB or Flet Session.
- Does not calculate a request hash.
- Does not create orders or change inventory.

Checkout Service must authenticate the Customer before calling
this validator and must check idempotency before querying
current product data.
"""

import re
from typing import Any
from uuid import UUID

from models.app_error import AppError

MAX_CART_LINES = 20
MAX_PRODUCT_ID = 9_223_372_036_854_775_807
MAX_QUANTITY = 2_147_483_647
MAX_NOTE_BYTES = 65_535

PHONE_PATTERN = re.compile(r"0[0-9]{9}")

REQUIRED_FIELDS = frozenset(
    {
        "receiver_name",
        "receiver_phone",
        "receiver_address",
        "items",
        "idempotency_key",
    }
)

ALLOWED_FIELDS = REQUIRED_FIELDS | {"note"}

ITEM_FIELDS = frozenset(
    {
        "product_id",
        "quantity",
    }
)


def _invalid(field: str, detail: str) -> None:
    """Produce a safe, field-specific business validation error."""
    raise AppError(
        "VALIDATION_ERROR",
        "Thông tin đặt hàng không hợp lệ.",
        {field: detail},
    )


def _required_text(
    value: object,
    *,
    field: str,
    label: str,
    max_length: int,
) -> str:
    """Trim and collapse whitespace in required human-readable text."""
    if type(value) is not str:
        _invalid(
            field,
            f"{label} phải là chuỗi ký tự.",
        )

    normalized = " ".join(value.split())

    if not normalized:
        _invalid(
            field,
            f"{label} không được để trống.",
        )

    if len(normalized) > max_length:
        _invalid(
            field,
            f"{label} không được vượt quá "
            f"{max_length} ký tự.",
        )

    return normalized


def validate_receiver_name(value: object) -> str:
    """Validate recipient name using the orders VARCHAR(100) limit."""
    return _required_text(
        value,
        field="receiver_name",
        label="Tên người nhận",
        max_length=100,
    )


def validate_receiver_phone(value: object) -> str:
    """Validate a Vietnamese-style ten-digit ASCII phone number."""
    if type(value) is not str:
        _invalid(
            "receiver_phone",
            "Số điện thoại phải là chuỗi ký tự.",
        )

    phone = value.strip()

    if PHONE_PATTERN.fullmatch(phone) is None:
        _invalid(
            "receiver_phone",
            "Số điện thoại phải gồm 10 chữ số ASCII "
            "và bắt đầu bằng số 0.",
        )

    return phone


def validate_receiver_address(value: object) -> str:
    """Validate delivery address using orders VARCHAR(255)."""
    return _required_text(
        value,
        field="receiver_address",
        label="Địa chỉ nhận hàng",
        max_length=255,
    )


def validate_checkout_note(value: object) -> str:
    """Normalize optional note; enforce MariaDB TEXT byte capacity."""
    if value is None:
        return ""

    if type(value) is not str:
        _invalid(
            "note",
            "Ghi chú phải là chuỗi ký tự hoặc để trống.",
        )

    note = value.strip()

    try:
        encoded = note.encode("utf-8")
    except UnicodeEncodeError:
        _invalid(
            "note",
            "Ghi chú chứa ký tự không hợp lệ.",
        )

    if len(encoded) > MAX_NOTE_BYTES:
        _invalid(
            "note",
            "Ghi chú vượt quá giới hạn lưu trữ.",
        )

    return note


def validate_checkout_items(
    value: object,
) -> list[dict[str, int]]:
    """Validate cart items without querying product data.

    Keep original item order. Sorting belongs to the
    canonical-payload task (US09-T04).
    """
    if type(value) is not list:
        _invalid(
            "items",
            "Danh sách sản phẩm phải là một danh sách.",
        )

    if not 1 <= len(value) <= MAX_CART_LINES:
        _invalid(
            "items",
            "Giỏ hàng phải có từ 1 đến 20 dòng sản phẩm.",
        )

    result: list[dict[str, int]] = []
    seen: set[int] = set()

    for index, item in enumerate(value):
        prefix = f"items[{index}]"

        if type(item) is not dict or set(item) != ITEM_FIELDS:
            _invalid(
                prefix,
                "Mỗi dòng chỉ được chứa product_id và quantity.",
            )

        product_id = item["product_id"]
        quantity = item["quantity"]

        if (
            type(product_id) is not int
            or not 1 <= product_id <= MAX_PRODUCT_ID
        ):
            _invalid(
                f"{prefix}.product_id",
                "ID sản phẩm phải là số nguyên dương "
                "trong giới hạn BIGINT.",
            )

        if (
            type(quantity) is not int
            or not 1 <= quantity <= MAX_QUANTITY
        ):
            _invalid(
                f"{prefix}.quantity",
                "Số lượng phải là số nguyên dương "
                "trong giới hạn INT.",
            )

        if product_id in seen:
            _invalid(
                f"{prefix}.product_id",
                "Sản phẩm đã xuất hiện trong giỏ hàng.",
            )

        seen.add(product_id)

        result.append(
            {
                "product_id": product_id,
                "quantity": quantity,
            }
        )

    return result


def validate_idempotency_key(value: object) -> str:
    """Accept only canonical UUID4 strings; normalize uppercase."""
    if type(value) is not str:
        _invalid(
            "idempotency_key",
            "Idempotency key phải là chuỗi UUID4.",
        )

    candidate = value.strip().lower()

    if len(candidate) != 36:
        _invalid(
            "idempotency_key",
            "Idempotency key phải có định dạng UUID4.",
        )

    try:
        parsed = UUID(candidate)
    except (ValueError, AttributeError):
        _invalid(
            "idempotency_key",
            "Idempotency key phải có định dạng UUID4.",
        )

    if parsed.version != 4 or str(parsed) != candidate:
        _invalid(
            "idempotency_key",
            "Idempotency key phải là UUID phiên bản 4.",
        )

    return candidate


def validate_checkout_request(
    payload: object,
) -> dict[str, Any]:
    """Validate and normalize one untrusted checkout request.

    Required fields:
      receiver_name, receiver_phone, receiver_address,
      items, idempotency_key.

    Optional:
      note (None or missing -> empty string).

    Do not accept client-supplied customer_id, prices,
    order status, hash, timestamps, or stock values.
    """
    if type(payload) is not dict:
        _invalid(
            "checkout",
            "Dữ liệu checkout phải là một đối tượng.",
        )

    supplied = set(payload)

    missing = REQUIRED_FIELDS - supplied
    if missing:
        _invalid(
            "checkout",
            "Thiếu trường bắt buộc: "
            + ", ".join(sorted(missing)),
        )

    unexpected = supplied - ALLOWED_FIELDS
    if unexpected:
        _invalid(
            "checkout",
            "Yêu cầu chứa trường không được phép.",
        )

    return {
        "receiver_name": validate_receiver_name(
            payload["receiver_name"]
        ),
        "receiver_phone": validate_receiver_phone(
            payload["receiver_phone"]
        ),
        "receiver_address": validate_receiver_address(
            payload["receiver_address"]
        ),
        "note": validate_checkout_note(
            payload.get("note")
        ),
        "items": validate_checkout_items(
            payload["items"]
        ),
        "idempotency_key": validate_idempotency_key(
            payload["idempotency_key"]
        ),
    }
