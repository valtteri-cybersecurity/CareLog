def upgrade(cursor):
    # NULL passes a CHECK constraint, so optional columns stay optional.
    checks = [
        ("visits", "chk_visits_planned_duration", "planned_duration_minutes > 0"),
        ("visits", "chk_visits_duration", "duration_minutes > 0"),
        ("visits", "chk_visits_priority", "priority BETWEEN 1 AND 3"),
        (
            "visits",
            "chk_visits_status",
            "status IN ('planned', 'completed', 'cancelled')",
        ),
    ]

    # The table and constraint names are fixed values from the list above.
    for table, name, condition in checks:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ADD CONSTRAINT {name} CHECK ({condition})"
        )
