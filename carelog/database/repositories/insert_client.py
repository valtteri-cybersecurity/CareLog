from psycopg import Cursor


def insert_client(
    cursor: Cursor,
    created_by_user_id: int,
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
        INSERT INTO clients (first_name, last_name, phone, email, street_address, postal_code, city, distance_from_home_km, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (first_name, last_name, phone, email, street_address, postal_code, city, distance_from_home_km, created_by_user_id)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
