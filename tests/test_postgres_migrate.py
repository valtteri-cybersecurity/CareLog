from datetime import datetime

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
    v012_foreign_key_indexes,
)
from tests.postgres_helpers import (
    get_columns,
    insert_client,
    insert_service,
    insert_user,
    insert_visit,
    table_exists,
)


EXPECTED_VERSIONS = set(range(1, 15))

# The versions before user tracking (v014)
VERSIONS_UNTIL_V013 = set(range(1, 14))


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


def use_migrations_until(monkeypatch, last_version):
    # The runner knows only the migrations up to last_version, as an
    # earlier release did. v014 refuses rows without a known creator, so
    # the upgrade tests of old databases with rows stop at v013.
    migrations = []

    for version, table, upgrade in postgres_migrate.MIGRATIONS:
        if version <= last_version:
            migrations.append((version, table, upgrade))

    monkeypatch.setattr(postgres_migrate, "MIGRATIONS", migrations)


def build_database_until(cursor, last_version):
    # A database as an earlier release left it: the migrations up to
    # last_version and their version records.
    postgres_migrate.create_migrations_table(cursor)

    for version, table, upgrade in postgres_migrate.MIGRATIONS:
        if version <= last_version:
            upgrade(cursor)
            postgres_migrate.record_migration(cursor, version)


def function_exists(cursor, name):
    cursor.execute("SELECT COUNT(*) FROM pg_proc WHERE proname = %s", (name,))
    return cursor.fetchone()[0] == 1


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
        "visit_note_history",
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

    # User tracking of v014: the worker and the creator are required, the
    # latest editor is empty until the first change.
    assert ("created_by_user_id", "integer", "NO", None) in clients
    assert ("updated_by_user_id", "integer", "YES", None) in clients
    assert ("user_id", "integer", "NO", None) in visits
    assert ("user_id", "integer", "NO", None) in expenses
    assert (
        "updated_at",
        "timestamp without time zone",
        "NO",
        "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'::text)",
    ) in services

    for column in visits:
        assert column[0] != "assigned_user_id"

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


