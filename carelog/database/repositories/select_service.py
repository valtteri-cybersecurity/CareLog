from psycopg import Cursor


def select_service(cursor: Cursor, service_id: int) -> dict | None:
    sql = """
        SELECT *
        FROM services
        WHERE id = %s
    """

    cursor.execute(sql, (service_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    service = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        service[column_name] = result[index]

    return service
