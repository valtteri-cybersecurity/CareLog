from pymysql.cursors import Cursor


def select_clients(cursor: Cursor) -> list[dict]:
    sql = """
        SELECT *
        FROM clients
        WHERE archived_at IS NULL
        ORDER BY last_name, first_name, id
    """

    cursor.execute(sql)

    results = cursor.fetchall()
    clients = []

    for result in results:
        client = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            client[column_name] = result[index]

        clients.append(client)

    return clients
