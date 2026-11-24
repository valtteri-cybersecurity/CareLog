from psycopg import Cursor


def select_visit_expenses(
    cursor: Cursor,
    visit_id: int,
    owner_user_id: int | None = None
) -> list[dict]:

    # Only the expenses of this visit. General expenses have a NULL
    # visit_id, and NULL never equals a number, so they are left out.
    sql = """
        SELECT id, visit_id, expense_date, amount, category, description,
               user_id, created_by_user_id, updated_by_user_id, updated_at
        FROM expenses
        WHERE visit_id = %s
    """

    values = [visit_id]

    # With owner_user_id only that worker's expenses are returned. The
    # owner of the expense decides, not the worker of the visit.
    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    # Oldest first. Expenses of the same day are ordered by id.
    sql += " ORDER BY expense_date ASC, id ASC"

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
