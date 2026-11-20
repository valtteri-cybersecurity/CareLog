from pymysql.cursors import Cursor


def archive_client_record(
    cursor: Cursor,
    client_id: int
) -> bool:

    sql = """
        UPDATE clients
        SET archived_at = UTC_TIMESTAMP()
        WHERE id = %s
        AND archived_at IS NULL
    """

    cursor.execute(sql, (client_id,))

    if cursor.rowcount == 0:
        return False

    return True
