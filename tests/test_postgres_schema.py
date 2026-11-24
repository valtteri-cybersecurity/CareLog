from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from tests.postgres_helpers import (
    assert_postgres_error,
    insert_client,
    insert_visit,
    set_actor,
)


def get_visit_client_and_service(cursor, visit_id):
    cursor.execute("SELECT client_id, service_id FROM visits WHERE id = %s", (visit_id,))
    return cursor.fetchone()


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

    # The same email in other letter case is a duplicate
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


def test_default_times_are_utc(migrated_cursor, user_ids):
    cursor = migrated_cursor

    # The defaults use UTC even if a session uses another time zone
    cursor.execute("SET TIME ZONE 'Europe/Helsinki'")
    client_id = insert_client(cursor, user_ids["worker"])

    cursor.execute(
        "SELECT created_at, updated_at FROM clients WHERE id = %s",
        (client_id,)
    )
    created_at, updated_at = cursor.fetchone()

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    assert abs(created_at - now) < timedelta(minutes=1)
    assert updated_at == created_at

    # updated_at of v014 uses the same UTC default
    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) "
        "VALUES ('Kauppa-asiointi', %s) RETURNING updated_at",
        (user_ids["worker"],)
    )

    assert abs(cursor.fetchone()[0] - now) < timedelta(minutes=1)


def test_updated_at_changes_on_update(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]
    old_time = datetime(2020, 1, 1, 12, 0)

    # The trigger runs only on UPDATE, so the old times can be inserted.
    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id, "
        "created_at, updated_at) "
        "VALUES ('Test', 'Client', %s, %s, %s) RETURNING id",
        (worker_id, old_time, old_time)
    )
    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id, updated_at) "
        "VALUES ('Test service', %s, %s) RETURNING id",
        (worker_id, old_time)
    )
    service_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO trips (client_id, start_location, destination, "
        "created_by_user_id, updated_at) "
        "VALUES (%s, 'Koti', 'Kauppa', %s, %s) RETURNING id",
        (client_id, worker_id, old_time)
    )
    trip_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visits (client_id, service_id, user_id, created_by_user_id, "
        "created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (client_id, service_id, worker_id, worker_id, old_time, old_time)
    )
    visit_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO expenses (visit_id, expense_date, amount, category, "
        "user_id, created_by_user_id, updated_at) "
        "VALUES (%s, '2026-11-23', 10, 'customer', %s, %s, %s) RETURNING id",
        (visit_id, worker_id, worker_id, old_time)
    )
    expense_id = cursor.fetchone()[0]

    # Table, row and a column to change. services, trips and expenses
    # have updated_at since v014.
    rows = [
        ("clients", client_id, "city"),
        ("services", service_id, "description"),
        ("trips", trip_id, "destination"),
        ("visits", visit_id, "description"),
        ("expenses", expense_id, "description"),
    ]

    for table, row_id, column in rows:
        # The names are fixed values from the list above
        cursor.execute(
            f"UPDATE {table} SET {column} = 'Muutettu' WHERE id = %s",
            (row_id,)
        )

        cursor.execute(f"SELECT updated_at FROM {table} WHERE id = %s", (row_id,))

        assert cursor.fetchone()[0] > old_time, table

    # created_at does not change
    for table, row_id in (("clients", client_id), ("visits", visit_id)):
        cursor.execute(f"SELECT created_at FROM {table} WHERE id = %s", (row_id,))

        assert cursor.fetchone()[0] == old_time


def test_foreign_keys(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    # Referenced rows must exist
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "INSERT INTO visits (client_id, service_id, user_id, created_by_user_id) "
        "VALUES (%s, %s, %s, %s)",
        (client_id + 1000, service_id, worker_id, worker_id),
    )
    assert_postgres_error(
        cursor, psycopg.errors.ForeignKeyViolation,
        "INSERT INTO expenses (visit_id, expense_date, amount, category, "
        "user_id, created_by_user_id) "
        "VALUES (%s, '2026-11-23', 10, 'customer', %s, %s)",
        (visit_id + 1000, worker_id, worker_id),
    )

    # The history is protected: a client, service or visit that is used
    # elsewhere cannot be deleted.
    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
        "VALUES (%s, 'Muistiinpano', %s)",
        (visit_id, worker_id)
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
    other_client_id = insert_client(cursor, worker_id)
    cursor.execute(
        "INSERT INTO trips (client_id, start_location, destination, created_by_user_id) "
        "VALUES (%s, 'Koti', 'Kauppa', %s)",
        (other_client_id, worker_id)
    )
    cursor.execute("DELETE FROM clients WHERE id = %s", (other_client_id,))
    cursor.execute("SELECT COUNT(*) FROM trips WHERE client_id = %s", (other_client_id,))

    assert cursor.fetchone()[0] == 0


