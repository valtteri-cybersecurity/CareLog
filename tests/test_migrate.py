from datetime import date

import pytest

from carelog.database import migrate
from tests.migration_helpers import get_columns


@pytest.fixture
def migration_database(cursor, connect_to_test_mysql, monkeypatch):
    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection(database=None, user=None, password=None):
        assert user == "carelog_migrator"
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(migrate, "get_connection", get_test_connection)
    return database


@pytest.mark.parametrize(
    ("table", "create_table"),
    [
        ("visits", "CREATE TABLE visits (id INT PRIMARY KEY, event_date DATE NOT NULL)"),
        ("entries", "CREATE TABLE entries (id INT PRIMARY KEY)"),
        ("tasks", "CREATE TABLE tasks (id INT PRIMARY KEY)"),
    ],
)
def test_run_migrations_stops_before_writing(cursor, migration_database, table, create_table):
    cursor.execute(create_table)

    with pytest.raises(RuntimeError, match=f"Legacy CareLog tables found: {table}"):
        migrate.run_migrations(migration_database, password="test-only")

    cursor.execute("SHOW TABLES")
    assert cursor.fetchall() == ((table,),)


def test_run_migrations_stops_with_existing_history(cursor, migration_database):
    cursor.execute("CREATE TABLE visits (id INT PRIMARY KEY, event_date DATE NOT NULL)")
    cursor.execute("INSERT INTO visits VALUES (1, '2026-01-01')")
    migrate.create_migrations_table(cursor)
    for version in (1, 2, 3, 4):
        migrate.record_migration(cursor, version)

    with pytest.raises(RuntimeError, match="Legacy CareLog tables found: visits"):
        migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4}
    cursor.execute("SELECT id, event_date FROM visits")
    assert cursor.fetchall() == ((1, date(2026, 1, 1)),)


def test_run_migrations_can_be_run_twice(cursor, migration_database):
    migrate.run_migrations(migration_database, password="test-only")
    migrate.run_migrations(migration_database, password="test-only")

    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12}
    assert ("street_address", "varchar(255)", "YES", None) in get_columns(cursor, "clients")
    assert "personal_identity_code" not in [column[0] for column in get_columns(cursor, "clients")]
    assert ("default_hourly_rate", "decimal(10,2)", "YES", None) in get_columns(
        cursor, "services"
    )
    assert ("description", "varchar(255)", "YES", None) in get_columns(cursor, "expenses")
