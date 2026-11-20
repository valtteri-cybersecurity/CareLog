
from pymysql.cursors import Cursor


def select_client(cursor: Cursor, client_id: int) -> dict | None:
    sql = """
        SELECT *
        FROM clients
        WHERE id = %s
    """

    cursor.execute(sql, (client_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    client = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        client[column_name] = result[index]

    return client
