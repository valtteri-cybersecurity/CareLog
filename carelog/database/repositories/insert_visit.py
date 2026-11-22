from datetime import date, datetime
from decimal import Decimal

from pymysql.cursors import Cursor


def insert_visit(
    cursor: Cursor,
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
            price
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            price
        )
    )

    return cursor.lastrowid
