from psycopg import Cursor


def select_expense(
    cursor: Cursor,
    expense_id: int,
    owner_user_id: int | None = None
) -> dict | None:
    sql = """
        SELECT id, visit_id, expense_date, amount, category, description,
               user_id, created_by_user_id, updated_by_user_id, updated_at
        FROM expenses
        WHERE id = %s
    """

    values = [expense_id]

    # With owner_user_id only an expense of that worker is found.
    # Another worker's expense gives None, as a missing expense does.
    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    cursor.execute(sql, tuple(values))

    result = cursor.fetchone()

    if result is None:
        return None

    expense = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        expense[column_name] = result[index]

    return expense
