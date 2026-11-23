def upgrade(cursor):
    # PostgreSQL does not create indexes for foreign keys automatically.
    # These columns are used in WHERE and JOIN conditions of the
    # repositories. visit_trip_legs.visit_id needs no index of its own,
    # because it is the first column of uq_trip_legs_visit_position.
    # visits.service_id is not used in any query, so it gets no index.
    indexes = [
        ("idx_visits_client_id", "visits", "client_id"),
        ("idx_trips_client_id", "trips", "client_id"),
        ("idx_visit_notes_visit_id", "visit_notes", "visit_id"),
        ("idx_expenses_visit_id", "expenses", "visit_id"),
    ]

    # The names are fixed values from the list above.
    for name, table, column in indexes:
        cursor.execute(f"CREATE INDEX {name} ON {table} ({column})")
