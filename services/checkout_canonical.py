
"""Task 51 / US09-T04: canonical checkout payload.

Convert an untrusted checkout request into a deterministic
business payload and a canonical JSON string.

Rules:
- Reuse Task 50 validation and normalization.
- Sort items by numeric product_id.
- Exclude idempotency_key from the hash payload.
- Exclude customer_id, prices, stock, timestamps, and status.
- Preserve Vietnamese Unicode in JSON.
- Serialize using sorted keys and compact separators.
- Never change the caller's input object.

Hash calculation belongs to US09-T05 (Task 52).
No database access, session access, or order creation here.
"""

import json
from typing import Any

from services.checkout_validation import validate_checkout_request


def create_canonical_payload(
    checkout_request: object,
) -> dict[str, Any]:
    """Return the normalized, deterministically ordered hash payload.

    The input must be a full checkout request accepted by
    validate_checkout_request(), including its idempotency_key.

    The output deliberately excludes the idempotency_key.
    The Service uses that key separately for idempotency lookup.
    """
    validated = validate_checkout_request(checkout_request)

    sorted_items = sorted(
        validated["items"],
        key=lambda item: item["product_id"],
    )

    return {
        "receiver_name": validated["receiver_name"],
        "receiver_phone": validated["receiver_phone"],
        "receiver_address": validated["receiver_address"],
        "note": validated["note"],
        "items": [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
            }
            for item in sorted_items
        ],
    }


def create_canonical_json(
    checkout_request: object,
) -> str:
    """Serialize the canonical payload into stable UTF-8-ready JSON.

    No hashing is done here. Task 52 will compute SHA-256 over:
        create_canonical_json(request).encode("utf-8")
    """
    payload = create_canonical_payload(checkout_request)

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
