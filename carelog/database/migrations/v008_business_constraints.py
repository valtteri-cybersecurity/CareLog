def upgrade(cursor):
    checks = [
        ("clients", "chk_clients_distance", "distance_from_home_km >= 0"),
        ("services", "chk_services_rate", "default_hourly_rate >= 0"),
        ("trips", "chk_trips_distance", "distance_km >= 0"),
        ("visits", "chk_visits_distance", "distance_km >= 0"),
        ("visits", "chk_visits_price", "price >= 0"),
        ("visits", "chk_visits_time", "ended_at >= started_at"),
        ("visit_notes", "chk_notes_content", "TRIM(content) <> ''"),
        ("expenses", "chk_expenses_amount", "amount > 0"),
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
