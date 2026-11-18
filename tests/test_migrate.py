import pytest

from carelog.database import migrate
from carelog.database.migrations import v001_users
from tests.migration_helpers import get_columns, table_exists


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

    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4, 5, 6, 7}


def test_run_migrations_can_be_run_twice(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")
    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4, 5, 6, 7}


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


def test_interrupted_migration_recovers(cursor, migration_database):
    migrate.create_migrations_table(cursor)
    v001_users.upgrade(cursor)

    cursor.execute(
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('test@example.com', 'Test', 'test-hash')"
    )

    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4, 5, 6, 7}

    cursor.execute("SELECT email FROM users")
    assert cursor.fetchone() == ("test@example.com",)


def test_invalid_interrupted_migration_fails(cursor, migration_database):
    migrate.create_migrations_table(cursor)
    v001_users.upgrade(cursor)

    cursor.execute(
        "ALTER TABLE users MODIFY email VARCHAR(100) NOT NULL"
    )

    with pytest.raises(RuntimeError, match="Invalid columns"):
        migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == set()


def test_unknown_migration_version_fails(cursor, migration_database):
    migrate.create_migrations_table(cursor)

    cursor.execute(
        "INSERT INTO schema_migrations (version) VALUES (999)"
    )

    with pytest.raises(RuntimeError, match="Unknown migration versions"):
        migrate.run_migrations(migration_database, password="test-only")

    assert not table_exists(cursor, "users")


def test_changed_table_structure_fails(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    cursor.execute(
        "ALTER TABLE services "
        "MODIFY default_hourly_rate DECIMAL(12, 2) NULL"
    )

    with pytest.raises(RuntimeError, match="Invalid columns"):
        migrate.run_migrations(migration_database, password="test-only")


def test_missing_unique_constraint_fails(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    cursor.execute("ALTER TABLE users DROP INDEX email")

    with pytest.raises(RuntimeError, match="Invalid unique constraints"):
        migrate.run_migrations(migration_database, password="test-only")


def test_missing_recorded_table_fails(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")

    cursor.execute("DROP TABLE expenses")

    with pytest.raises(RuntimeError, match="recorded but table"):
        migrate.run_migrations(migration_database, password="test-only")

