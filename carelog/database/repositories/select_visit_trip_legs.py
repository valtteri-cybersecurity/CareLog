from psycopg import Cursor


def select_visit_trip_legs(
    cursor: Cursor,
    visit_id: int,
    owner_user_id: int | None = None
) -> list[dict]:

    # With owner_user_id only the legs of that worker's visit are
    # returned. The kilometres belong to the worker of the visit.
    sql = """
        SELECT l.id, l.visit_id, l.position, l.start_location, l.destination,
               l.distance_km, l.created_by_user_id
        FROM visit_trip_legs AS l
        JOIN visits AS v
          ON v.id = l.visit_id
        WHERE l.visit_id = %s
    """

    values = [visit_id]

    if owner_user_id is not None:
        sql += " AND v.user_id = %s"
        values.append(owner_user_id)

    # In the order of the trip
    sql += " ORDER BY l.position ASC, l.id ASC"

    cursor.execute(sql, tuple(values))

    results = cursor.fetchall()
    legs = []

    for result in results:
        leg = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            leg[column_name] = result[index]

        legs.append(leg)

    return legs
