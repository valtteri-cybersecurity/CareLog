from decimal import Decimal

from pymysql.cursors import Cursor


def insert_trip(
    cursor: Cursor,
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
            distance_km
        )
        VALUES (%s, %s, %s, %s)
    """

    cursor.execute(
        sql,
        (client_id, start_location, destination, distance_km)
    )

    return cursor.lastrowid
