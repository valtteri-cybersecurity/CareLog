from psycopg import Cursor


def select_visit_status_for_update(
    cursor: Cursor,
    visit_id: int,
    owner_user_id: int | None = None
) -> str | None:

    # Returns the status of the visit and locks the row until the
    # transaction ends. Returns None if the visit does not exist, or with
    # owner_user_id, if it belongs to another worker.

    sql = """
        SELECT status
        FROM visits
        WHERE id = %s
    """

    values = [visit_id]

    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    sql += " FOR UPDATE"

    cursor.execute(sql, tuple(values))

    result = cursor.fetchone()

    if result is None:
        return None

    return result[0]
