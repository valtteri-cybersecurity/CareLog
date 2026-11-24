from decimal import Decimal

from psycopg import Cursor


def insert_trip(
    cursor: Cursor,
    created_by_user_id: int,
    client_id: int,
    start_location: str,
    destination: str,
    distance_km: Decimal | None = None
) -> int:

    sql = """
        INSERT INTO trips (
            client_id,
            start_location,
            destination,
            distance_km,
            created_by_user_id
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (client_id, start_location, destination, distance_km, created_by_user_id)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
