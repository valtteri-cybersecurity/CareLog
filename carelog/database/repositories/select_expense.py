from pymysql.cursors import Cursor


def select_expense(cursor: Cursor, expense_id: int) -> dict | None:
    sql = """
        SELECT id, visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE id = %s
    """

    cursor.execute(sql, (expense_id,))

    result = cursor.fetchone()

    if result is None:
        return None

    expense = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        expense[column_name] = result[index]

    return expense
