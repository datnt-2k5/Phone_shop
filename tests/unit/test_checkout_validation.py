
"""Task 50 / US09-T03: checkout validation unit tests."""

from copy import deepcopy

import pytest

from models.app_error import AppError
from services.checkout_validation import (
    MAX_CART_LINES,
    MAX_NOTE_BYTES,
    MAX_PRODUCT_ID,
    MAX_QUANTITY,
    REQUIRED_FIELDS,
    validate_checkout_items,
    validate_checkout_note,
    validate_checkout_request,
    validate_idempotency_key,
    validate_receiver_address,
    validate_receiver_name,
    validate_receiver_phone,
)

UUID4_KEY = "123e4567-e89b-42d3-a456-426614174000"


def valid_request():
    """Return a fresh valid checkout payload for every test."""
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "Giao trong gio hanh chinh",
        "items": [
            {"product_id": 12, "quantity": 2},
            {"product_id": 5, "quantity": 1},
        ],
        "idempotency_key": UUID4_KEY,
    }


def assert_invalid(call, field):
    """Assert safe validation errors instead of Python exceptions."""
    with pytest.raises(AppError) as caught:
        call()

    error = caught.value

    assert error.error_code == "VALIDATION_ERROR"
    assert error.message == "Thông tin đặt hàng không hợp lệ."
    assert field in error.errors
    assert isinstance(error.errors[field], str)
    assert error.errors[field]


def test_valid_checkout_returns_normalized_payload():
    request = valid_request()

    result = validate_checkout_request(request)

    assert result == request
    assert result is not request
    assert result["items"] is not request["items"]
    assert result["items"][0] is not request["items"][0]


def test_whitespace_is_normalized_in_receiver_fields():
    request = valid_request()

    request["receiver_name"] = "  Nguyen   Van \n A  "
    request["receiver_phone"] = " 0912345678 "
    request["receiver_address"] = "  12  Tran   Phu \n Dong Thap "
    request["note"] = "  Giao buoi sang  "

    result = validate_checkout_request(request)

    assert result["receiver_name"] == "Nguyen Van A"
    assert result["receiver_phone"] == "0912345678"
    assert result["receiver_address"] == "12 Tran Phu Dong Thap"
    assert result["note"] == "Giao buoi sang"


@pytest.mark.parametrize(
    "note",
    [None, ""],
)
def test_optional_note_normalizes_to_empty_string(note):
    request = valid_request()
    request["note"] = note

    assert validate_checkout_request(request)["note"] == ""


def test_missing_note_defaults_to_empty_string():
    request = valid_request()
    request.pop("note")

    result = validate_checkout_request(request)

    assert result["note"] == ""


def test_checkout_supports_vietnamese_unicode():
    request = valid_request()
    request["receiver_name"] = "  Nguyễn  Văn   An "
    request["receiver_address"] = "  Cao Lãnh,  Đồng Tháp "
    request["note"] = "Giao đến nhà, gọi trước."

    result = validate_checkout_request(request)

    assert result["receiver_name"] == "Nguyễn Văn An"
    assert result["receiver_address"] == "Cao Lãnh, Đồng Tháp"
    assert result["note"] == "Giao đến nhà, gọi trước."


def test_checkout_does_not_mutate_original_payload():
    request = valid_request()
    original = deepcopy(request)

    validate_checkout_request(request)

    assert request == original


def test_checkout_items_are_independent_copies():
    request = valid_request()
    result = validate_checkout_request(request)

    result["items"][0]["quantity"] = 99
    result["items"].append(
        {"product_id": 20, "quantity": 1}
    )

    assert request["items"] == [
        {"product_id": 12, "quantity": 2},
        {"product_id": 5, "quantity": 1},
    ]


def test_items_keep_original_order_until_canonical_task():
    request = valid_request()

    result = validate_checkout_request(request)

    assert [
        item["product_id"]
        for item in result["items"]
    ] == [12, 5]


def test_twenty_distinct_products_are_accepted():
    request = valid_request()
    request["items"] = [
        {"product_id": i, "quantity": 1}
        for i in range(1, MAX_CART_LINES + 1)
    ]

    result = validate_checkout_request(request)

    assert len(result["items"]) == 20


@pytest.mark.parametrize(
    "bad_payload",
    [None, [], "checkout", 123, True],
)
def test_checkout_requires_dictionary(bad_payload):
    assert_invalid(
        lambda: validate_checkout_request(bad_payload),
        "checkout",
    )


@pytest.mark.parametrize(
    "missing_field",
    sorted(REQUIRED_FIELDS),
)
def test_checkout_rejects_missing_required_fields(missing_field):
    request = valid_request()
    request.pop(missing_field)

    assert_invalid(
        lambda: validate_checkout_request(request),
        "checkout",
    )


@pytest.mark.parametrize(
    "untrusted_field",
    [
        "customer_id",
        "status",
        "unit_price",
        "total_amount",
        "request_hash",
        "created_at",
    ],
)
def test_checkout_rejects_untrusted_top_level_fields(
    untrusted_field,
):
    request = valid_request()
    request[untrusted_field] = "client-supplied"

    assert_invalid(
        lambda: validate_checkout_request(request),
        "checkout",
    )


@pytest.mark.parametrize(
    "bad_name",
    [None, 123, "", " \n ", "A" * 101],
)
def test_invalid_receiver_name_is_rejected(bad_name):
    assert_invalid(
        lambda: validate_receiver_name(bad_name),
        "receiver_name",
    )