def test_check_constraints_reject_invalid_values(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    # The user columns are given, so only the CHECK constraint can fail
    invalid_values = [
        ("UPDATE clients SET distance_from_home_km = -1 WHERE id = %s", (client_id,)),
        ("UPDATE services SET default_hourly_rate = -1 WHERE id = %s", (service_id,)),
        (
            "INSERT INTO trips (client_id, start_location, destination, distance_km, "
            "created_by_user_id) VALUES (%s, 'Koti', 'Kauppa', -1, %s)",
            (client_id, worker_id),
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
        (
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
            "VALUES (%s, '   ', %s)",
            (visit_id, worker_id),
        ),
        (
            "INSERT INTO expenses (visit_id, expense_date, amount, category, "
            "user_id, created_by_user_id) "
            "VALUES (%s, '2026-11-23', 0, 'customer', %s, %s)",
            (visit_id, worker_id, worker_id),
        ),
        (
            "INSERT INTO visit_trip_legs (visit_id, position, start_location, "
            "destination, created_by_user_id) VALUES (%s, 0, 'Koti', 'Kauppa', %s)",
            (visit_id, worker_id),
        ),
        (
            "INSERT INTO visit_trip_legs "
            "(visit_id, position, start_location, destination, distance_km, "
            "created_by_user_id) VALUES (%s, 1, 'Koti', 'Kauppa', -1, %s)",
            (visit_id, worker_id),
        ),
    ]

    for sql, values in invalid_values:
        assert_postgres_error(cursor, psycopg.errors.CheckViolation, sql, values)


def test_check_constraints_accept_valid_values(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]

    visit_id = insert_visit(cursor, worker_id)

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
        "INSERT INTO visit_trip_legs (visit_id, position, start_location, "
        "destination, created_by_user_id) VALUES (%s, 1, 'Koti', 'Kauppa', %s)",
        (visit_id, worker_id)
    )

    # Two legs of the same visit cannot share a position
    assert_postgres_error(
        cursor, psycopg.errors.UniqueViolation,
        "INSERT INTO visit_trip_legs (visit_id, position, start_location, "
        "destination, created_by_user_id) VALUES (%s, 1, 'Kauppa', 'Koti', %s)",
        (visit_id, worker_id),
    )

    cursor.execute("SELECT status, priority FROM visits WHERE id = %s", (visit_id,))

    assert cursor.fetchone() == ("completed", 3)


def test_visit_priority_and_status_values(migrated_cursor, user_ids):
    cursor = migrated_cursor

    visit_id = insert_visit(cursor, user_ids["worker"])

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
            "INSERT INTO visits (client_id, service_id, priority, status, "
            "user_id, created_by_user_id) "
            "SELECT client_id, service_id, NULL, 'planned', user_id, created_by_user_id "
            "FROM visits WHERE id = %s",
            (visit_id,),
        ),
        (
            "INSERT INTO visits (client_id, service_id, priority, status, "
            "user_id, created_by_user_id) "
            "SELECT client_id, service_id, 2, NULL, user_id, created_by_user_id "
            "FROM visits WHERE id = %s",
            (visit_id,),
        ),
    ]

    for sql, values in invalid_values:
        assert_postgres_error(cursor, psycopg.errors.NotNullViolation, sql, values)


def test_column_limits(migrated_cursor, user_ids):
    cursor = migrated_cursor

    client_id = insert_client(cursor, user_ids["worker"])

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


# USER TRACKING (v014)


