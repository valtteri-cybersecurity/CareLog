from pymysql.cursors import Cursor


ALLOWED_FIELDS = (
    "expense_date",
    "amount",
    "category",
    "description",
    "visit_id"
)


def select_expense_for_update(cursor: Cursor, expense_id: int) -> dict | None:

    # Reads the expense and locks the row until the transaction ends,
    # so the service validates the changes against current data and no
    # other update can change the row in between.

    cursor.execute(
        """
        SELECT id, visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE id = %s
        FOR UPDATE
        """,
        (expense_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return None

    expense = {}

    for index, column in enumerate(cursor.description):
        column_name = column[0]
        expense[column_name] = result[index]

    return expense


def update_expense_record(
    cursor: Cursor,
    expense_id: int,
    changes: dict
) -> bool:

    # Check if expense exists and lock it until the transaction ends.
    # The rowcount of the UPDATE is not used, because it is 0 when the
    # new values are the same as the old ones.

    cursor.execute(
        """
        SELECT id
        FROM expenses
        WHERE id = %s
        FOR UPDATE
        """,
        (expense_id,)
    )

    if cursor.fetchone() is None:
        return False

    # Build UPDATE query

    updates = []
    values = []

    for field, value in changes.items():
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid expense field")

        updates.append(f"{field} = %s")
        values.append(value)

    if not updates:
        raise ValueError("No fields to update")

    sql = "UPDATE expenses SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s"

    values.append(expense_id)

    cursor.execute(sql, tuple(values))

    return True
