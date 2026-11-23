from psycopg import Cursor


def select_visit_status_for_update(cursor: Cursor, visit_id: int) -> str | None:

    # Returns the status of the visit and locks the row until the
    # transaction ends. Returns None if the visit does not exist.

    cursor.execute(
        """
        SELECT status
        FROM visits
        WHERE id = %s
        FOR UPDATE
        """,
        (visit_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return None

    return result[0]
