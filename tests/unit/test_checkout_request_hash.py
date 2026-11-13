
"""Task 52 / US09-T05: checkout request SHA-256 regression tests."""

import json
import re
from copy import deepcopy
from hashlib import sha256

import pytest

from models.app_error import AppError
from services.checkout_canonical import create_canonical_json
from services.checkout_request_hash import create_request_hash
from utils.request_hash_utils import hash_canonical_json

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

EXPECTED_HASH = (
    "06ce89f6256f98bb9a9fc084a553432f"
    "bd35b6477a9a00409fa7ad1d4a3986a1"
)


def valid_request():
    """Construct a fresh request for every test."""
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


def assert_validation_error(payload):
    with pytest.raises(AppError) as caught:
        create_request_hash(payload)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert caught.value.errors


# ============================================================
# A. Pure SHA-256 utility tests
# ============================================================


def test_sha256_matches_known_hello_vector():
    assert hash_canonical_json("hello") == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b"
        "161e5c1fa7425e73043362938b9824"
    )


def test_sha256_matches_known_empty_string_vector():
    assert hash_canonical_json("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_hashes_exact_input_bytes():
    compact = '{"quantity":1}'
    spaced = '{"quantity": 1}'

    first = hash_canonical_json(compact)
    second = hash_canonical_json(spaced)

    assert first != second
    assert first == sha256(compact.encode("utf-8")).hexdigest()
    assert second == sha256(spaced.encode("utf-8")).hexdigest()


def test_sha256_uses_utf8_for_vietnamese_text():
    canonical = '{"note":"Giao hàng tại Cao Lãnh"}'

    result = hash_canonical_json(canonical)

    assert result == sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    assert re.fullmatch(r"[0-9a-f]{64}", result)


@pytest.mark.parametrize(
    "bad_input",
    [
        None,
        123,
        True,
        b"abc",
        {},
        ["json"],
    ],
)
def test_sha256_rejects_non_string_input(bad_input):
    with pytest.raises(TypeError):
        hash_canonical_json(bad_input)


def test_sha256_rejects_unpaired_unicode_surrogate():
    with pytest.raises(ValueError):
        hash_canonical_json('{"name":"\ud800"}')


# ============================================================
# B. Golden vectors and output format
# ============================================================


def test_task51_canonical_json_matches_golden_string():
    assert create_canonical_json(valid_request()) == EXPECTED_JSON


def test_checkout_request_hash_matches_golden_vector():
    assert create_request_hash(valid_request()) == EXPECTED_HASH


def test_checkout_hash_matches_standard_library_sha256():
    request = valid_request()
    canonical = create_canonical_json(request)

    expected = sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    assert create_request_hash(request) == expected


def test_checkout_hash_is_lowercase_64_character_hex():
    result = create_request_hash(valid_request())

    assert isinstance(result, str)
    assert len(result) == 64
    assert result == result.lower()
    assert re.fullmatch(r"[0-9a-f]{64}", result)


def test_checkout_hash_is_stable_across_repeated_calls():
    request = valid_request()

    values = {
        create_request_hash(request)
        for _ in range(20)
    }

    assert values == {EXPECTED_HASH}


def test_checkout_hash_does_not_mutate_original_request():
    request = valid_request()
    original = deepcopy(request)

    create_request_hash(request)

    assert request == original
    assert [
        row["product_id"]
        for row in request["items"]
    ] == [12, 5]


# ============================================================
# C. Semantically equivalent requests produce same hash
# ============================================================


def test_item_order_does_not_change_hash():
    first = valid_request()
    second = deepcopy(first)

    second["items"].reverse()

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_top_level_dictionary_key_order_does_not_change_hash():
    first = valid_request()
    second = dict(reversed(list(first.items())))

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_item_dictionary_key_order_does_not_change_hash():
    first = valid_request()
    second = deepcopy(first)

    second["items"] = [
        dict(reversed(list(row.items())))
        for row in second["items"]
    ]

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_different_idempotency_keys_do_not_change_hash():
    first = valid_request()
    second = valid_request()

    second["idempotency_key"] = KEY_B

    assert create_request_hash(first) == (
        create_request_hash(second)
    )

    assert create_request_hash(first) == EXPECTED_HASH


def test_uppercase_uuid4_does_not_change_hash():
    first = valid_request()
    second = valid_request()

    second["idempotency_key"] = KEY_A.upper()

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_missing_none_and_empty_note_are_equivalent():
    first = valid_request()
    second = valid_request()
    third = valid_request()

    first.pop("note")
    second["note"] = None
    third["note"] = ""

    hashes = {
        create_request_hash(first),
        create_request_hash(second),
        create_request_hash(third),
    }

    assert hashes == {EXPECTED_HASH}


def test_normalized_whitespace_produces_same_hash():
    first = valid_request()
    second = valid_request()

    second["receiver_name"] = " Nguyen  Van \n A "
    second["receiver_phone"] = " 0912345678 "
    second["receiver_address"] = (
        " Cao Lanh,  Dong \n Thap "
    )

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_trimmed_note_produces_same_hash():
    first = valid_request()
    second = valid_request()

    first["note"] = "Giao buoi sang"
    second["note"] = "  Giao buoi sang  "

    assert create_request_hash(first) == (
        create_request_hash(second)
    )


def test_vietnamese_checkout_hashes_exact_utf8_canonical_json():
    request = valid_request()
    request["receiver_name"] = "Nguyễn Văn An"
    request["receiver_address"] = "Cao Lãnh, Đồng Tháp"
    request["note"] = "Giao hàng trước 17 giờ"

    canonical = create_canonical_json(request)
    expected = sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    assert "Nguyễn Văn An" in canonical
    assert "Đồng Tháp" in canonical
    assert create_request_hash(request) == expected


# ============================================================
# D. Real business changes produce different hashes
# ============================================================


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("receiver_name", "Nguyen Van B"),
        ("receiver_phone", "0987654321"),
        ("receiver_address", "Da Nang"),
        ("note", "Giao buoi sang"),
    ],
)
def test_business_field_changes_hash(field, new_value):
    original = valid_request()
    modified = deepcopy(original)

    modified[field] = new_value

    assert create_request_hash(original) != (
        create_request_hash(modified)
    )


