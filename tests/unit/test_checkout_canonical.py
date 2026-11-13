
"""Task 51 / US09-T04: canonical checkout payload tests."""

import json
from copy import deepcopy

import pytest

from models.app_error import AppError
from services.checkout_canonical import (
    create_canonical_json,
    create_canonical_payload,
)

KEY_A = "123e4567-e89b-42d3-a456-426614174000"
KEY_B = "123e4567-e89b-42d3-a456-426614174111"

EXPECTED_JSON = (
    '{"items":[{"product_id":5,"quantity":1},'
    '{"product_id":12,"quantity":2}],'
    '"note":"",'
    '"receiver_address":"Cao Lanh, Dong Thap",'
    '"receiver_name":"Nguyen Van A",'
    '"receiver_phone":"0912345678"}'
)


def valid_request():
    """Return a fresh checkout request for each test."""
    return {
        "receiver_name": "Nguyen Van A",
        "receiver_phone": "0912345678",
        "receiver_address": "Cao Lanh, Dong Thap",
        "note": "",
        "items": [
            {"product_id": 12, "quantity": 2},
            {"product_id": 5, "quantity": 1},
        ],
        "idempotency_key": KEY_A,
    }


def assert_invalid(request):
    """Malformed requests must fail through Task 50 validation."""
    with pytest.raises(AppError) as caught:
        create_canonical_json(request)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert caught.value.errors


def test_canonical_payload_has_exact_five_fields():
    result = create_canonical_payload(valid_request())

    assert set(result) == {
        "receiver_name",
        "receiver_phone",
        "receiver_address",
        "note",
        "items",
    }

    assert "idempotency_key" not in result
    assert "customer_id" not in result
    assert "unit_price" not in result
    assert "total_amount" not in result
    assert "created_at" not in result


def test_canonical_items_are_sorted_numerically():
    result = create_canonical_payload(valid_request())

    assert result["items"] == [
        {"product_id": 5, "quantity": 1},
        {"product_id": 12, "quantity": 2},
    ]


def test_canonical_json_matches_exact_golden_string():
    result = create_canonical_json(valid_request())

    assert result == EXPECTED_JSON


def test_canonical_json_round_trip_is_lossless():
    canonical = create_canonical_json(valid_request())
    payload = create_canonical_payload(valid_request())

    assert json.loads(canonical) == payload


def test_canonicalization_does_not_mutate_request():
    request = valid_request()
    original = deepcopy(request)

    create_canonical_payload(request)
    create_canonical_json(request)

    assert request == original

    assert [
        row["product_id"]
        for row in request["items"]
    ] == [12, 5]


def test_canonical_payload_is_an_independent_copy():
    request = valid_request()

    result = create_canonical_payload(request)

    result["items"][0]["quantity"] = 99
    result["receiver_name"] = "Modified"

    assert request["receiver_name"] == "Nguyen Van A"
    assert request["items"][1]["quantity"] == 1


def test_repeated_canonicalization_is_deterministic():
    request = valid_request()

    results = [
        create_canonical_json(request)
        for _ in range(10)
    ]

    assert len(set(results)) == 1


def test_original_dictionary_key_order_does_not_matter():
    request = valid_request()
    reordered = dict(reversed(list(request.items())))

    assert create_canonical_json(request) == (
        create_canonical_json(reordered)
    )


def test_product_order_does_not_change_canonical_json():
    request_a = valid_request()
    request_b = deepcopy(request_a)

    request_b["items"].reverse()

    assert create_canonical_json(request_a) == (
        create_canonical_json(request_b)
    )


def test_item_dictionary_key_order_does_not_matter():
    request = valid_request()
    changed = deepcopy(request)

    changed["items"] = [
        dict(reversed(list(row.items())))
        for row in changed["items"]
    ]

    assert create_canonical_json(request) == (
        create_canonical_json(changed)
    )


def test_different_idempotency_keys_have_same_business_payload():
    request_a = valid_request()
    request_b = valid_request()

    request_b["idempotency_key"] = KEY_B

    assert create_canonical_payload(request_a) == (
        create_canonical_payload(request_b)
    )

    assert create_canonical_json(request_a) == (
        create_canonical_json(request_b)
    )


def test_uppercase_uuid4_does_not_change_canonical_json():
    request_a = valid_request()
    request_b = valid_request()

    request_b["idempotency_key"] = KEY_A.upper()

    assert create_canonical_json(request_a) == (
        create_canonical_json(request_b)
    )


def test_missing_null_and_empty_note_are_equivalent():
    request_a = valid_request()
    request_b = valid_request()
    request_c = valid_request()

    request_a.pop("note")
    request_b["note"] = None
    request_c["note"] = ""

    first = create_canonical_json(request_a)

    assert first == create_canonical_json(request_b)
    assert first == create_canonical_json(request_c)


def test_whitespace_normalization_produces_same_json():
    request_a = valid_request()
    request_b = valid_request()

    request_b["receiver_name"] = " Nguyen  Van \n A "
    request_b["receiver_phone"] = " 0912345678 "
    request_b["receiver_address"] = (
        " Cao Lanh,   Dong \n Thap "
    )

    assert create_canonical_json(request_a) == (
        create_canonical_json(request_b)
    )


