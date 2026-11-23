from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from carelog.database import postgres_migrate
from tests.postgres_helpers import (
    assert_postgres_error,
    insert_client,
    insert_service,
    insert_visit,
)


@pytest.fixture
def migrated_cursor(postgres_cursor):
    # All PostgreSQL migrations in order, as run_postgres_migrations()
    # runs them, but without a separate migration connection.
    for version, table, upgrade in postgres_migrate.MIGRATIONS:
        upgrade(postgres_cursor)

    return postgres_cursor


def test_users_constraints(migrated_cursor):
    cursor = migrated_cursor

    cursor.execute(
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('worker@example.com', 'Worker', 'test-hash') "
        "RETURNING id, role, is_active"
    )
    user_id, role, is_active = cursor.fetchone()

    assert user_id > 0
    assert role == "worker"
    assert is_active is True

    # The same email in other letter case is a duplicate, as in MySQL
    assert_postgres_error(
        cursor, psycopg.errors.UniqueViolation,
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('Worker@Example.com', 'Other', 'test-hash')",
    )

    # The role must be admin or worker
    assert_postgres_error(
        cursor, psycopg.errors.CheckViolation,
        "INSERT INTO users (email, display_name, password_hash, role) "
        "VALUES ('other@example.com', 'Other', 'test-hash', 'unknown')",
    )


def test_default_times_are_utc(migrated_cursor):
    cursor = migrated_cursor

    # The defaults use UTC even if a session uses another time zone
    cursor.execute("SET TIME ZONE 'Europe/Helsinki'")
    client_id = insert_client(cursor)

    cursor.execute(
        "SELECT created_at, updated_at FROM clients WHERE id = %s",
        (client_id,)
    )
    created_at, updated_at = cursor.fetchone()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    assert abs(created_at - now) < timedelta(minutes=1)
    assert updated_at == created_at


def test_updated_at_changes_on_update(migrated_cursor):
    cursor = migrated_cursor
    old_time = datetime(2020, 1, 1, 12, 0)

    # The trigger runs only on UPDATE, so the old times can be inserted.
    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_at, updated_at) "
        "VALUES ('Test', 'Client', %s, %s) RETURNING id",
        (old_time, old_time)
    )
    client_id = cursor.fetchone()[0]

    service_id = insert_service(cursor)

    cursor.execute(
        "INSERT INTO visits (client_id, service_id, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (client_id, service_id, old_time, old_time)
    )
    visit_id = cursor.fetchone()[0]

    # Table, row and a column to change
    rows = [
        ("clients", client_id, "city"),
        ("visits", visit_id, "description"),
    ]

    for table, row_id, column in rows:
        # The names are fixed values from the list above
        cursor.execute(
            f"UPDATE {table} SET {column} = 'Muutettu' WHERE id = %s",
            (row_id,)
        )

        cursor.execute(
            f"SELECT created_at, updated_at FROM {table} WHERE id = %s",
            (row_id,)
        )
        created_at, updated_at = cursor.fetchone()

        assert created_at == old_time
        assert updated_at > old_time


def test_foreign_keys(migrated_cursor):
    cursor = migrated_cursor

    visit_id = insert_visit(cursor)

    cursor.execute("SELECT client_id, service_id FROM visits WHERE id = %s", (visit_id,))
    client_id, service_id = cursor.fetchone()

    # Referenced rows must exist
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "INSERT INTO visits (client_id, service_id) VALUES (%s, %s)",
        (client_id + 1000, service_id),
    )
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "INSERT INTO expenses (visit_id, expense_date, amount, category) "
        "VALUES (%s, '2026-11-23', 10, 'customer')",
        (visit_id + 1000,),
    )

    # The history is protected: a client, service or visit that is used
    # elsewhere cannot be deleted.
    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Muistiinpano')",
        (visit_id,)
    )

    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "DELETE FROM visits WHERE id = %s", (visit_id,),
    )
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "DELETE FROM clients WHERE id = %s", (client_id,),
    )
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "DELETE FROM services WHERE id = %s", (service_id,),
    )

    # Saved trips are removed together with their client
    other_client_id = insert_client(cursor)
    cursor.execute(
        "INSERT INTO trips (client_id, start_location, destination) "
        "VALUES (%s, 'Koti', 'Kauppa')",
        (other_client_id,)
    )
    cursor.execute("DELETE FROM clients WHERE id = %s", (other_client_id,))
    cursor.execute("SELECT COUNT(*) FROM trips WHERE client_id = %s", (other_client_id,))

    assert cursor.fetchone()[0] == 0


