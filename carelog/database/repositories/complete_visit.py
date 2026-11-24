from datetime import date, datetime

from psycopg import Cursor


def complete_visit_record(
    cursor: Cursor,
    updated_by_user_id: int,
    visit_id: int,
    completed_date: date,
    duration_minutes: int | None,
    started_at: datetime | None,
    ended_at: datetime | None
) -> bool:

    # Check if visit exists and lock it until the transaction ends,
    # so two completions cannot succeed at the same time.

    cursor.execute(
        """
        SELECT status
        FROM visits
        WHERE id = %s
        FOR UPDATE
        """,
        (visit_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return False

    if result[0] != "planned":
        raise ValueError("Only planned visits can be completed")

    # Only the completed fields and the latest editor change. The plan
    # and the worker stay as they were.

    sql = """
        UPDATE visits
        SET status = 'completed',
            completed_date = %s,
            duration_minutes = %s,
            started_at = %s,
            ended_at = %s,
            updated_by_user_id = %s
        WHERE id = %s
        AND status = 'planned'
    """

    cursor.execute(
        sql,
        (completed_date, duration_minutes, started_at, ended_at, updated_by_user_id, visit_id)
    )

    if cursor.rowcount != 1:
        raise ValueError("Visit was changed by another operation")

    return True
