from pymysql.cursors import Cursor


def insert_client(
    cursor: Cursor,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    email: str | None = None,
    street_address: str | None = None
) -> int:
    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, phone, email, street_address)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (first_name, last_name, phone, email, street_address)
    )

    return cursor.lastrowid
