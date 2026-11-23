from psycopg import Cursor


def select_visit(
    cursor: Cursor,
    visit_id: int,
    for_update: bool = False
) -> dict | None:
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

    # FOR UPDATE locks the row until the transaction ends. If another
    # transaction has changed the row but not committed yet, this waits
    # and then returns the committed, current values.
    if for_update:
        sql += " FOR UPDATE"

    cursor.execute(sql, (visit_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    visit = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        visit[column_name] = result[index]

    return visit
