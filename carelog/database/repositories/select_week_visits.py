from datetime import date, datetime

from psycopg import Cursor


def select_week_visits(
    cursor: Cursor,
    week_start: date,
    next_week_start: date,
    week_start_utc: datetime,
    next_week_start_utc: datetime,
    owner_user_id: int | None = None
) -> list[dict]:

    # Planned visits of the week, and completed visits whose local day is
    # in the week. Old completed visits without completed_date use
    # started_at, which is compared with the week's limits in UTC.
    # Cancelled visits are not included.
    #
    # Ordered by the day (completed day first, then planned day), then by
    # the time, then by priority. Visits without a day or a time come
    # first, because of NULLS FIRST.
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
            updated_at,
            user_id,
            created_by_user_id,
            updated_by_user_id
        FROM visits
        WHERE (
            (
                status = 'planned'
                AND planned_week = %s
            )
            OR (
                status = 'completed'
                AND completed_date >= %s
                AND completed_date < %s
            )
            OR (
                status = 'completed'
                AND completed_date IS NULL
                AND started_at >= %s
                AND started_at < %s
            )
        )
    """

    values = [
        week_start,
        week_start,
        next_week_start,
        week_start_utc,
        next_week_start_utc
    ]

    # With owner_user_id only the visits of that worker are returned.
    # The parentheses above keep the condition for every status.
    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    sql += """
        ORDER BY
            COALESCE(completed_date, planned_date) NULLS FIRST,
            COALESCE(started_at, planned_at) NULLS FIRST,
            priority,
            id
    """

    cursor.execute(sql, tuple(values))

    results = cursor.fetchall()
    visits = []

    for result in results:
        visit = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            visit[column_name] = result[index]

        visits.append(visit)

    return visits
