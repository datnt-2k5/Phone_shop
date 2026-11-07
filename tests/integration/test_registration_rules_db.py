
"""Task 12 / US01 - Real MariaDB registration integration tests.

Uses the existing test_db fixture: phone_shop_test only.
The outer test transaction is rolled back after every test.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from secrets import token_hex

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.app_error import AppError
from services.auth_service import AuthService, RegistrationResult


def _email() -> str:
    """Generate a unique email for each test."""

    return f"task12_{token_hex(6)}@example.test"


def _service(connection: Connection) -> AuthService:
    """Create AuthService using the isolated test connection."""

    def session_factory() -> Session:
        return Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

    return AuthService(session_factory=session_factory)


def _register(
    service: AuthService,
    email: str,
    password: str = "MatKhau123!",
) -> RegistrationResult:
    """Register a Customer using a complete valid request."""

    return service.register(
        email=email,
        password=password,
        confirm_password=password,
        full_name="  Nguyễn   Văn A  ",
        phone="0912345678",
    )


def _count(test_db: Connection, email: str) -> int:
    """Count rows in the test database by email."""

    return int(
        test_db.execute(
            text("""
                SELECT COUNT(*)
                FROM users
                WHERE email = :email
            """),
            {"email": email},
        ).scalar_one()
    )


def test_valid_registration_persists_customer_and_bcrypt(
    test_db: Connection,
) -> None:
    """Valid registration must persist a CUSTOMER/ACTIVE user."""

    email = _email()
    password = "A1" + "é" * 35

    assert len(password.encode("utf-8")) == 72

    result = _register(
        _service(test_db),
        f"  {email.upper()}  ",
        password,
    )

    # Check the AuthService response
    assert result.user_id > 0
    assert result.email == email
    assert result.full_name == "Nguyễn Văn A"
    assert result.role == "CUSTOMER"
    assert result.status == "ACTIVE"

    # No password or password_hash may appear in the response
    assert "password" not in asdict(result)
    assert "password_hash" not in asdict(result)

    # Query the actual MariaDB row
    row = test_db.execute(
        text("""
            SELECT
                email,
                password_hash,
                full_name,
                phone,
                role,
                status
            FROM users
            WHERE id = :user_id
        """),
        {"user_id": result.user_id},
    ).mappings().one()

    assert row["email"] == email
    assert row["full_name"] == "Nguyễn Văn A"
    assert row["phone"] == "0912345678"
    assert row["role"] == "CUSTOMER"
    assert row["status"] == "ACTIVE"

    # Password is hashed, not stored as plain text
    assert row["password_hash"] != password

    assert bcrypt.checkpw(
        password.encode("utf-8"),
        row["password_hash"].encode("ascii"),
    )


@pytest.mark.parametrize(
    "variant",
    [
        "upper",
        "mixed",
        "padded",
    ],
)
def test_duplicate_email_case_variants_are_rejected(
    test_db: Connection,
    variant: str,
) -> None:
    """Case and surrounding spaces must not bypass uniqueness."""

    email = _email()
    service = _service(test_db)

    first = _register(service, email)

    variants = {
        "upper": email.upper(),
        "mixed": email.replace(
            "task12_",
            "TaSk12_",
        ),
        "padded": f"  {email.upper()}  ",
    }

    with pytest.raises(AppError) as caught:
        _register(
            service,
            variants[variant],
            "MatKhau456!",
        )

    assert caught.value.error_code == "EMAIL_EXISTS"
    assert "email" in caught.value.errors

    # Only the original account can exist
    assert _count(test_db, email) == 1

    original_id = test_db.execute(
        text("""
            SELECT id
            FROM users
            WHERE email = :email
        """),
        {"email": email},
    ).scalar_one()

    assert original_id == first.user_id


def test_database_unique_email_is_case_insensitive(
    test_db: Connection,
) -> None:
    """Database UNIQUE must protect email even without AuthService."""

    email = _email()

    first = _register(
        _service(test_db),
        email,
    )

    first_hash = test_db.execute(
        text("""
            SELECT password_hash
            FROM users
            WHERE id = :id
        """),
        {"id": first.user_id},
    ).scalar_one()

    # Direct SQL deliberately bypasses Service validation.
    # SAVEPOINT protects the surrounding test transaction.
    with pytest.raises(IntegrityError) as caught, test_db.begin_nested():
        test_db.execute(
            text("""
                    INSERT INTO users (
                        email,
                        password_hash,
                        full_name,
                        phone,
                        role,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :email,
                        :password_hash,
                        :full_name,
                        :phone,
                        'CUSTOMER',
                        'ACTIVE',
                        :now,
                        :now
                    )
                """),
            {
                "email": email.upper(),
                "password_hash": first_hash,
                "full_name": "Second Test User",
                "phone": "0912345678",
                "now": datetime.now(UTC).replace(
                    tzinfo=None
                ),
            },
        )

    # MariaDB error 1062 = Duplicate entry
    assert caught.value.orig.args[0] == 1062

    assert _count(test_db, email) == 1


@pytest.mark.parametrize(
    "password",
    [
        "A1" + "a" * 71,
        "A1" + "é" * 36,
        "A1" + "😀" * 18,
    ],
)
def test_overlong_password_is_rejected_without_insert(
    test_db: Connection,
    password: str,
) -> None:
    """Invalid bcrypt length must not create a database row."""

    email = _email()

    assert len(password.encode("utf-8")) > 72

    with pytest.raises(AppError) as caught:
        _register(
            _service(test_db),
            email,
            password,
        )

    assert caught.value.error_code == "VALIDATION_ERROR"
    assert "password" in caught.value.errors

    # No account must have been inserted
    assert _count(test_db, email) == 0


@pytest.mark.parametrize(
    "forged_role",
    [
        "ADMIN",
        "SUPER_ADMIN",
    ],
)
def test_register_cannot_assign_admin_roles(
    test_db: Connection,
    forged_role: str,
) -> None:
    """Reject attempts to assign a privileged role on signup."""

    email = _email()

    with pytest.raises(TypeError) as caught:
        _service(test_db).register(
            email=email,
            password="MatKhau123!",
            confirm_password="MatKhau123!",
            full_name="Nguyễn Văn A",
            phone="0912345678",
            role=forged_role,
        )

    assert "role" in str(caught.value)

    # Forged signup must create no user
    assert _count(test_db, email) == 0
