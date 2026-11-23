from psycopg import Cursor


def select_client(
    cursor: Cursor,
    client_id: int,
    for_update: bool = False
) -> dict | None:
    sql = """
        SELECT *
        FROM clients
        WHERE id = %s
    """

    # FOR UPDATE locks the row until the transaction ends. An UPDATE of
    # the client, such as archiving, must then wait. If another
    # transaction has changed the row but not committed yet, this waits
    # and then returns the committed, current values.
    if for_update:
        sql += " FOR UPDATE"

    cursor.execute(sql, (client_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    client = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        client[column_name] = result[index]

    return client
