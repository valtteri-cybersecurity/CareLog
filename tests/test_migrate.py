import pytest

from carelog.database import migrate
from carelog.database.migrations import (
    v001_users,
    v002_clients,
    v003_services,
    v004_trips,
    v005_visits,
    v006_visit_notes,
    v007_expenses,
    v008_business_constraints,
)
from tests.migration_helpers import get_columns, insert_visit, table_exists


EXPECTED_VERSIONS = set(range(1, 11))


@pytest.fixture
def migration_database(cursor, connect_to_test_mysql, monkeypatch):
    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection(database=None, user=None, password=None):
        assert user == "carelog_migrator"
        assert password == "test-only"
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(migrate, "get_connection", get_test_connection)

    return database


def test_run_migrations_creates_tables(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    tables = [
        "users",
        "clients",
        "services",
        "trips",
        "visits",
        "visit_notes",
        "expenses",
        "schema_migrations",
    ]

    for table in tables:
        assert table_exists(cursor, table)


def test_run_migrations_records_versions(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS


def test_run_migrations_can_be_run_twice(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")
    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS


def test_run_migrations_creates_correct_columns(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    clients = get_columns(cursor, "clients")
    services = get_columns(cursor, "services")
    trips = get_columns(cursor, "trips")
    visits = get_columns(cursor, "visits")
    expenses = get_columns(cursor, "expenses")

    assert ("street_address", "varchar(255)", "YES", None) in clients
    assert ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP") in clients

    assert ("description", "text", "YES", None) in services
    assert ("default_hourly_rate", "decimal(10,2)", "YES", None) in services

    assert ("distance_km", "decimal(10,2)", "YES", None) in trips
    assert ("planned_date", "date", "YES", None) in visits
    assert ("duration_minutes", "int", "YES", None) in visits
    assert ("description", "varchar(255)", "YES", None) in expenses

    for column in clients:
        assert column[0] != "personal_identity_code"
        assert column[0] != "street_adress"


def test_run_migrations_creates_business_constraints(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    cursor.execute("""
        SELECT TABLE_NAME, CONSTRAINT_NAME, ENFORCED
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
          AND CONSTRAINT_TYPE = 'CHECK'
    """)

    constraints = set(cursor.fetchall())

    expected = {
        ("clients", "chk_clients_distance", "YES"),
        ("services", "chk_services_rate", "YES"),
        ("trips", "chk_trips_distance", "YES"),
        ("visits", "chk_visits_distance", "YES"),
        ("visits", "chk_visits_price", "YES"),
        ("visits", "chk_visits_time", "YES"),
        ("visits", "chk_visits_planned_duration", "YES"),
        ("visits", "chk_visits_duration", "YES"),
        ("visits", "chk_visits_priority", "YES"),
        ("visits", "chk_visits_status", "YES"),
        ("visit_notes", "chk_notes_content", "YES"),
        ("expenses", "chk_expenses_amount", "YES"),
    }

    assert constraints == expected


def test_interrupted_migration_recovers(cursor, migration_database):
    migrate.create_migrations_table(cursor)
    v001_users.upgrade(cursor)

    cursor.execute(
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('test@example.com', 'Test', 'test-hash')"
    )

    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS

    cursor.execute("SELECT email FROM users")
    assert cursor.fetchone() == ("test@example.com",)


def test_interrupted_business_migration_recovers(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    # Simulate a crash after some v008 ALTER TABLE operations succeeded,
    # but before the migration was recorded. Later versions cannot be
    # recorded without version 8.
    cursor.execute("DELETE FROM schema_migrations WHERE version >= 8")
    cursor.execute("ALTER TABLE clients DROP CHECK chk_clients_distance")

    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS
    migrate.validate_business_constraints(cursor, require_v010=True)


def test_upgrade_from_v008_database(cursor, migration_database):
    # Build a database as the previous release left it: versions 1–8.
    migrate.create_migrations_table(cursor)

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
        migration.upgrade(cursor)
        migrate.record_migration(cursor, version)

    visit_id = insert_visit(cursor)

    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS
    migrate.validate_business_constraints(cursor, require_v010=True)

    cursor.execute(
        "SELECT status, priority, planned_date, duration_minutes "
        "FROM visits WHERE id = %s",
        (visit_id,),
    )

    # The old visit is kept and the new columns are empty.
    assert cursor.fetchone() == ("planned", 2, None, None)


def test_interrupted_v009_migration_recovers(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    # Simulate a crash after the v009 ALTER TABLE succeeded, but before
    # version 9 was recorded and before v010 was run.
    cursor.execute("DELETE FROM schema_migrations WHERE version >= 9")

    v010_checks = [
        "chk_visits_planned_duration",
        "chk_visits_duration",
        "chk_visits_priority",
        "chk_visits_status",
    ]

    for name in v010_checks:
        cursor.execute(f"ALTER TABLE visits DROP CHECK {name}")

    # Adding the same columns again would fail, so this also proves
    # that v009 is not applied twice.
    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS
    assert len(get_columns(cursor, "visits")) == 18
    migrate.validate_business_constraints(cursor, require_v010=True)


def test_interrupted_v010_migration_recovers(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    # Simulate a crash after some v010 constraints were added.
    cursor.execute("DELETE FROM schema_migrations WHERE version = 10")
    cursor.execute("ALTER TABLE visits DROP CHECK chk_visits_status")

    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == EXPECTED_VERSIONS
    migrate.validate_business_constraints(cursor, require_v010=True)


def test_run_migrations_rejects_unknown_version(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")
    migrate.record_migration(cursor, 11)

    with pytest.raises(RuntimeError, match="Unknown migration versions"):
        migrate.run_migrations(migration_database, password="test-only")