def test_user_columns_are_required(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    # Every row needs a creator, and visits and expenses also a worker
    missing_user_sql = [
        ("INSERT INTO clients (first_name, last_name) VALUES ('Test', 'Client')", ()),
        ("INSERT INTO services (name) VALUES ('Test service')", ()),
        (
            "INSERT INTO trips (client_id, start_location, destination) "
            "VALUES (%s, 'Koti', 'Kauppa')",
            (client_id,),
        ),
        (
            "INSERT INTO visits (client_id, service_id, created_by_user_id) "
            "VALUES (%s, %s, %s)",
            (client_id, service_id, worker_id),
        ),
        (
            "INSERT INTO visits (client_id, service_id, user_id) VALUES (%s, %s, %s)",
            (client_id, service_id, worker_id),
        ),
        ("UPDATE visits SET user_id = NULL WHERE id = %s", (visit_id,)),
        (
            "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Muistiinpano')",
            (visit_id,),
        ),
        (
            "INSERT INTO expenses (visit_id, expense_date, amount, category, "
            "created_by_user_id) VALUES (%s, '2026-11-23', 10, 'customer', %s)",
            (visit_id, worker_id),
        ),
        (
            "INSERT INTO expenses (visit_id, expense_date, amount, category, user_id) "
            "VALUES (%s, '2026-11-23', 10, 'customer', %s)",
            (visit_id, worker_id),
        ),
        (
            "INSERT INTO visit_trip_legs (visit_id, position, start_location, destination) "
            "VALUES (%s, 1, 'Koti', 'Kauppa')",
            (visit_id,),
        ),
    ]

    for sql, values in missing_user_sql:
        assert_postgres_error(cursor, psycopg.errors.NotNullViolation, sql, values)

    # A history row must tell who made the change
    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
        "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
        (visit_id, worker_id)
    )
    note_id = cursor.fetchone()[0]

    assert_postgres_error(
        cursor, psycopg.errors.NotNullViolation,
        "INSERT INTO visit_note_history (note_id, old_content, new_content) "
        "VALUES (%s, 'Vanha', 'Uusi')",
        (note_id,),
    )

    # The latest editor is empty until the first change
    cursor.execute("SELECT updated_by_user_id FROM visits WHERE id = %s", (visit_id,))

    assert cursor.fetchone()[0] is None


def test_user_columns_reject_unknown_users(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]
    unknown_user_id = user_ids["admin"] + user_ids["worker"] + 1000

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    # One worker, creator and latest editor column. The schema check of
    # the migrations verifies that every user column has this foreign key.
    invalid_user_sql = [
        ("UPDATE visits SET user_id = %s WHERE id = %s", (unknown_user_id, visit_id)),
        (
            "INSERT INTO clients (first_name, last_name, created_by_user_id) "
            "VALUES ('Test', 'Client', %s)",
            (unknown_user_id,),
        ),
        ("UPDATE clients SET updated_by_user_id = %s WHERE id = %s", (unknown_user_id, client_id)),
    ]

    for sql, values in invalid_user_sql:
        assert_postgres_error(cursor, psycopg.errors.ForeignKeyViolation, sql, values)


def test_user_with_records_cannot_be_deleted(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    # The admin only changed the client last
    cursor.execute(
        "UPDATE clients SET city = 'Tampere', updated_by_user_id = %s WHERE id = %s",
        (admin_id, client_id)
    )

    for user_id in (worker_id, admin_id):
        assert_postgres_error(
            cursor, psycopg.errors.ForeignKeyViolation,
            "DELETE FROM users WHERE id = %s", (user_id,),
        )

    # RESTRICT only protects users with records
    other_worker_id = user_ids["other_worker"]
    cursor.execute("DELETE FROM users WHERE id = %s", (other_worker_id,))
    cursor.execute("SELECT COUNT(*) FROM users WHERE id = %s", (other_worker_id,))

    assert cursor.fetchone()[0] == 0


def test_created_by_cannot_be_changed(migrated_cursor, user_ids):
    cursor = migrated_cursor
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    visit_id = insert_visit(cursor, worker_id)
    client_id, service_id = get_visit_client_and_service(cursor, visit_id)

    cursor.execute(
        "INSERT INTO trips (client_id, start_location, destination, created_by_user_id) "
        "VALUES (%s, 'Koti', 'Kauppa', %s) RETURNING id",
        (client_id, worker_id)
    )
    trip_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
        "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
        (visit_id, worker_id)
    )
    note_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO expenses (visit_id, expense_date, amount, category, "
        "user_id, created_by_user_id) "
        "VALUES (%s, '2026-11-23', 10, 'customer', %s, %s) RETURNING id",
        (visit_id, worker_id, worker_id)
    )
    expense_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visit_trip_legs (visit_id, position, start_location, "
        "destination, created_by_user_id) "
        "VALUES (%s, 1, 'Koti', 'Kauppa', %s) RETURNING id",
        (visit_id, worker_id)
    )
    leg_id = cursor.fetchone()[0]

    rows = [
        ("clients", client_id),
        ("services", service_id),
        ("trips", trip_id),
        ("visits", visit_id),
        ("visit_notes", note_id),
        ("expenses", expense_id),
        ("visit_trip_legs", leg_id),
    ]

    for table, row_id in rows:
        # The trigger stops the change, also when it is made directly in
        # SQL by the owner of the tables. The names are fixed values.
        assert_postgres_error(
            cursor, psycopg.errors.RestrictViolation,
            f"UPDATE {table} SET created_by_user_id = %s WHERE id = %s",
            (admin_id, row_id),
        )

        # Keeping the same value is allowed, so other updates still work
        cursor.execute(
            f"UPDATE {table} SET created_by_user_id = created_by_user_id WHERE id = %s",
            (row_id,)
        )

        cursor.execute(f"SELECT created_by_user_id FROM {table} WHERE id = %s", (row_id,))

        assert cursor.fetchone()[0] == worker_id, table