def test_quantity_change_produces_different_hash():
    original = valid_request()
    modified = deepcopy(original)

    modified["items"][0]["quantity"] = 3

    assert create_request_hash(original) != (
        create_request_hash(modified)
    )


def test_product_change_produces_different_hash():
    original = valid_request()
    modified = deepcopy(original)

    modified["items"][0]["product_id"] = 13

    assert create_request_hash(original) != (
        create_request_hash(modified)
    )


def test_twenty_items_produce_valid_hash():
    request = valid_request()

    request["items"] = [
        {"product_id": product_id, "quantity": 1}
        for product_id in range(20, 0, -1)
    ]

    result = create_request_hash(request)
    canonical = create_canonical_json(request)

    assert re.fullmatch(r"[0-9a-f]{64}", result)
    assert result == sha256(
        canonical.encode("utf-8")
    ).hexdigest()

    data = json.loads(canonical)
    assert [
        item["product_id"]
        for item in data["items"]
    ] == list(range(1, 21))


# ============================================================
# E. Invalid checkout data must not be hashed
# ============================================================


@pytest.mark.parametrize(
    "bad_payload",
    [
        None,
        [],
        "checkout",
        123,
    ],
)
def test_invalid_checkout_container_is_rejected(bad_payload):
    assert_validation_error(bad_payload)


def test_empty_cart_is_rejected_before_hashing():
    request = valid_request()
    request["items"] = []

    assert_validation_error(request)


def test_duplicate_product_is_rejected_before_hashing():
    request = valid_request()
    request["items"].append(
        {"product_id": 5, "quantity": 3}
    )

    assert_validation_error(request)


def test_more_than_twenty_items_are_rejected():
    request = valid_request()

    request["items"] = [
        {"product_id": product_id, "quantity": 1}
        for product_id in range(1, 22)
    ]

    assert_validation_error(request)


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "invalid-uuid",
        "123e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_invalid_idempotency_key_is_rejected(bad_key):
    request = valid_request()
    request["idempotency_key"] = bad_key

    assert_validation_error(request)


@pytest.mark.parametrize(
    "field",
    [
        "customer_id",
        "unit_price",
        "total_amount",
        "request_hash",
    ],
)
def test_untrusted_top_level_fields_are_rejected(field):
    request = valid_request()
    request[field] = "client-controlled"

    assert_validation_error(request)


@pytest.mark.parametrize(
    "field",
    [
        "unit_price",
        "cost_price",
        "stock",
    ],
)
def test_untrusted_item_fields_are_rejected(field):
    request = valid_request()
    request["items"][0][field] = 100

    assert_validation_error(request)


@pytest.mark.parametrize(
    "bad_quantity",
    [
        0,
        -1,
        "2",
        True,
    ],
)
def test_invalid_quantities_are_rejected(bad_quantity):
    request = valid_request()
    request["items"][0]["quantity"] = bad_quantity

    assert_validation_error(request)


@pytest.mark.parametrize(
    "bad_product_id",
    [
        0,
        True,
        "5",
    ],
)
def test_invalid_product_ids_are_rejected(bad_product_id):
    request = valid_request()
    request["items"][0]["product_id"] = bad_product_id

    assert_validation_error(request)


def test_invalid_unicode_is_reported_as_app_error():
    request = valid_request()
    request["receiver_name"] = "Nguyen \ud800"

    with pytest.raises(AppError) as caught:
        create_request_hash(request)

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "checkout" in caught.value.errors


# ============================================================
# F. Verify the dependency between Task 51 and Task 52
# ============================================================


def test_service_hashes_exact_canonical_json(monkeypatch):
    captured = []

    def recording_hash(canonical_json):
        captured.append(canonical_json)
        return EXPECTED_HASH

    monkeypatch.setattr(
        "services.checkout_request_hash.hash_canonical_json",
        recording_hash,
    )

    result = create_request_hash(valid_request())

    assert result == EXPECTED_HASH
    assert captured == [EXPECTED_JSON]


def test_invalid_checkout_does_not_call_sha256(monkeypatch):
    def forbidden_hash(canonical_json):
        pytest.fail(
            "SHA-256 must not run for invalid checkout data."
        )

    monkeypatch.setattr(
        "services.checkout_request_hash.hash_canonical_json",
        forbidden_hash,
    )

    request = valid_request()
    request["items"] = []

    assert_validation_error(request)
