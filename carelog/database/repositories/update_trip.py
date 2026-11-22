from pymysql.cursors import Cursor


ALLOWED_FIELDS = (
    "start_location",
    "destination",
    "distance_km"
)


def update_trip_record(
    cursor: Cursor,
    trip_id: int,
    changes: dict
) -> bool:

    # Check if trip exists

    cursor.execute(
        """
        SELECT id
        FROM trips
        WHERE id = %s
        FOR UPDATE
        """,
        (trip_id,)
    )

    if cursor.fetchone() is None:
        return False

    # Build UPDATE query

    updates = []
    values = []

    for field, value in changes.items():
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid trip field")

        updates.append(f"{field} = %s")
        values.append(value)

    if not updates:
        raise ValueError("No fields to update")

    sql = "UPDATE trips SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s"

    values.append(trip_id)

    cursor.execute(sql, tuple(values))

    return True
