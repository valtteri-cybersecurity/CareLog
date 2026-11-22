from pymysql.cursors import Cursor


def select_visit_trip_legs(cursor: Cursor, visit_id: int) -> list[dict]:

    # In the order of the trip
    sql = """
        SELECT id, visit_id, position, start_location, destination, distance_km
        FROM visit_trip_legs
        WHERE visit_id = %s
        ORDER BY position ASC, id ASC
    """

    cursor.execute(sql, (visit_id,))

    results = cursor.fetchall()
    legs = []

    for result in results:
        leg = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            leg[column_name] = result[index]

        legs.append(leg)

    return legs