def test_upgrade_from_v008_database(postgres_cursor, migration_database, monkeypatch):
    # The old rows have no creator, so this upgrade stops at v013
    use_migrations_until(monkeypatch, 13)

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

    assert postgres_migrate.get_applied_versions(postgres_cursor) == VERSIONS_UNTIL_V013

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
        ORDER BY tablename, indexname
    """)

    # ORDER BY both columns keeps the order of a table's indexes stable
    assert postgres_cursor.fetchall() == [
        ("expenses", "idx_expenses_user_id"),
        ("expenses", "idx_expenses_visit_id"),
        ("trips", "idx_trips_client_id"),
        ("visit_note_history", "idx_visit_note_history_note_id"),
        ("visit_notes", "idx_visit_notes_visit_id"),
        ("visits", "idx_visits_client_id"),
        ("visits", "idx_visits_user_id"),
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


def test_upgrade_from_v011_database(postgres_cursor, migration_database, monkeypatch):
    # The old rows have no creator, so this upgrade stops at v013
    use_migrations_until(monkeypatch, 13)

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

    # The first run adds v012 and v013, the second run changes nothing.
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == VERSIONS_UNTIL_V013

    postgres_cursor.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname LIKE 'idx_%'")
    assert postgres_cursor.fetchone()[0] == 5

    postgres_cursor.execute("SELECT id FROM visits")
    assert postgres_cursor.fetchall() == [(visit_id,)]


def test_upgrade_from_v012_database(postgres_cursor, migration_database, monkeypatch):
    # The old rows have no creator, so this upgrade stops at v013
    use_migrations_until(monkeypatch, 13)

    # Build a database as the previous release left it: versions 1–12.
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
        (12, v012_foreign_key_indexes),
    ]

    for version, migration in old_migrations:
        migration.upgrade(postgres_cursor)
        postgres_migrate.record_migration(postgres_cursor, version)

    # The v012 schema has no updated_at in visit_notes, and the check
    # does not ask for it before v013.
    postgres_migrate.validate_schema(postgres_cursor, set(range(1, 13)))

    visit_id = insert_visit(postgres_cursor)
    postgres_cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_at) "
        "VALUES (%s, 'Vanha muistiinpano', '2026-11-18 09:00') RETURNING id",
        (visit_id,),
    )
    note_id = postgres_cursor.fetchone()[0]

    # The first run adds only v013, the second run changes nothing.
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == VERSIONS_UNTIL_V013

    # The old note is kept, and it is not marked as edited
    postgres_cursor.execute(
        "SELECT content, created_at, updated_at FROM visit_notes WHERE id = %s",
        (note_id,),
    )
    assert postgres_cursor.fetchone() == (
        "Vanha muistiinpano",
        datetime(2026, 11, 18, 9, 0),
        datetime(2026, 11, 18, 9, 0),
    )

    postgres_cursor.execute("SELECT COUNT(*) FROM visit_note_history")
    assert postgres_cursor.fetchone()[0] == 0

    # A new note gets updated_at from the default value
    postgres_cursor.execute(
        "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Uusi') "
        "RETURNING created_at = updated_at",
        (visit_id,),
    )
    assert postgres_cursor.fetchone()[0] is True


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


def test_upgrade_from_v013_database(postgres_cursor, migration_database):
    build_database_until(postgres_cursor, 13)

    # The check accepts the v013 schema before the upgrade
    postgres_migrate.validate_schema(postgres_cursor, VERSIONS_UNTIL_V013)

    # Users may exist already. v014 does not change the users table.
    user_id = insert_user(postgres_cursor)

    # The first run adds only v014, the second run changes nothing.
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS
    postgres_migrate.validate_schema(postgres_cursor, EXPECTED_VERSIONS)

    # A new visit has a worker and a creator, and no editor yet
    visit_id = insert_visit(postgres_cursor, user_id)

    postgres_cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM visits WHERE id = %s",
        (visit_id,),
    )

    assert postgres_cursor.fetchone() == (user_id, user_id, None)


def test_v014_stops_when_records_have_unknown_creator(postgres_cursor, migration_database):
    build_database_until(postgres_cursor, 13)

    # Development data from before user tracking. A user exists, but the
    # old rows are never linked to it automatically.
    user_id = insert_user(postgres_cursor)
    client_id = insert_client(postgres_cursor)
    service_id = insert_service(postgres_cursor)

    with pytest.raises(RuntimeError, match="creator is unknown: clients, services"):
        postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    # Nothing of v014 was saved, and the v013 schema is still valid
    assert postgres_migrate.get_applied_versions(postgres_cursor) == VERSIONS_UNTIL_V013
    postgres_migrate.validate_schema(postgres_cursor, VERSIONS_UNTIL_V013)

    for column in get_columns(postgres_cursor, "clients"):
        assert column[0] != "created_by_user_id"

    assert not function_exists(postgres_cursor, "prevent_created_by_change")

    # The old rows were kept, and no user was created or linked
    postgres_cursor.execute("SELECT id FROM clients")
    assert postgres_cursor.fetchall() == [(client_id,)]

    postgres_cursor.execute("SELECT id FROM services")
    assert postgres_cursor.fetchall() == [(service_id,)]

    postgres_cursor.execute("SELECT id FROM users")
    assert postgres_cursor.fetchall() == [(user_id,)]

    # When the administrator has removed the development data, the
    # migration can be run again.
    postgres_cursor.execute("DELETE FROM services")
    postgres_cursor.execute("DELETE FROM clients")

    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")

    assert postgres_migrate.get_applied_versions(postgres_cursor) == EXPECTED_VERSIONS


def test_run_migrations_rejects_unknown_version(postgres_cursor, migration_database):
    postgres_migrate.run_postgres_migrations(migration_database, password="test-only")
    postgres_migrate.record_migration(postgres_cursor, 15)

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
        (
            "ALTER TABLE visit_notes DISABLE TRIGGER trg_visit_notes_history",
            "Invalid triggers in table: visit_notes",
        ),
        (
            "ALTER TABLE visit_notes ALTER COLUMN updated_at DROP NOT NULL",
            "Invalid columns in table: visit_notes",
        ),
        (
            "ALTER FUNCTION save_visit_note_history() SECURITY INVOKER",
            "Invalid function settings: save_visit_note_history",
        ),
        (
            "ALTER FUNCTION save_visit_note_history() RESET search_path",
            "Invalid function settings: save_visit_note_history",
        ),
        (
            "ALTER FUNCTION save_visit_note_history() SET search_path = public",
            "Invalid function settings: save_visit_note_history",
        ),
        (
            "GRANT EXECUTE ON FUNCTION save_visit_note_history() TO PUBLIC",
            "Invalid function privileges: save_visit_note_history",
        ),
        # User tracking of v014
        (
            "ALTER TABLE visits ALTER COLUMN user_id DROP NOT NULL",
            "Invalid columns in table: visits",
        ),
        (
            "ALTER TABLE visit_note_history ALTER COLUMN edited_by_user_id DROP NOT NULL",
            "Invalid columns in table: visit_note_history",
        ),
        (
            "ALTER TABLE expenses DROP CONSTRAINT expenses_user_id_fkey",
            "Invalid foreign keys in table: expenses",
        ),
        (
            "DROP INDEX idx_expenses_user_id",
            "Invalid indexes in table: expenses",
        ),
        (
            "ALTER TABLE services DISABLE TRIGGER trg_services_updated_at",
            "Invalid triggers in table: services",
        ),
        (
            "ALTER TABLE clients DISABLE TRIGGER trg_clients_created_by",
            "Invalid triggers in table: clients",
        ),
        (
            "DROP TRIGGER trg_visit_trip_legs_created_by ON visit_trip_legs",
            "Invalid triggers in table: visit_trip_legs",
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
