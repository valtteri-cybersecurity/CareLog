from pymysql.cursors import Cursor


def select_services(cursor: Cursor) -> list[dict]:

    sql = """
        SELECT id, name, description, default_hourly_rate
        FROM services
        ORDER BY name, id
    """

    cursor.execute(sql)

    results = cursor.fetchall()
    services = []

    for result in results:
        service = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            service[column_name] = result[index]

        services.append(service)

    return services
