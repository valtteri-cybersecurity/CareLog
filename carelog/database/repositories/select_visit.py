from psycopg import Cursor


def select_visit(
    cursor: Cursor,
    visit_id: int,
    for_update: bool = False,
    owner_user_id: int | None = None
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
            updated_at,
            user_id,
            created_by_user_id,
            updated_by_user_id
        FROM visits
        WHERE id = %s
    """

    values = [visit_id]

    # With owner_user_id only a visit of that worker is found. Another
    # worker's visit gives None, as a missing visit does.
    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    # FOR UPDATE locks the row until the transaction ends. If another
    # transaction has changed the row but not committed yet, this waits
    # and then returns the committed, current values. The owner condition
    # is checked again against those values, so a visit that was given to
    # another worker meanwhile is not returned.
    if for_update:
        sql += " FOR UPDATE"

    cursor.execute(sql, tuple(values))

    result = cursor.fetchone()

    if result is None:
        return None

    visit = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        visit[column_name] = result[index]

    return visit
