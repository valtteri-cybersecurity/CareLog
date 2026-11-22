from pymysql.cursors import Cursor


def select_trips(cursor: Cursor, client_id: int) -> list[dict]:

    sql = """
        SELECT id, client_id, start_location, destination, distance_km
        FROM trips
        WHERE client_id = %s
        ORDER BY start_location, destination, id
    """

    cursor.execute(sql, (client_id,))

    results = cursor.fetchall()
    trips = []

    for result in results:
        trip = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            trip[column_name] = result[index]

        trips.append(trip)

    return trips
