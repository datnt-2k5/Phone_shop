
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

# Đọc cấu hình từ file .env ở thư mục gốc
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# Xây dựng URL kết nối an toàn
DATABASE_URL = URL.create(
    drivername="mysql+pymysql",
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3307")),
    database=os.environ["DB_NAME"],
    query={"charset": "utf8mb4"},
)


# Tạo SQLAlchemy Engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


# Bảo đảm mỗi kết nối có Strict Mode
@event.listens_for(engine, "connect", insert=True)
def ensure_strict_mode(
    dbapi_connection,
    connection_record,
):
    cursor = dbapi_connection.cursor()

    try:
        cursor.execute(
            "SELECT @@SESSION.sql_mode"
        )
        current_mode = cursor.fetchone()[0] or ""

        modes = [
            mode.strip()
            for mode in current_mode.split(",")
            if mode.strip()
        ]

        enabled_modes = {
            mode.upper()
            for mode in modes
        }

        if not (
            "STRICT_TRANS_TABLES" in enabled_modes
            or "STRICT_ALL_TABLES" in enabled_modes
        ):
            modes.append("STRICT_TRANS_TABLES")

            cursor.execute(
                "SET SESSION sql_mode = %s",
                (",".join(modes),),
            )
    finally:
        cursor.close()


# Factory tạo Session cho nghiệp vụ
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)
