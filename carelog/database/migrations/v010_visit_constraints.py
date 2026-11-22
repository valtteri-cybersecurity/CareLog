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

    for table, name, condition in checks:
        cursor.execute("""
            SELECT 1
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = %s
              AND CONSTRAINT_TYPE = 'CHECK'
        """, (table, name))

        if cursor.fetchone() is not None:
            continue

        cursor.execute(
            f"ALTER TABLE `{table}` "
            f"ADD CONSTRAINT `{name}` CHECK ({condition})"
        )
