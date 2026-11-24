from datetime import date, datetime
from decimal import Decimal

from psycopg import Cursor


def insert_visit(
    cursor: Cursor,
    user_id: int,
    created_by_user_id: int,
    client_id: int,
    service_id: int,
    status: str,
    priority: int,
    planned_week: date | None = None,
    planned_date: date | None = None,
    planned_at: datetime | None = None,
    planned_duration_minutes: int | None = None,
    description: str | None = None,
    completed_date: date | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    duration_minutes: int | None = None,
    distance_km: Decimal | None = None,
    price: Decimal | None = None
) -> int:

    sql = """
        INSERT INTO visits (
            client_id,
            service_id,
            status,
            priority,
            planned_week,
            planned_date,
            planned_at,
            planned_duration_minutes,
            description,
            completed_date,
            started_at,
            ended_at,
            duration_minutes,
            distance_km,
            price,
            user_id,
            created_by_user_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (
            client_id,
            service_id,
            status,
            priority,
            planned_week,
            planned_date,
            planned_at,
            planned_duration_minutes,
            description,
            completed_date,
            started_at,
            ended_at,
            duration_minutes,
            distance_km,
            price,
            user_id,
            created_by_user_id
        )
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
