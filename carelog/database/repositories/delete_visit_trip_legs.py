from psycopg import Cursor


def delete_visit_trip_legs(cursor: Cursor, visit_id: int) -> None:

    # Removes the legs of one visit only, so that a new list can
    # replace them in the same transaction.

    sql = """
        DELETE FROM visit_trip_legs
        WHERE visit_id = %s
    """

    cursor.execute(sql, (visit_id,))
