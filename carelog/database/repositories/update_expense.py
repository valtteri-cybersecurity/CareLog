from psycopg import Cursor


ALLOWED_FIELDS = (
    "expense_date",
    "amount",
    "category",
    "description",
    "visit_id"
)


def select_expense_for_update(
    cursor: Cursor,
    expense_id: int,
    owner_user_id: int | None = None
) -> dict | None:

    # Reads the expense and locks the row until the transaction ends,
    # so the service validates the changes against current data and no
    # other update can change the row in between. With owner_user_id
    # another worker's expense is treated as missing.

    sql = """
        SELECT id, visit_id, expense_date, amount, category, description,
               user_id
        FROM expenses
        WHERE id = %s
    """

    values = [expense_id]

    if owner_user_id is not None:
        sql += " AND user_id = %s"
        values.append(owner_user_id)

    sql += " FOR UPDATE"

    cursor.execute(sql, tuple(values))

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
    updated_by_user_id: int,
    expense_id: int,
    changes: dict
) -> bool:

    # Check if expense exists and lock it until the transaction ends.
    # The existence is checked here, so the result does not depend on
    # the rowcount of the UPDATE.

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

    # The latest editor is not one of ALLOWED_FIELDS: it always comes
    # from the user who performs the update. user_id and
    # created_by_user_id are never changed here.
    updates.append("updated_by_user_id = %s")
    values.append(updated_by_user_id)

    sql = "UPDATE expenses SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s"

    values.append(expense_id)

    cursor.execute(sql, tuple(values))

    return True
