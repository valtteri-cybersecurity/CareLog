from psycopg import Cursor


ALLOWED_FIELDS = {
    "first_name": 100,
    "last_name": 100,
    "phone": 50,
    "email": 255,
    "street_address": 255,
    "postal_code": 20,
    "city": 100,
    "distance_from_home_km": None
}


def update_client_record(
    cursor: Cursor,
    updated_by_user_id: int,
    client_id: int,
    changes: dict
) -> bool:

    # Check if client exists and is active

    cursor.execute(
        """
        SELECT id
        FROM clients
        WHERE id = %s AND archived_at IS NULL
        FOR UPDATE
        """,
        (client_id,)
    )

    if cursor.fetchone() is None:
        return False

    # Build UPDATE query

    updates = []
    values = []

    for field, value in changes.items():
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid client field")

        updates.append(f"{field} = %s")
        values.append(value)

    if not updates:
        raise ValueError("No fields to update")

    # The latest editor is not one of ALLOWED_FIELDS: it always comes
    # from the user who performs the update.
    updates.append("updated_by_user_id = %s")
    values.append(updated_by_user_id)

    sql = "UPDATE clients SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s AND archived_at IS NULL"

    values.append(client_id)

    cursor.execute(sql, tuple(values))

    return True
