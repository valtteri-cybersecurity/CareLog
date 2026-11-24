from psycopg import Cursor


def cancel_visit_record(
    cursor: Cursor,
    updated_by_user_id: int,
    visit_id: int,
    owner_user_id: int | None = None
) -> bool:

    # Check if visit exists and lock it until the transaction ends,
    # so it cannot be completed and cancelled at the same time. With
    # owner_user_id another worker's visit is treated as missing.

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
        return False

    if result[0] != "planned":
        raise ValueError("Only planned visits can be cancelled")

    # Only the status and the latest editor change. The visit and its
    # worker are kept for the history.

    sql = """
        UPDATE visits
        SET status = 'cancelled',
            updated_by_user_id = %s
        WHERE id = %s
        AND status = 'planned'
    """

    cursor.execute(sql, (updated_by_user_id, visit_id))

    if cursor.rowcount != 1:
        raise ValueError("Visit was changed by another operation")

    return True
