def upgrade(cursor):
    # A previous run may have added the columns but crashed before the
    # migration was recorded. One ALTER TABLE statement is atomic in
    # MySQL 8, so either all four columns exist or none of them do.
    cursor.execute("""
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'visits'
          AND COLUMN_NAME = 'planned_date'
    """)

    if cursor.fetchone() is not None:
        return

    # DATE columns hold the local calendar day (Europe/Helsinki).
    # Durations are whole minutes.
    cursor.execute("""
        ALTER TABLE visits
            ADD COLUMN planned_date DATE NULL,
            ADD COLUMN completed_date DATE NULL,
            ADD COLUMN planned_duration_minutes INT NULL,
            ADD COLUMN duration_minutes INT NULL
    """)
