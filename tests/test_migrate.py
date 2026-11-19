import pytest

from carelog.database import migrate
from carelog.database.migrations import v001_users
from tests.migration_helpers import get_columns, table_exists


EXPECTED_VERSIONS = set(range(1, 9))


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
    expenses = get_columns(cursor, "expenses")

    assert ("street_address", "varchar(255)", "YES", None) in clients
    assert ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP") in clients

    assert ("description", "text", "YES", None) in services
    assert ("default_hourly_rate", "decimal(10,2)", "YES", None) in services

    assert ("distance_km", "decimal(10,2)", "YES", None) in trips
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
    # but before the migration was recorded.
    cursor.execute("DELETE FROM schema_migrations WHERE version = 8")
    cursor.execute("ALTER TABLE clients DROP CHECK chk_clients_distance")