def test_note_history_saves_editor_of_every_change(migrated_cursor, user_ids):
    cursor = migrated_cursor
    connection = cursor.connection
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    visit_id = insert_visit(cursor, worker_id)
    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
        "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
        (visit_id, worker_id)
    )
    note_id = cursor.fetchone()[0]

    # The same worker edits twice in a row, then the admin. Every change
    # gives its editor in its own transaction.
    edits = [
        (worker_id, "Ensimmäinen muutos"),
        (worker_id, "Toinen muutos"),
        (admin_id, "Kolmas muutos"),
    ]

    for editor_id, content in edits:
        with connection.transaction():
            set_actor(cursor, editor_id)
            cursor.execute(
                "UPDATE visit_notes SET content = %s WHERE id = %s",
                (content, note_id)
            )

    cursor.execute(
        "SELECT old_content, new_content, edited_by_user_id "
        "FROM visit_note_history WHERE note_id = %s ORDER BY id",
        (note_id,)
    )

    assert cursor.fetchall() == [
        ("Muistiinpano", "Ensimmäinen muutos", worker_id),
        ("Ensimmäinen muutos", "Toinen muutos", worker_id),
        ("Toinen muutos", "Kolmas muutos", admin_id),
    ]

    # The note tells its creator and its latest editor, and updated_at
    # is the time of the latest history row.
    cursor.execute(
        "SELECT n.content, n.created_by_user_id, n.updated_by_user_id, "
        "n.updated_at = (SELECT MAX(edited_at) FROM visit_note_history) "
        "FROM visit_notes AS n WHERE n.id = %s",
        (note_id,)
    )

    assert cursor.fetchone() == ("Kolmas muutos", worker_id, admin_id, True)


def test_note_history_requires_editor_for_every_change(migrated_cursor, user_ids):
    cursor = migrated_cursor
    connection = cursor.connection
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    visit_id = insert_visit(cursor, worker_id)
    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
        "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
        (visit_id, worker_id)
    )
    note_id = cursor.fetchone()[0]

    update_sql = "UPDATE visit_notes SET content = %s WHERE id = %s"

    # No editor at all
    with pytest.raises(psycopg.errors.NotNullViolation):
        cursor.execute(update_sql, ("Muutos", note_id))

    # An editor given in an earlier transaction is gone
    with connection.transaction():
        set_actor(cursor, worker_id)

    with pytest.raises(psycopg.errors.NotNullViolation):
        cursor.execute(update_sql, ("Muutos", note_id))

    # An editor is used only once, also inside one transaction
    with pytest.raises(psycopg.errors.NotNullViolation):
        with connection.transaction():
            set_actor(cursor, worker_id)
            cursor.execute(update_sql, ("Muutos 1", note_id))
            cursor.execute(update_sql, ("Muutos 2", note_id))

    # The editor must be a real user
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with connection.transaction():
            set_actor(cursor, worker_id + admin_id + 1000)
            cursor.execute(update_sql, ("Muutos", note_id))

    # Every failed change was rolled back as a whole
    cursor.execute(
        "SELECT content, updated_by_user_id FROM visit_notes WHERE id = %s",
        (note_id,)
    )
    assert cursor.fetchone() == ("Muistiinpano", None)

    cursor.execute("SELECT COUNT(*) FROM visit_note_history")
    assert cursor.fetchone()[0] == 0

    # Without a change of content no editor is needed, and the latest
    # editor cannot be changed alone.
    cursor.execute(
        "UPDATE visit_notes SET content = content, updated_by_user_id = %s WHERE id = %s",
        (admin_id, note_id)
    )
    cursor.execute("SELECT updated_by_user_id FROM visit_notes WHERE id = %s", (note_id,))

    assert cursor.fetchone()[0] is None
