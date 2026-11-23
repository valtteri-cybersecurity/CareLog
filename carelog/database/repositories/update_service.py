from psycopg import Cursor


ALLOWED_FIELDS = (
    "name",
    "description",
    "default_hourly_rate"
)


def update_service_record(
    cursor: Cursor,
    service_id: int,
    changes: dict
) -> bool:

    # Check if service exists

    cursor.execute(
        """
        SELECT id
        FROM services
        WHERE id = %s
        FOR UPDATE
        """,
        (service_id,)
    )

    if cursor.fetchone() is None:
        return False

    # Build UPDATE query

    updates = []
    values = []

    for field, value in changes.items():
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid service field")

        updates.append(f"{field} = %s")
        values.append(value)

    if not updates:
        raise ValueError("No fields to update")

    sql = "UPDATE services SET "
    sql += ", ".join(updates)
    sql += " WHERE id = %s"

    values.append(service_id)

    cursor.execute(sql, tuple(values))

    return True
