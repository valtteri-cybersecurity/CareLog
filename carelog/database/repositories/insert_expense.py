from datetime import date
from decimal import Decimal

from pymysql.cursors import Cursor


def insert_expense(
    cursor: Cursor,
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
            description
        )
        VALUES (%s, %s, %s, %s, %s)
    """

    cursor.execute(
        sql,
        (visit_id, expense_date, amount, category, description)
    )

    return cursor.lastrowid