def test_receiver_name_accepts_exact_maximum_length():
    assert validate_receiver_name("A" * 100) == "A" * 100


@pytest.mark.parametrize(
    "bad_phone",
    [
        None,
        123,
        "",
        "1234567890",
        "012345678",
        "01234567890",
        "0abcdefghi",
        "０１２３４５６７８９",
        "01234 56789",
    ],
)
def test_invalid_receiver_phone_is_rejected(bad_phone):
    assert_invalid(
        lambda: validate_receiver_phone(bad_phone),
        "receiver_phone",
    )


def test_phone_preserves_leading_zero():
    assert validate_receiver_phone(
        " 0912345678 "
    ) == "0912345678"


@pytest.mark.parametrize(
    "bad_address",
    [None, 123, "", " \n ", "A" * 256],
)
def test_invalid_receiver_address_is_rejected(bad_address):
    assert_invalid(
        lambda: validate_receiver_address(bad_address),
        "receiver_address",
    )


def test_receiver_address_accepts_exact_maximum_length():
    assert validate_receiver_address(
        "A" * 255
    ) == "A" * 255


@pytest.mark.parametrize(
    "bad_note",
    [
        123,
        False,
        ["text"],
        "A" * (MAX_NOTE_BYTES + 1),
        "\ud800",
    ],
)
def test_invalid_note_is_rejected(bad_note):
    assert_invalid(
        lambda: validate_checkout_note(bad_note),
        "note",
    )


def test_note_accepts_exact_text_byte_limit():
    value = "A" * MAX_NOTE_BYTES

    assert validate_checkout_note(value) == value


def test_note_limit_is_checked_in_utf8_bytes():
    # One Vietnamese character occupies multiple UTF-8 bytes.
    assert_invalid(
        lambda: validate_checkout_note("á" * 32_768),
        "note",
    )


@pytest.mark.parametrize(
    "bad_items",
    [
        None,
        (),
        {},
        "items",
        [],
        [
            {"product_id": i, "quantity": 1}
            for i in range(1, 22)
        ],
    ],
)
def test_invalid_items_container_is_rejected(bad_items):
    assert_invalid(
        lambda: validate_checkout_items(bad_items),
        "items",
    )


@pytest.mark.parametrize(
    "bad_item",
    [
        None,
        [],
        {},
        {"product_id": 1},
        {"quantity": 1},
        {
            "product_id": 1,
            "quantity": 1,
            "unit_price": 100,
        },
        {
            "product_id": 1,
            "quantity": 1,
            "cost_price": 50,
        },
    ],
)
def test_invalid_item_shape_is_rejected(bad_item):
    assert_invalid(
        lambda: validate_checkout_items([bad_item]),
        "items[0]",
    )


@pytest.mark.parametrize(
    "bad_id",
    [
        0,
        -1,
        True,
        "1",
        1.5,
        None,
        MAX_PRODUCT_ID + 1,
    ],
)
def test_invalid_product_id_is_rejected(bad_id):
    assert_invalid(
        lambda: validate_checkout_items(
            [{"product_id": bad_id, "quantity": 1}]
        ),
        "items[0].product_id",
    )


def test_bigint_maximum_product_id_is_accepted():
    assert validate_checkout_items(
        [{"product_id": MAX_PRODUCT_ID, "quantity": 1}]
    ) == [
        {"product_id": MAX_PRODUCT_ID, "quantity": 1}
    ]


@pytest.mark.parametrize(
    "bad_quantity",
    [
        0,
        -1,
        True,
        "2",
        1.5,
        None,
        MAX_QUANTITY + 1,
    ],
)
def test_invalid_item_quantity_is_rejected(bad_quantity):
    assert_invalid(
        lambda: validate_checkout_items(
            [{"product_id": 10, "quantity": bad_quantity}]
        ),
        "items[0].quantity",
    )


def test_maximum_sql_int_quantity_is_accepted():
    assert validate_checkout_items(
        [{"product_id": 10, "quantity": MAX_QUANTITY}]
    ) == [
        {"product_id": 10, "quantity": MAX_QUANTITY}
    ]


def test_duplicate_product_id_is_rejected():
    items = [
        {"product_id": 10, "quantity": 1},
        {"product_id": 10, "quantity": 2},
    ]

    assert_invalid(
        lambda: validate_checkout_items(items),
        "items[1].product_id",
    )


@pytest.mark.parametrize(
    "bad_key",
    [
        None,
        123,
        "",
        "not-a-uuid",
        "123e4567-e89b-12d3-a456-426614174000",
        "123e4567-e89b-42d3-a456-42661417400",
        "{123e4567-e89b-42d3-a456-426614174000}",
        "123e4567e89b42d3a456426614174000",
        "123e4567-e89b-42d3-7456-426614174000",
    ],
)
def test_invalid_idempotency_key_is_rejected(bad_key):
    assert_invalid(
        lambda: validate_idempotency_key(bad_key),
        "idempotency_key",
    )


def test_uppercase_uuid4_is_normalized():
    result = validate_idempotency_key(
        " " + UUID4_KEY.upper() + " "
    )

    assert result == UUID4_KEY


def test_checkout_does_not_accept_client_price_in_items():
    request = valid_request()
    request["items"][0]["unit_price"] = "1"

    assert_invalid(
        lambda: validate_checkout_request(request),
        "items[0]",
    )


def test_checkout_does_not_accept_client_stock():
    request = valid_request()
    request["items"][0]["stock"] = 9999

    assert_invalid(
        lambda: validate_checkout_request(request),
        "items[0]",
    )
