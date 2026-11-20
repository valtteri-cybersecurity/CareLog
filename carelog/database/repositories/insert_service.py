from decimal import Decimal

from pymysql.cursors import Cursor


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
    """

    cursor.execute(
        sql,
        (name, description, default_hourly_rate)
    )

    return cursor.lastrowid
