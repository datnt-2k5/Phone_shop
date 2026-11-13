
"""Task 52 / US09-T05: SHA-256 request hash for checkout.

Pipeline:
    raw request
    -> Task 50 validation
    -> Task 51 canonical JSON
    -> UTF-8
    -> SHA-256 hexadecimal digest

No authentication, database access, current product lookup,
order insertion or idempotency lookup is performed here.
"""

from models.app_error import AppError
from services.checkout_canonical import create_canonical_json
from utils.request_hash_utils import hash_canonical_json


def create_request_hash(checkout_request: object) -> str:
    """Calculate a deterministic hash of checkout business data.

    The canonical JSON intentionally excludes idempotency_key,
    customer_id, prices, stock, timestamps and order status.

    Task 53 will compare this digest with the stored request_hash
    for an existing (customer_id, idempotency_key) pair.
    """
    canonical_json = create_canonical_json(checkout_request)

    try:
        return hash_canonical_json(canonical_json)
    except ValueError as exc:
        # The checkout validator already checks note encoding,
        # but recipient fields might contain an invalid Unicode
        # surrogate. Do not expose Unicode internals to the UI.
        raise AppError(
            "VALIDATION_ERROR",
            "Thông tin đặt hàng không hợp lệ.",
            {
                "checkout": (
                    "Dữ liệu chứa ký tự không thể mã hóa UTF-8."
                )
            },
        ) from exc
