from datetime import date

from psycopg import Cursor


def select_expenses(
    cursor: Cursor,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    client_id: int | None = None
) -> list[dict]:

    # Every filter that is given is added as a fixed SQL condition, and
    # all of them must match (AND). Only the values come from the caller,
    # and they are passed as %s parameters.

    sql = """
        SELECT
            expenses.id,
            expenses.visit_id,
            expenses.expense_date,
            expenses.amount,
            expenses.category,
            expenses.description
        FROM expenses
    """

    conditions = []
    values = []

    # A client's expenses are found through the visit. The JOIN also
    # leaves out general expenses, because their visit_id is NULL.
    if client_id is not None:
        sql += " JOIN visits ON visits.id = expenses.visit_id"
        conditions.append("visits.client_id = %s")
        values.append(client_id)

    # Both limit days are included.
    if start_date is not None:
        conditions.append("expenses.expense_date >= %s")
        values.append(start_date)

    if end_date is not None:
        conditions.append("expenses.expense_date <= %s")
        values.append(end_date)

    if category is not None:
        conditions.append("expenses.category = %s")
        values.append(category)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    # Oldest first. Expenses of the same day are ordered by id.
    sql += " ORDER BY expenses.expense_date ASC, expenses.id ASC"

    cursor.execute(sql, tuple(values))

    results = cursor.fetchall()
    expenses = []

    for result in results:
        expense = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            expense[column_name] = result[index]

        expenses.append(expense)

    return expenses
