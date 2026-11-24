from psycopg import Cursor


def archive_client_record(
    cursor: Cursor,
    updated_by_user_id: int,
    client_id: int
) -> bool:

    # The current time in UTC, stored without a time zone
    sql = """
        UPDATE clients
        SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
            updated_by_user_id = %s
        WHERE id = %s
        AND archived_at IS NULL
    """

    cursor.execute(sql, (updated_by_user_id, client_id))

    if cursor.rowcount == 0:
        return False

    return True
