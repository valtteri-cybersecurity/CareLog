from psycopg import Cursor


def select_client_visits(cursor: Cursor, client_id: int) -> list[dict]:

    # Newest first by the visit day: the completed day, then the planned
    # day, then the planned week. Visits without any of these use the
    # creation time. The id keeps the order stable.
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
        WHERE client_id = %s
        ORDER BY
            COALESCE(completed_date, planned_date, planned_week, DATE(created_at)) DESC,
            created_at DESC,
            id DESC
    """

    cursor.execute(sql, (client_id,))

    results = cursor.fetchall()
    visits = []

    for result in results:
        visit = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            visit[column_name] = result[index]

        visits.append(visit)

    return visits
