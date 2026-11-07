
from uuid import uuid4

PREFIXES = {
    "order": "DH",
    "import_receipt": "PN",
    "invoice": "HD",
    "stock_adjustment": "DC",
}


def generate_temp_code() -> str:
    return f"TMP-{uuid4().hex}"


def generate_code(
    record_type: str,
    record_id: int
) -> str:
    if record_type not in PREFIXES:
        raise ValueError(
            "Loại chứng từ không hợp lệ"
        )

    if type(record_id) is not int or record_id <= 0:
        raise ValueError(
            "ID phải là số nguyên dương"
        )

    prefix = PREFIXES[record_type]

    return f"{prefix}{record_id:08d}"
