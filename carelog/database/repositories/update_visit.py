from psycopg import Cursor


ALLOWED_FIELDS = (
    "service_id",
    "priority",
    "planned_week",
    "planned_date",
    "planned_at",
    "planned_duration_minutes",
    "description"
)


def update_visit_record(
    cursor: Cursor,
    updated_by_user_id: int,
    visit_id: int,
    changes: dict
) -> bool:

    # Check if visit exists and lock it until the transaction ends,
    # so it cannot be completed or cancelled at the same time.

    cursor.execute(
        """
        SELECT status
        FROM visits
        WHERE id = %s
        FOR UPDATE
        """,
        (visit_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return False

    if result[0] != "planned":
        raise ValueError("Only planned visits can be updated")

    # Build UPDATE query

    updates = []
    values = []

    for field, value in changes.items():
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid visit field")

        updates.append(f"{field} = %s")
        values.append(value)

    if not updates:
        raise ValueError("No fields to update")

    # The latest editor is not one of ALLOWED_FIELDS: it always comes
    # from the user who performs the update.
    updates.append("updated_by_user_id = %s")
    values.append(updated_by_user_id)

    sql = "UPDATE visits SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s AND status = 'planned'"

    values.append(visit_id)

    cursor.execute(sql, tuple(values))

    return True
