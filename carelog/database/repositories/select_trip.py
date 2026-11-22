from pymysql.cursors import Cursor


def select_trip(cursor: Cursor, trip_id: int) -> dict | None:
    sql = """
        SELECT id, client_id, start_location, destination, distance_km
        FROM trips
        WHERE id = %s
    """

    cursor.execute(sql, (trip_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    trip = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        trip[column_name] = result[index]

    return trip
