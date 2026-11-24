from psycopg import Cursor


def archive_client_record(
    cursor: Cursor,
    client_id: int
) -> bool:

    # The current time in UTC, stored without a time zone
    sql = """
        UPDATE clients
        SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
        WHERE id = %s
        AND archived_at IS NULL
    """

    cursor.execute(sql, (client_id,))

    if cursor.rowcount == 0:
        return False

    return True
