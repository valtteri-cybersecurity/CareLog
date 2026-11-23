from psycopg import Cursor


def select_planned_visits(cursor: Cursor) -> list[dict]:

    # All planned visits, also the ones left in past weeks.
    # NULLS FIRST: within a week the visits without a day come first, and
    # within a day the visits without a time come first. PostgreSQL would
    # otherwise sort NULL last.
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
        WHERE status = 'planned'
        ORDER BY
            planned_week NULLS FIRST,
            planned_date NULLS FIRST,
            planned_at NULLS FIRST,
            priority,
            id
    """

    cursor.execute(sql)

    results = cursor.fetchall()
    visits = []

    for result in results:
        visit = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            visit[column_name] = result[index]

        visits.append(visit)

    return visits