def test_vietnamese_unicode_is_preserved():
    request = valid_request()

    request["receiver_name"] = "Nguyễn Văn An"
    request["receiver_address"] = "Cao Lãnh, Đồng Tháp"
    request["note"] = "Giao hàng trước 17 giờ"

    canonical = create_canonical_json(request)

    assert "Nguyễn Văn An" in canonical
    assert "Cao Lãnh, Đồng Tháp" in canonical
    assert "Giao hàng trước 17 giờ" in canonical
    assert "\\u1ec5" not in canonical

    assert json.loads(canonical)["receiver_name"] == (
        "Nguyễn Văn An"
    )


def test_canonical_json_is_compact_and_key_sorted():
    canonical = create_canonical_json(valid_request())

    # JSON phải đúng chuỗi canonical đã định nghĩa.
    assert canonical == EXPECTED_JSON

    # Kiểm tra định dạng compact bằng cách parse rồi
    # serialize lại với cùng quy tắc canonical.
    parsed = json.loads(canonical)

    compact_json = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    assert canonical == compact_json

    # Thứ tự key phải ổn định.
    assert canonical.startswith('{"items":')

    # Dấu phẩy và khoảng trắng thuộc nội dung địa chỉ
    # phải được giữ nguyên.
    assert "Cao Lanh, Dong Thap" in canonical


def test_product_ids_and_quantities_remain_integers():
    payload = create_canonical_payload(valid_request())

    for item in payload["items"]:
        assert type(item["product_id"]) is int
        assert type(item["quantity"]) is int


@pytest.mark.parametrize(
    "field,changed_value",
    [
        ("receiver_name", "Nguyen Van B"),
        ("receiver_phone", "0987654321"),
        ("receiver_address", "Da Nang"),
        ("note", "Giao buoi sang"),
    ],
)
def test_business_field_change_produces_different_json(
    field,
    changed_value,
):
    original = valid_request()
    modified = deepcopy(original)

    modified[field] = changed_value

    assert create_canonical_json(original) != (
        create_canonical_json(modified)
    )


def test_quantity_change_produces_different_json():
    original = valid_request()
    modified = deepcopy(original)

    modified["items"][0]["quantity"] = 3

    assert create_canonical_json(original) != (
        create_canonical_json(modified)
    )


def test_product_change_produces_different_json():
    original = valid_request()
    modified = deepcopy(original)

    modified["items"][0]["product_id"] = 13

    assert create_canonical_json(original) != (
        create_canonical_json(modified)
    )


def test_duplicate_product_id_is_rejected():
    request = valid_request()

    request["items"].append(
        {"product_id": 5, "quantity": 2}
    )

    assert_invalid(request)


def test_empty_cart_is_rejected():
    request = valid_request()
    request["items"] = []

    assert_invalid(request)


def test_twenty_items_are_accepted_and_sorted():
    request = valid_request()

    request["items"] = [
        {"product_id": product_id, "quantity": 1}
        for product_id in range(20, 0, -1)
    ]

    payload = create_canonical_payload(request)

    assert len(payload["items"]) == 20

    assert [
        row["product_id"]
        for row in payload["items"]
    ] == list(range(1, 21))


def test_twenty_one_items_are_rejected():
    request = valid_request()

    request["items"] = [
        {"product_id": product_id, "quantity": 1}
        for product_id in range(1, 22)
    ]

    assert_invalid(request)


def test_invalid_idempotency_key_is_rejected():
    request = valid_request()
    request["idempotency_key"] = "not-a-uuid4"

    assert_invalid(request)


@pytest.mark.parametrize(
    "bad_payload",
    [
        None,
        [],
        "checkout",
    ],
)
def test_invalid_checkout_container_is_rejected(bad_payload):
    assert_invalid(bad_payload)


@pytest.mark.parametrize(
    "field",
    [
        "customer_id",
        "unit_price",
        "total_amount",
        "request_hash",
        "created_at",
        "stock",
    ],
)
def test_untrusted_top_level_fields_are_rejected(field):
    request = valid_request()
    request[field] = "client-controlled"

    assert_invalid(request)


@pytest.mark.parametrize(
    "field",
    [
        "unit_price",
        "cost_price",
    ],
)
def test_untrusted_item_fields_are_rejected(field):
    request = valid_request()
    request["items"][0][field] = 100

    assert_invalid(request)


@pytest.mark.parametrize(
    "quantity",
    [
        0,
        -1,
        "2",
        True,
    ],
)
def test_invalid_quantities_are_rejected(quantity):
    request = valid_request()
    request["items"][0]["quantity"] = quantity

    assert_invalid(request)


@pytest.mark.parametrize(
    "product_id",
    [
        0,
        True,
        "5",
    ],
)
def test_invalid_product_ids_are_rejected(product_id):
    request = valid_request()
    request["items"][0]["product_id"] = product_id

    assert_invalid(request)


def test_trimmed_note_is_canonicalized_consistently():
    request_a = valid_request()
    request_b = valid_request()

    request_a["note"] = "Giao buoi sang"
    request_b["note"] = "  Giao buoi sang  "

    assert create_canonical_json(request_a) == (
        create_canonical_json(request_b)
    )


def test_canonical_json_can_be_encoded_as_utf8():
    request = valid_request()
    request["receiver_name"] = "Nguyễn Văn An"

    canonical = create_canonical_json(request)
    encoded = canonical.encode("utf-8")

    assert isinstance(encoded, bytes)
    assert encoded.decode("utf-8") == canonical
    assert b"Nguy" in encoded
