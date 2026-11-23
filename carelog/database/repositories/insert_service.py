from decimal import Decimal

from psycopg import Cursor


def insert_service(
    cursor: Cursor,
    name: str,
    description: str | None = None,
    default_hourly_rate: Decimal | None = None
) -> int:

    sql = """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate
        )
        VALUES (%s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (name, description, default_hourly_rate)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
