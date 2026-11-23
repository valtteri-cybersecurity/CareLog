from decimal import Decimal

from psycopg import Cursor


def insert_visit_trip_leg(
    cursor: Cursor,
    visit_id: int,
    position: int,
    start_location: str,
    destination: str,
    distance_km: Decimal | None
) -> int:

    sql = """
        INSERT INTO visit_trip_legs (
            visit_id,
            position,
            start_location,
            destination,
            distance_km
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (visit_id, position, start_location, destination, distance_km)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
