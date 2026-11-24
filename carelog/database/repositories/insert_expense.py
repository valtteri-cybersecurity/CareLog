from datetime import date
from decimal import Decimal

from psycopg import Cursor


def insert_expense(
    cursor: Cursor,
    user_id: int,
    created_by_user_id: int,
    expense_date: date,
    amount: Decimal,
    category: str,
    visit_id: int | None = None,
    description: str | None = None
) -> int:

    # No commit here, so the same function can be used inside another
    # transaction later.

    sql = """
        INSERT INTO expenses (
            visit_id,
            expense_date,
            amount,
            category,
            description,
            user_id,
            created_by_user_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (visit_id, expense_date, amount, category, description, user_id, created_by_user_id)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
