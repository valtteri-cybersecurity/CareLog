from pymysql.cursors import Cursor


def select_visit_expenses(cursor: Cursor, visit_id: int) -> list[dict]:

    # Only the expenses of this visit. General expenses have a NULL
    # visit_id, and NULL never equals a number, so they are left out.
    # Oldest first. Expenses of the same day are ordered by id.
    sql = """
        SELECT id, visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE visit_id = %s
        ORDER BY expense_date ASC, id ASC
    """

    cursor.execute(sql, (visit_id,))

    results = cursor.fetchall()
    expenses = []

    for result in results:
        expense = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            expense[column_name] = result[index]

        expenses.append(expense)

    return expenses
