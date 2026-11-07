from sqlalchemy import text

from database.connection import engine


def main():
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("""
                    SELECT
                        VERSION() AS version,
                        DATABASE() AS db_name,
                        @@SESSION.sql_mode AS sql_mode
                """)
            ).mappings().one()

            print("KẾT NỐI MARIADB THÀNH CÔNG!")
            print("Phiên bản:", result["version"])
            print("Database:", result["db_name"])
            print("SQL Mode:", result["sql_mode"])

            modes = {
                mode.strip().upper()
                for mode in result["sql_mode"].split(",")
            }

            if (
                "STRICT_TRANS_TABLES" in modes
                or "STRICT_ALL_TABLES" in modes
            ):
                print("Strict Mode: OK")
            else:
                raise RuntimeError(
                    "Strict Mode chưa được bật!"
                )

    except Exception as error:
        print("KẾT NỐI / KIỂM TRA THẤT BẠI!")
        print(type(error).__name__)
        print(str(error))
        raise


if __name__ == "__main__":
    main()
