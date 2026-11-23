def upgrade(cursor):
    # PostgreSQL can roll back ALTER TABLE. If one constraint fails, the
    # whole migration is cancelled, so no "already exists" checks are
    # needed as in the MySQL version.
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

    # The table and constraint names are fixed values from the list above.
    for table, name, condition in checks:
        cursor.execute(
            f"ALTER TABLE {table} "
            f"ADD CONSTRAINT {name} CHECK ({condition})"
        )
