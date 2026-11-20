from pymysql.cursors import Cursor


def insert_client(
    cursor: Cursor,
    first_name: str,
    last_name: str,
    phone: str | None = None,
    email: str | None = None,
    street_address: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
    distance_from_home_km: float | int | None = None

) -> int:
    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, phone, email, street_address, postal_code, city, distance_from_home_km)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (first_name, last_name, phone, email, street_address, postal_code, city, distance_from_home_km)
    )

    return cursor.lastrowid
