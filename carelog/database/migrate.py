from carelog.database.connection import get_connection
from carelog.database.migrations import (
    v001_users,
    v002_clients,
    v003_services,
    v004_trips,
    v005_visits,
    v006_visit_notes,
    v007_expenses,
)


def create_migrations_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)


def get_applied_versions(cursor):
    cursor.execute("""
        SELECT version FROM schema_migrations
    """)

    results = cursor.fetchall()
    versions = set()

    for result in results:
        version = result[0]
        versions.add(version)

    return versions


def record_migration(cursor, version):
    cursor.execute("""
        INSERT INTO schema_migrations (version)
        VALUES (%s)
    """, (version,))


def run_migrations(database=None, *, password):
    if not password:
        raise ValueError("A password for carelog_migrator is required")

    connection = None
    cursor = None

    try:
        connection = get_connection(
            database=database,
            user="carelog_migrator",
            password=password,
        )

        cursor = connection.cursor()
        create_migrations_table(cursor)
        applied_versions = get_applied_versions(cursor)

        migrations = [
            (1, v001_users.upgrade),
            (2, v002_clients.upgrade),
            (3, v003_services.upgrade),
            (4, v004_trips.upgrade),
            (5, v005_visits.upgrade),
            (6, v006_visit_notes.upgrade),
            (7, v007_expenses.upgrade),
        ]

        for version, upgrade in migrations:
            if version not in applied_versions:
                upgrade(cursor)
                record_migration(cursor, version)
                connection.commit()

    except Exception as error:
        print(f"Migration error: {error}")

        if connection is not None:
            connection.rollback()

        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit("Run database migrations through install.sh")
