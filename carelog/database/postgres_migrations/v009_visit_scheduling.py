def upgrade(cursor):
    # DATE columns hold the local calendar day (Europe/Helsinki).
    # Durations are whole minutes.
    cursor.execute("""
        ALTER TABLE visits
            ADD COLUMN planned_date DATE NULL,
            ADD COLUMN completed_date DATE NULL,
            ADD COLUMN planned_duration_minutes INT NULL,
            ADD COLUMN duration_minutes INT NULL
    """)
