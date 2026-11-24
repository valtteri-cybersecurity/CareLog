from decimal import Decimal

from psycopg import Cursor


def insert_service(
    cursor: Cursor,
    created_by_user_id: int,
    name: str,
    description: str | None = None,
    default_hourly_rate: Decimal | None = None
) -> int:

    sql = """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate,
            created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (name, description, default_hourly_rate, created_by_user_id)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
