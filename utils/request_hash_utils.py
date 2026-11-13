
"""Task 52 / US09-T05: SHA-256 utility for canonical JSON.

This utility only hashes the exact string it receives.
It does not validate checkout fields, reorder JSON keys,
look up products, or access the database.

The checkout Service must first obtain canonical JSON from
services.checkout_canonical.create_canonical_json().
"""

import hashlib


def hash_canonical_json(canonical_json: str) -> str:
    """Return the lowercase 64-character SHA-256 hexadecimal digest.

    The input must already be canonical JSON. Hash its exact
    UTF-8 bytes without adding whitespace, a newline, a
    timestamp, an idempotency key or any other data.

    An empty string is allowed at this low-level utility,
    because SHA-256 is defined for empty input. The checkout
    validator independently rejects an empty checkout.
    """
    if type(canonical_json) is not str:
        raise TypeError(
            "Canonical JSON phải là chuỗi ký tự."
        )

    try:
        data = canonical_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(
            "Canonical JSON chứa ký tự Unicode không hợp lệ."
        ) from exc

    return hashlib.sha256(data).hexdigest()
