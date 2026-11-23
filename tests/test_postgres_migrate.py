import pytest

from carelog.database import postgres_migrate
from carelog.database.postgres_migrations import (
    v001_users,
    v002_clients,
    v003_services,
    v004_trips,
    v005_visits,
    v006_visit_notes,
    v007_expenses,
    v008_business_constraints,
    v009_visit_scheduling,
    v010_visit_constraints,
    v011_visit_trip_legs,
)
from tests.postgres_helpers import get_columns, insert_visit, table_exists


EXPECTED_VERSIONS = set(range(1, 13))


@pytest.fixture
def migration_database(postgres_cursor, connect_to_test_postgres, monkeypatch):
    postgres_cursor.execute("SELECT current_database()")
    database = postgres_cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection(database=None, user=None, password=None):
        assert user == "carelog_migrator"
        assert password == "test-only"
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(postgres_migrate, "get_postgres_connection", get_test_connection)

    return database


def test_run_migrations_requires_password():
    with pytest.raises(ValueError):
        postgres_migrate.run_postgres_migrations(password="")


def test_run_migrations_creates_tables(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    tables = [
        "users",
        "clients",
        "services",
        "trips",
        "visits",
        "visit_notes",
        "expenses",
        "visit_trip_legs",
        "schema_migrations",
    ]

    for table in tables:
        assert table_exists(postgres_cursor, table)


def test_run_migrations_records_versions(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS


def test_run_migrations_can_be_run_twice(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS
    postgres_migrate.validate_schema(postgres_cursor, EXPECTED_VERSIONS)


def test_run_migrations_creates_correct_columns(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    users = get_columns(postgres_cursor, "users")
    clients = get_columns(postgres_cursor, "clients")
    services = get_columns(postgres_cursor, "services")
    visits = get_columns(postgres_cursor, "visits")
    expenses = get_columns(postgres_cursor, "expenses")

    assert ("role", "character varying", "NO", "'worker'::character varying") in users
    assert ("is_active", "boolean", "NO", "true") in users

    assert ("street_address", "character varying", "YES", None) in clients
    assert ("archived_at", "timestamp without time zone", "YES", None) in clients

    assert ("description", "text", "YES", None) in services
    assert ("default_hourly_rate", "numeric", "YES", None) in services

    assert ("priority", "smallint", "NO", "2") in visits
    assert ("planned_date", "date", "YES", None) in visits
    assert ("duration_minutes", "integer", "YES", None) in visits
    assert ("description", "character varying", "YES", None) in expenses

    for column in clients:
        assert column[0] != "personal_identity_code"


def test_run_migrations_creates_business_constraints(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    postgres_cursor.execute("""
        SELECT r.relname, c.conname
        FROM pg_constraint AS c
        JOIN pg_class AS r ON r.oid = c.conrelid
        WHERE r.relnamespace = 'public'::regnamespace
          AND c.contype = 'c'
    """)

    constraints = set(postgres_cursor.fetchall())

    expected = {
        ("users", "chk_users_role"),
        ("clients", "chk_clients_distance"),
        ("services", "chk_services_rate"),
        ("trips", "chk_trips_distance"),
        ("visits", "chk_visits_distance"),
        ("visits", "chk_visits_price"),
        ("visits", "chk_visits_time"),
        ("visits", "chk_visits_planned_duration"),
        ("visits", "chk_visits_duration"),
        ("visits", "chk_visits_priority"),
        ("visits", "chk_visits_status"),
        ("visit_trip_legs", "chk_trip_legs_position"),
        ("visit_trip_legs", "chk_trip_legs_distance"),
        ("visit_notes", "chk_notes_content"),
        ("expenses", "chk_expenses_amount"),
    }

    assert constraints == expected


def test_upgrade_from_v008_database(postgres_cursor, migration_database):
    # Build a database as an earlier release would have left it: versions 1–8.
    postgres_migrate.create_migrations_table(postgres_cursor)

    old_migrations = [
        (1, v001_users),
        (2, v002_clients),
        (3, v003_services),
        (4, v004_trips),
        (5, v005_visits),
        (6, v006_visit_notes),
        (7, v007_expenses),
        (8, v008_business_constraints),
    ]

    for version, migration in old_migrations:
        migration.upgrade(postgres_cursor)
        postgres_migrate.record_migration(postgres_cursor, version)

    visit_id = insert_visit(postgres_cursor)

    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS

    postgres_cursor.execute(
        "SELECT status, priority, planned_date, duration_minutes "
        "FROM visits WHERE id = %s",
        (visit_id,),
    )

    # The old visit is kept and the new columns are empty.
    assert postgres_cursor.fetchone() == ("planned", 2, None, None)


def test_run_migrations_creates_foreign_key_indexes(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    postgres_cursor.execute("""
        SELECT tablename, indexname
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname LIKE 'idx_%'
        ORDER BY tablename
    """)

    assert postgres_cursor.fetchall() == [
        ("expenses", "idx_expenses_visit_id"),
        ("trips", "idx_trips_client_id"),
        ("visit_notes", "idx_visit_notes_visit_id"),
        ("visits", "idx_visits_client_id"),
    ]

    # visit_trip_legs.visit_id is already the first column of the unique
    # index, so no copy of it is created.
    postgres_cursor.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'visit_trip_legs' ORDER BY 1"
    )

    assert postgres_cursor.fetchall() == [
        ("uq_trip_legs_visit_position",),
        ("visit_trip_legs_pkey",),
    ]


def test_upgrade_from_v011_database(postgres_cursor, migration_database):
    # Build a database as the previous release left it: versions 1–11.
    postgres_migrate.create_migrations_table(postgres_cursor)

    old_migrations = [
        (1, v001_users),
        (2, v002_clients),
        (3, v003_services),
        (4, v004_trips),
        (5, v005_visits),
        (6, v006_visit_notes),
        (7, v007_expenses),
        (8, v008_business_constraints),
        (9, v009_visit_scheduling),
        (10, v010_visit_constraints),
        (11, v011_visit_trip_legs),
    ]

    for version, migration in old_migrations:
        migration.upgrade(postgres_cursor)
        postgres_migrate.record_migration(postgres_cursor, version)

    visit_id = insert_visit(postgres_cursor)

    # The first run adds only v012, the second run changes nothing.
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS

    postgres_cursor.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'idx_%'")
    assert postgres_cursor.fetchone()[0] == 4

    postgres_cursor.execute("SELECT id FROM visits")
    assert postgres_cursor.fetchall() == [(visit_id,)]


def test_failed_migration_is_rolled_back(postgres_cursor, migration_database, monkeypatch):
    def create_table_then_fail(cursor):
        v011_visit_trip_legs.upgrade(cursor)
        raise RuntimeError("Simulated migration failure")

    original_migrations = postgres_migrate.MIGRATIONS
    failing_migrations = []

    for version, table, upgrade in original_migrations:
        if version == 11:
            upgrade = create_table_then_fail

        failing_migrations.append((version, table, upgrade))

    monkeypatch.setattr(postgres_migrate, "MIGRATIONS", failing_migrations)

    with pytest.raises(RuntimeError, match="Simulated migration failure"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    # Migrations 1–10 were saved. CREATE TABLE of v011 was rolled back
    # together with its version record.
    assert postgres_migrate.get_applied_versions(postgres_cursor) == set(range(1, 11))
    assert not table_exists(postgres_cursor, "visit_trip_legs")

    # The next run completes the migration.
    monkeypatch.setattr(postgres_migrate, "MIGRATIONS", original_migrations)
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS
    assert table_exists(postgres_cursor, "visit_trip_legs")


def test_run_migrations_rejects_unknown_version(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.record_migration(postgres_cursor, 13)

    with pytest.raises(RuntimeError, match="Unknown migration versions"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")


def test_run_migrations_rejects_missing_version(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_cursor.execute("DELETE FROM schema_migrations WHERE version = 5")

    with pytest.raises(RuntimeError, match="missing versions"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")


def test_run_migrations_rejects_table_without_history(postgres_cursor, migration_database):
    # The tables exist, but their versions were never recorded
    v001_users.upgrade(postgres_cursor)
    v002_clients.upgrade(postgres_cursor)

    with pytest.raises(RuntimeError, match="exists without migration history"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")


def test_run_migrations_rejects_missing_table(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_cursor.execute("DROP TABLE visit_trip_legs")

    with pytest.raises(RuntimeError, match="table visit_trip_legs is missing"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")


@pytest.mark.parametrize(
    ("change_sql", "message"),
    [
        (
            "ALTER TABLE clients DROP CONSTRAINT chk_clients_distance",
            "Missing CHECK constraints",
        ),
        (
            "ALTER TABLE clients DROP CONSTRAINT chk_clients_distance; "
            "ALTER TABLE clients ADD CONSTRAINT chk_clients_distance "
            "CHECK (distance_from_home_km >= 0) NOT VALID",
            "Invalid CHECK constraint",
        ),
        (
            "ALTER TABLE expenses ADD CONSTRAINT chk_extra CHECK (amount < 1000)",
            "Unexpected CHECK constraint",
        ),
        (
            "ALTER TABLE visits ALTER COLUMN description TYPE VARCHAR(500)",
            "Invalid columns in table: visits",
        ),
        (
            "DROP INDEX uq_users_email",
            "Invalid indexes in table: users",
        ),
        (
            "DROP INDEX idx_visits_client_id",
            "Invalid indexes in table: visits",
        ),
        (
            "ALTER TABLE expenses DROP CONSTRAINT chk_expenses_amount; "
            "ALTER TABLE expenses ADD CONSTRAINT chk_expenses_amount "
            "CHECK (amount >= -100)",
            "Invalid CHECK constraint: expenses.chk_expenses_amount",
        ),
        (
            "ALTER TABLE visits DROP CONSTRAINT chk_visits_status; "
            "ALTER TABLE visits ADD CONSTRAINT chk_visits_status "
            "CHECK (status IN ('planned', 'completed', 'cancelled', 'deleted'))",
            "Invalid CHECK constraint: visits.chk_visits_status",
        ),
        (
            "ALTER TABLE visits DROP CONSTRAINT chk_visits_time; "
            "ALTER TABLE visits ADD CONSTRAINT chk_visits_time "
            "CHECK (ended_at IS NOT NULL)",
            "Invalid CHECK constraint: visits.chk_visits_time",
        ),
        (
            "ALTER TABLE trips DROP CONSTRAINT trips_client_id_fkey",
            "Invalid foreign keys in table: trips",
        ),
        (
            "ALTER TABLE clients DISABLE TRIGGER trg_clients_updated_at",
            "Invalid triggers in table: clients",
        ),
    ],
)
def test_run_migrations_detects_changed_schema(
    postgres_cursor,
    migration_database,
    change_sql,
    message
):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_cursor.execute(change_sql)

    with pytest.raises(RuntimeError, match=message):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")


def test_run_migrations_requires_public_schema(postgres_cursor, migration_database):
    # New connections to the test database would create tables in "other"
    postgres_cursor.execute("CREATE SCHEMA other")
    postgres_cursor.execute(f'ALTER DATABASE "{migration_database}" SET search_path = other')

    with pytest.raises(RuntimeError, match="Invalid schema for migrations: other"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert not table_exists(postgres_cursor, "schema_migrations")
