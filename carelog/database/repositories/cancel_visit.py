from psycopg import Cursor


def cancel_visit_record(
    cursor: Cursor,
    visit_id: int
) -> bool:

    # Check if visit exists and lock it until the transaction ends,
    # so it cannot be completed and cancelled at the same time.

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
        return False

    if result[0] != "planned":
        raise ValueError("Only planned visits can be cancelled")

    # Only the status changes. The visit is kept for the history.

    sql = """
        UPDATE visits
        SET status = 'cancelled'
        WHERE id = %s
        AND status = 'planned'
    """

    cursor.execute(sql, (visit_id,))

    if cursor.rowcount != 1:
        raise ValueError("Visit was changed by another operation")

    return True
