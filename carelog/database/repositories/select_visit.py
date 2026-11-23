from psycopg import Cursor


def select_visit(cursor: Cursor, visit_id: int) -> dict | None:
    sql = """
        SELECT
            id,
            client_id,
            service_id,
            status,
            priority,
            planned_week,
            planned_date,
            planned_at,
            planned_duration_minutes,
            completed_date,
            duration_minutes,
            started_at,
            ended_at,
            description,
            distance_km,
            price,
            created_at,
            updated_at
        FROM visits
        WHERE id = %s
    """

    cursor.execute(sql, (visit_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    visit = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        visit[column_name] = result[index]

    return visit
