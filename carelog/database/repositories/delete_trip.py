from psycopg import Cursor


def delete_trip_record(
    cursor: Cursor,
    trip_id: int
) -> bool:

    sql = """
        DELETE FROM trips
        WHERE id = %s
    """

    cursor.execute(sql, (trip_id,))

    if cursor.rowcount == 0:
        return False

    return True