def test_check_constraints_reject_invalid_values(migrated_cursor):
    cursor = migrated_cursor

    client_id = insert_client(cursor)
    service_id = insert_service(cursor)
    visit_id = insert_visit(cursor)

    invalid_values = [
        ("UPDATE clients SET distance_from_home_km = -1 WHERE id = %s", (client_id,)),
        ("UPDATE services SET default_hourly_rate = -1 WHERE id = %s", (service_id,)),
        (
            "INSERT INTO trips (client_id, start_location, destination, distance_km) "
            "VALUES (%s, 'Koti', 'Kauppa', -1)",
            (client_id,),
        ),
        ("UPDATE visits SET distance_km = -1 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET price = -1 WHERE id = %s", (visit_id,)),
        (
            "UPDATE visits SET started_at = '2026-11-23 10:00', "
            "ended_at = '2026-11-23 09:00' WHERE id = %s",
            (visit_id,),
        ),
        ("UPDATE visits SET planned_duration_minutes = 0 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET duration_minutes = 0 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET priority = 0 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET priority = 4 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET priority = -1 WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET status = 'unknown' WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET status = 'pending' WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET status = 'archived' WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET status = '' WHERE id = %s", (visit_id,)),
        ("INSERT INTO visit_notes (visit_id, content) VALUES (%s, '   ')", (visit_id,)),
        (
            "INSERT INTO expenses (visit_id, expense_date, amount, category) "
            "VALUES (%s, '2026-11-23', 0, 'customer')",
            (visit_id,),
        ),
        (
            "INSERT INTO visit_trip_legs (visit_id, position, start_location, destination) "
            "VALUES (%s, 0, 'Koti', 'Kauppa')",
            (visit_id,),
        ),
        (
            "INSERT INTO visit_trip_legs "
            "(visit_id, position, start_location, destination, distance_km) "
            "VALUES (%s, 1, 'Koti', 'Kauppa', -1)",
            (visit_id,),
        ),
    ]

    for sql, values in invalid_values:
        assert_postgres_error(cursor, psycopg.errors.CheckViolation, sql, values)


def test_check_constraints_accept_valid_values(migrated_cursor):
    cursor = migrated_cursor

    visit_id = insert_visit(cursor)

    # NULL passes a CHECK constraint, and the limits themselves are valid
    cursor.execute(
        """
        UPDATE visits
        SET distance_km = 0,
            price = 0,
            started_at = '2026-11-23 10:00',
            ended_at = '2026-11-23 10:00',
            planned_duration_minutes = NULL,
            duration_minutes = 1,
            priority = 3,
            status = 'completed'
        WHERE id = %s
        """,
        (visit_id,)
    )

    cursor.execute(
        "INSERT INTO visit_trip_legs (visit_id, position, start_location, destination) "
        "VALUES (%s, 1, 'Koti', 'Kauppa')",
        (visit_id,)
    )

    # Two legs of the same visit cannot share a position
    assert_postgres_error(
        cursor, psycopg.errors.UniqueViolation,
        "INSERT INTO visit_trip_legs (visit_id, position, start_location, destination) "
        "VALUES (%s, 1, 'Kauppa', 'Koti')",
        (visit_id,),
    )

    cursor.execute("SELECT status, priority FROM visits WHERE id = %s", (visit_id,))

    assert cursor.fetchone() == ("completed", 3)


def test_visit_priority_and_status_values(migrated_cursor):
    cursor = migrated_cursor

    visit_id = insert_visit(cursor)

    # Every allowed value is accepted
    for priority in (1, 2, 3):
        cursor.execute("UPDATE visits SET priority = %s WHERE id = %s", (priority, visit_id))

    for status in ("planned", "completed", "cancelled"):
        cursor.execute("UPDATE visits SET status = %s WHERE id = %s", (status, visit_id))

    # NULL passes a CHECK constraint, so NOT NULL is needed as well
    invalid_values = [
        ("UPDATE visits SET priority = NULL WHERE id = %s", (visit_id,)),
        ("UPDATE visits SET status = NULL WHERE id = %s", (visit_id,)),
        (
            "INSERT INTO visits (client_id, service_id, priority, status) "
            "SELECT client_id, service_id, NULL, 'planned' FROM visits WHERE id = %s",
            (visit_id,),
        ),
        (
            "INSERT INTO visits (client_id, service_id, priority, status) "
            "SELECT client_id, service_id, 2, NULL FROM visits WHERE id = %s",
            (visit_id,),
        ),
    ]

    for sql, values in invalid_values:
        assert_postgres_error(cursor, psycopg.errors.NotNullViolation, sql, values)


def test_column_limits(migrated_cursor):
    cursor = migrated_cursor

    client_id = insert_client(cursor)

    # The largest DECIMAL(10,2) value fits, a larger one does not
    cursor.execute(
        "UPDATE clients SET distance_from_home_km = 99999999.99 WHERE id = %s",
        (client_id,)
    )

    assert_postgres_error(
        cursor, psycopg.errors.NumericValueOutOfRange,
        "UPDATE clients SET distance_from_home_km = 100000000.00 WHERE id = %s",
        (client_id,),
    )

    # Too long text is rejected, not cut
    assert_postgres_error(
        cursor, psycopg.errors.StringDataRightTruncation,
        "UPDATE clients SET first_name = %s WHERE id = %s",
        ("A" * 101, client_id),
    )
