from datetime import date
from decimal import Decimal
from secrets import token_hex

import psycopg
import pytest
from psycopg import sql

from carelog.database import postgres_migrate, postgres_permissions
from carelog.services.clients import add_client, archive_client, update_client
from carelog.services.expenses import add_expense, update_expense
from carelog.services.services import add_service, update_service
from carelog.services.trips import add_trip, delete_trip, update_trip
from carelog.services.user_validation import get_active_user
from carelog.services.visit_notes import (
    add_visit_note,
    get_visit_note_history,
    update_visit_note,
)
from carelog.services.visit_trips import save_visit_trip
from carelog.services.visits import (
    add_planned_visit,
    cancel_visit,
    change_visit_worker,
    complete_visit,
)
from tests.postgres_helpers import (
    assert_postgres_error,
    insert_test_users,
    insert_visit,
    set_actor,
)


# The newest migration version
LATEST_VERSION = postgres_migrate.MIGRATIONS[-1][0]
ALL_VERSIONS = set(range(1, LATEST_VERSION + 1))


# The service modules that are run with the application account
SERVICE_MODULES = (
    "carelog.services.clients",
    "carelog.services.expenses",
    "carelog.services.services",
    "carelog.services.trips",
    "carelog.services.visit_notes",
    "carelog.services.visit_trips",
    "carelog.services.visits",
)


# Default privileges on new tables and sequences, as found in an earlier
# local installation: carelog_app=arwd for tables and U for sequences.
SCHEMA_DEFAULT_PRIVILEGES = [
    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}",
    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
    "GRANT USAGE ON SEQUENCES TO {}",
]

GLOBAL_DEFAULT_PRIVILEGES = [
    "ALTER DEFAULT PRIVILEGES FOR ROLE {} "
    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}",
    "ALTER DEFAULT PRIVILEGES FOR ROLE {} "
    "GRANT USAGE ON SEQUENCES TO {}",
]


def get_table_owner(cursor):
    # The test user creates the tables here, as carelog_migrator does in
    # a real installation.
    cursor.execute("SELECT current_user")
    return cursor.fetchone()[0]


@pytest.fixture
def app_database(migrated_cursor, connect_to_test_postgres):
    # A temporary login account in the role of carelog_app, in a test
    # database with the full current schema. Accounts are shared by the
    # whole server, so the name is random and the account is removed
    # after the test. Use only a disposable test server.
    postgres_cursor = migrated_cursor
    app_user = f"carelog_test_app_{token_hex(8)}"
    app_password = token_hex(16)

    postgres_cursor.execute("SELECT current_database()")
    database = postgres_cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    admin_connection = connect_to_test_postgres(autocommit=True)

    with admin_connection:
        admin_connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(app_user),
                sql.Literal(app_password),
            )
        )

        try:
            def connect_as_app():
                return connect_to_test_postgres(
                    database=database,
                    user=app_user,
                    password=app_password,
                )

            yield postgres_cursor, app_user, connect_as_app

        finally:
            # The privileges must be removed before the account can be dropped
            user = sql.Identifier(app_user)
            owner = sql.Identifier(get_table_owner(postgres_cursor))
            postgres_cursor.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(user)
            )
            postgres_cursor.execute(
                sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(user)
            )

            default_privileges = [
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON TABLES FROM {}",
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "REVOKE ALL ON SEQUENCES FROM {}",
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE ALL ON TABLES FROM {}",
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} REVOKE ALL ON SEQUENCES FROM {}",
            ]

            for query in default_privileges:
                postgres_cursor.execute(sql.SQL(query).format(owner, user))
            postgres_cursor.execute(
                sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(user)
            )
            admin_connection.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(user)
            )


@pytest.fixture
def app_users(app_database):
    # Test users of the temporary test database. The application account
    # cannot add users, so the owner of the tables adds them.
    cursor, app_user, connect_as_app = app_database

    return insert_test_users(cursor)


def test_grant_app_permissions_passes_check(app_database):
    cursor, app_user, connect_as_app = app_database

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))
    postgres_permissions.check_app_permissions(cursor, app_user)

    # The table privileges are exactly the listed ones
    for table in postgres_permissions.APP_TABLE_PRIVILEGES:
        for privilege in postgres_permissions.TABLE_PRIVILEGES:
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (app_user, table, privilege)
            )
            expected = privilege in postgres_permissions.APP_TABLE_PRIVILEGES[table]

            assert cursor.fetchone()[0] == expected


def test_app_table_privileges_match_application_needs(app_database):
    cursor, app_user, connect_as_app = app_database

    # Written here on purpose, not copied from APP_TABLE_PRIVILEGES, so
    # that a privilege added back by mistake makes this test fail. Only
    # trips and visit_trip_legs need DELETE.
    expected_privileges = {
        "clients": ["SELECT", "INSERT", "UPDATE"],
        "services": ["SELECT", "INSERT", "UPDATE"],
        "trips": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "visits": ["SELECT", "INSERT", "UPDATE"],
        "visit_notes": ["SELECT", "INSERT", "UPDATE"],
        "expenses": ["SELECT", "INSERT", "UPDATE"],
        "visit_trip_legs": ["SELECT", "INSERT", "DELETE"],
        "visit_note_history": ["SELECT"],
        "users": [],
        "schema_migrations": [],
    }

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    for table, privileges in expected_privileges.items():
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            cursor.execute(
                "SELECT has_table_privilege(%s, %s, %s)",
                (app_user, table, privilege)
            )

            assert cursor.fetchone()[0] == (privilege in privileges), (table, privilege)


def test_grant_app_permissions_removes_old_delete_privileges(app_database):
    cursor, app_user, connect_as_app = app_database
    user = sql.Identifier(app_user)

    # An earlier installation gave DELETE on these tables
    cursor.execute(sql.SQL("GRANT DELETE ON visit_notes, expenses TO {}").format(user))

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))
    postgres_permissions.check_app_permissions(cursor, app_user)

    for table in ("visit_notes", "expenses"):
        cursor.execute("SELECT has_table_privilege(%s, %s, 'DELETE')", (app_user, table))
        assert cursor.fetchone()[0] is False

    # trips and visit_trip_legs keep the DELETE they need
    for table in ("trips", "visit_trip_legs"):
        cursor.execute("SELECT has_table_privilege(%s, %s, 'DELETE')", (app_user, table))
        assert cursor.fetchone()[0] is True


def test_app_account_cannot_delete_notes_or_expenses(app_database, app_users):
    cursor, app_user, connect_as_app = app_database
    worker_id = app_users["worker"]
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        visit_id = insert_visit(app_cursor, worker_id)

        # SELECT, INSERT and UPDATE still work
        app_cursor.execute(
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
            "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
            (visit_id, worker_id)
        )
        note_id = app_cursor.fetchone()[0]

        with connection.transaction():
            set_actor(app_cursor, worker_id)
            app_cursor.execute(
                "UPDATE visit_notes SET content = 'Muutettu' WHERE id = %s", (note_id,)
            )

        app_cursor.execute("SELECT content FROM visit_notes WHERE id = %s", (note_id,))
        assert app_cursor.fetchone()[0] == "Muutettu"

        app_cursor.execute(
            "INSERT INTO expenses (visit_id, expense_date, amount, category, "
            "user_id, created_by_user_id) "
            "VALUES (%s, '2026-11-20', 12.50, 'customer', %s, %s) RETURNING id",
            (visit_id, worker_id, worker_id)
        )
        expense_id = app_cursor.fetchone()[0]
        app_cursor.execute("UPDATE expenses SET amount = 13.00 WHERE id = %s", (expense_id,))
        app_cursor.execute("SELECT amount FROM expenses WHERE id = %s", (expense_id,))
        assert str(app_cursor.fetchone()[0]) == "13.00"

        # DELETE is denied
        assert_postgres_error(
            app_cursor, psycopg.errors.InsufficientPrivilege,
            "DELETE FROM visit_notes WHERE id = %s", (note_id,),
        )
        assert_postgres_error(
            app_cursor, psycopg.errors.InsufficientPrivilege,
            "DELETE FROM expenses WHERE id = %s", (expense_id,),
        )

    cursor.execute("SELECT COUNT(*) FROM visit_notes")
    assert cursor.fetchone()[0] == 1
    cursor.execute("SELECT COUNT(*) FROM expenses")
    assert cursor.fetchone()[0] == 1


def test_app_account_cannot_change_note_history(app_database, app_users):
    cursor, app_user, connect_as_app = app_database
    worker_id = app_users["worker"]
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        visit_id = insert_visit(app_cursor, worker_id)
        app_cursor.execute(
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) "
            "VALUES (%s, 'Muistiinpano', %s) RETURNING id",
            (visit_id, worker_id)
        )
        note_id = app_cursor.fetchone()[0]

        # Editing the note writes one history row through the trigger,
        # with the editor that the application gave.
        with connection.transaction():
            set_actor(app_cursor, worker_id)
            app_cursor.execute(
                "UPDATE visit_notes SET content = 'Muutettu' WHERE id = %s", (note_id,)
            )

        app_cursor.execute(
            "SELECT old_content, new_content, edited_by_user_id "
            "FROM visit_note_history WHERE note_id = %s",
            (note_id,)
        )
        assert app_cursor.fetchall() == [("Muistiinpano", "Muutettu", worker_id)]

        # The application cannot write the history, run the trigger
        # function itself, or remove the trigger.
        forbidden_sql = [
            (
                "INSERT INTO visit_note_history "
                "(note_id, old_content, new_content, edited_by_user_id) "
                "VALUES (%s, 'Väärä', 'Väärä', %s)",
                (note_id, worker_id),
            ),
            ("UPDATE visit_note_history SET new_content = 'Väärä'", ()),
            ("DELETE FROM visit_note_history", ()),
            ("TRUNCATE visit_note_history", ()),
            ("SELECT save_visit_note_history()", ()),
            ("DROP TRIGGER trg_visit_notes_history ON visit_notes", ()),
            ("ALTER TABLE visit_notes DISABLE TRIGGER trg_visit_notes_history", ()),
            ("ALTER FUNCTION save_visit_note_history() SECURITY INVOKER", ()),
        ]

        for statement, values in forbidden_sql:
            assert_postgres_error(
                app_cursor, psycopg.errors.InsufficientPrivilege, statement, values
            )

    cursor.execute("SELECT old_content, new_content FROM visit_note_history")
    assert cursor.fetchall() == [("Muistiinpano", "Muutettu")]


@pytest.mark.parametrize(
    "function_name",
    ["save_visit_note_history", "prevent_created_by_change"],
)
def test_other_owner_of_trigger_function_is_rejected(app_database, function_name):
    cursor, app_user, connect_as_app = app_database
    owner = sql.Identifier(get_table_owner(cursor))
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    # An account other than the table owner must not own a trigger
    # function: the owner could replace it, for example with a function
    # that lets created_by_user_id change.
    cursor.execute(
        sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
            sql.Identifier(function_name),
            sql.Identifier(app_user),
        )
    )

    try:
        with pytest.raises(RuntimeError, match="Invalid function owner"):
            postgres_migrate.validate_schema(cursor, ALL_VERSIONS)

        with pytest.raises(RuntimeError, match="owns database objects"):
            postgres_permissions.check_app_permissions(cursor, app_user)

    finally:
        # The account can be dropped only when it owns nothing
        cursor.execute(
            sql.SQL("ALTER FUNCTION {}() OWNER TO {}").format(
                sql.Identifier(function_name),
                owner,
            )
        )

    postgres_migrate.validate_schema(cursor, ALL_VERSIONS)
    postgres_permissions.check_app_permissions(cursor, app_user)


def test_grant_app_permissions_removes_old_privileges(app_database):
    cursor, app_user, connect_as_app = app_database
    user = sql.Identifier(app_user)

    cursor.execute(sql.SQL("GRANT ALL ON clients, schema_migrations TO {}").format(user))
    cursor.execute(sql.SQL("GRANT SELECT ON users TO {}").format(user))

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))
    postgres_permissions.check_app_permissions(cursor, app_user)


@pytest.mark.parametrize(
    ("grant_sql", "message"),
    [
        ("GRANT DELETE ON clients TO {}", "excessive privilege: DELETE on clients"),
        ("GRANT DELETE ON visit_notes TO {}", "excessive privilege: DELETE on visit_notes"),
        ("GRANT DELETE ON expenses TO {}", "excessive privilege: DELETE on expenses"),
        ("GRANT TRUNCATE ON visits TO {}", "excessive privilege: TRUNCATE on visits"),
        ("GRANT SELECT ON schema_migrations TO {}", "on schema_migrations"),
        ("GRANT SELECT (password_hash) ON users TO {}", "users.password_hash"),
        ("GRANT UPDATE (id) ON visit_trip_legs TO {}", "UPDATE on visit_trip_legs"),
        (
            "GRANT INSERT ON visit_note_history TO {}",
            "excessive privilege: INSERT on visit_note_history",
        ),
        ("GRANT CREATE ON SCHEMA public TO {}", "can create database objects"),
    ],
)
def test_check_app_permissions_rejects_excessive_privileges(app_database, grant_sql, message):
    cursor, app_user, connect_as_app = app_database

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))
    cursor.execute(sql.SQL(grant_sql).format(sql.Identifier(app_user)))

    with pytest.raises(RuntimeError, match=message):
        postgres_permissions.check_app_permissions(cursor, app_user)


@pytest.mark.parametrize(
    ("default_sql", "message"),
    [
        (SCHEMA_DEFAULT_PRIVILEGES[0], "on new tables of .* in a schema"),
        (SCHEMA_DEFAULT_PRIVILEGES[1], "USAGE on new sequences of .* in a schema"),
        (GLOBAL_DEFAULT_PRIVILEGES[0], "on new tables of .* in all schemas"),
        (GLOBAL_DEFAULT_PRIVILEGES[1], "USAGE on new sequences of .* in all schemas"),
    ],
)
def test_check_app_permissions_rejects_default_privileges(app_database, default_sql, message):
    cursor, app_user, connect_as_app = app_database
    owner = sql.Identifier(get_table_owner(cursor))

    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))
    cursor.execute(sql.SQL(default_sql).format(owner, sql.Identifier(app_user)))

    with pytest.raises(RuntimeError, match=message):
        postgres_permissions.check_app_permissions(cursor, app_user)


@pytest.mark.parametrize(
    "default_sql_list",
    [SCHEMA_DEFAULT_PRIVILEGES, GLOBAL_DEFAULT_PRIVILEGES],
    ids=["schema", "global"],
)
def test_grant_app_permissions_removes_default_privileges(app_database, default_sql_list):
    cursor, app_user, connect_as_app = app_database
    owner_user = get_table_owner(cursor)
    user = sql.Identifier(app_user)

    for default_sql in default_sql_list:
        cursor.execute(sql.SQL(default_sql).format(sql.Identifier(owner_user), user))

    # Running the fix twice gives the same result
    postgres_permissions.grant_app_permissions(cursor, app_user, owner_user)
    postgres_permissions.grant_app_permissions(cursor, app_user, owner_user)
    postgres_permissions.check_app_permissions(cursor, app_user)

    # Tables and sequences created after the fix give no privileges
    cursor.execute("CREATE TABLE extra_table (id INT)")
    cursor.execute("CREATE SEQUENCE extra_sequence")

    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        cursor.execute(
            "SELECT has_table_privilege(%s, 'extra_table', %s)",
            (app_user, privilege)
        )
        assert cursor.fetchone()[0] is False

    for privilege in ("USAGE", "SELECT", "UPDATE"):
        cursor.execute(
            "SELECT has_sequence_privilege(%s, 'extra_sequence', %s)",
            (app_user, privilege)
        )
        assert cursor.fetchone()[0] is False

    # The new table and sequence do not break the check either
    postgres_permissions.check_app_permissions(cursor, app_user)


@pytest.mark.parametrize(
    ("public_sql", "message"),
    [
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT SELECT ON TABLES TO PUBLIC",
            "PUBLIC has default privilege SELECT on new tables of .* in a schema",
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} GRANT SELECT ON TABLES TO PUBLIC",
            "PUBLIC has default privilege SELECT on new tables of .* in all schemas",
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} GRANT USAGE ON SEQUENCES TO PUBLIC",
            "PUBLIC has default privilege USAGE on new sequences",
        ),
        (
            "GRANT SELECT (password_hash) ON users TO PUBLIC",
            "can read users.password_hash",
        ),
    ],
)
def test_check_app_permissions_rejects_public_privileges(app_database, public_sql, message):
    cursor, app_user, connect_as_app = app_database
    owner_user = get_table_owner(cursor)

    cursor.execute(sql.SQL(public_sql).format(sql.Identifier(owner_user)))

    # The fix does not change PUBLIC privileges. The check stops the
    # installation, so that an administrator removes them.
    postgres_permissions.grant_app_permissions(cursor, app_user, owner_user)

    with pytest.raises(RuntimeError, match=message):
        postgres_permissions.check_app_permissions(cursor, app_user)


def test_check_app_permissions_rejects_missing_account(app_database):
    cursor, app_user, connect_as_app = app_database

    with pytest.raises(RuntimeError, match="Application account is missing"):
        postgres_permissions.check_app_permissions(cursor, "carelog_test_no_such_account")


def test_app_account_cannot_change_schema(app_database):
    cursor, app_user, connect_as_app = app_database
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    forbidden_sql = [
        "CREATE TABLE extra (id INT)",
        "CREATE SCHEMA extra",
        "ALTER TABLE clients ADD COLUMN extra INT",
        "ALTER TABLE visits DROP CONSTRAINT chk_visits_status",
        "CREATE INDEX extra_index ON clients (city)",
        "DROP TRIGGER trg_clients_updated_at ON clients",
        "DROP TABLE expenses",
        "TRUNCATE visits",
        "DELETE FROM clients",
        "SELECT password_hash FROM users",
        "INSERT INTO schema_migrations (version) VALUES (99)",
        "DELETE FROM schema_migrations",
        # The users table can only be read, column by column. Locking a
        # user row would need UPDATE (Phase 3 decides how to check users).
        "INSERT INTO users (email, display_name, password_hash) VALUES ('a@b.c', 'A', 'x')",
        "UPDATE users SET role = 'admin'",
        "DELETE FROM users",
        "SELECT id FROM users FOR SHARE",
        # The created_by protection of v014 cannot be turned off
        "DROP TRIGGER trg_visits_created_by ON visits",
        "ALTER TABLE clients DISABLE TRIGGER trg_clients_created_by",
        "ALTER FUNCTION prevent_created_by_change() SECURITY DEFINER",
        "CREATE OR REPLACE FUNCTION prevent_created_by_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$",
        "SET session_replication_role = replica",
    ]

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        for statement in forbidden_sql:
            assert_postgres_error(app_cursor, psycopg.errors.InsufficientPrivilege, statement)

    postgres_migrate.validate_schema(cursor, ALL_VERSIONS)


def test_app_account_can_use_user_columns(app_database, app_users):
    cursor, app_user, connect_as_app = app_database
    worker_id = app_users["worker"]
    admin_id = app_users["admin"]
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()
    connection.autocommit = True

    # The existing privileges are enough for the user columns of v014: a
    # foreign key to users is checked with the rights of the table owner.
    # The admin adds a visit, and the worker it belongs to changes it.
    with connection, connection.cursor() as app_cursor:
        visit_id = insert_visit(app_cursor, admin_id)
        app_cursor.execute(
            "UPDATE visits SET user_id = %s, updated_by_user_id = %s WHERE id = %s",
            (worker_id, worker_id, visit_id)
        )

        # The application can read who the users are
        app_cursor.execute("SELECT role FROM users WHERE id = %s", (admin_id,))

        assert app_cursor.fetchone()[0] == "admin"

    cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone() == (worker_id, admin_id, worker_id)


def test_app_account_can_check_user(app_database, app_users):
    cursor, app_user, connect_as_app = app_database
    worker_id = app_users["worker"]
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        # The application cannot read password hashes, so the check works
        # without them.
        assert_postgres_error(
            app_cursor, psycopg.errors.InsufficientPrivilege,
            "SELECT password_hash FROM users",
        )

        user = get_active_user(app_cursor, worker_id)

        assert user == {"id": worker_id, "role": "worker", "is_active": True}

        with pytest.raises(PermissionError):
            get_active_user(app_cursor, app_users["inactive"])


def test_app_account_can_run_services(app_database, app_users, monkeypatch):
    cursor, app_user, connect_as_app = app_database
    worker_id = app_users["worker"]
    admin_id = app_users["admin"]
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    for module in SERVICE_MODULES:
        monkeypatch.setattr(f"{module}.get_postgres_connection", connect_as_app)

    # The services use every granted privilege, including SELECT ... FOR
    # UPDATE, which needs UPDATE, and identity columns without sequence
    # privileges.
    # The user check of the services reads users with the application
    # account, and the creator and the latest editor are saved.
    client_id = add_client(worker_id, "Hilma", "Testi")
    assert update_client(admin_id, client_id, {"city": "Tampere"})

    service_id = add_service(admin_id, "Kauppa-asiointi", default_hourly_rate=Decimal("30.00"))
    assert update_service(worker_id, service_id, {"description": "Kaupassa käynti"})

    trip_id = add_trip(worker_id, client_id, "Koti", "Kauppa", Decimal("3.20"))
    assert update_trip(admin_id, trip_id, {"distance_km": Decimal("3.50")})
    assert delete_trip(worker_id, trip_id)

    # The admin plans a visit for the worker, who completes it
    visit_id = add_planned_visit(
        admin_id, client_id, service_id, planned_date=date(2026, 11, 20), user_id=worker_id
    )
    # The worker writes a note to their visit, the admin corrects it
    note_id = add_visit_note(worker_id, visit_id, "Muistiinpano")
    assert update_visit_note(admin_id, note_id, "Muutettu muistiinpano")

    # The trigger saved the history although the application account
    # may only read the history table.
    history = get_visit_note_history(worker_id, note_id)
    assert len(history) == 1
    assert history[0]["new_content"] == "Muutettu muistiinpano"
    assert history[0]["edited_by_user_id"] == admin_id

    legs = [{"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")}]
    assert save_visit_trip(worker_id, visit_id, legs)
    assert complete_visit(
        worker_id, visit_id, completed_date=date(2026, 11, 20), duration_minutes=60
    )

    # The worker adds an expense to their visit, the admin corrects it
    expense_id = add_expense(
        worker_id, date(2026, 11, 20), Decimal("12.50"), "customer", visit_id=visit_id
    )
    assert update_expense(admin_id, expense_id, {"amount": Decimal("13.00")})

    cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM expenses WHERE id = %s",
        (expense_id,)
    )
    assert cursor.fetchone() == (worker_id, worker_id, admin_id)

    other_visit_id = add_planned_visit(
        worker_id, client_id, service_id, planned_date=date(2026, 11, 26)
    )
    assert change_visit_worker(admin_id, other_visit_id, admin_id)
    assert cancel_visit(admin_id, other_visit_id)

    # Worker, creator and latest editor of both visits
    cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM visits ORDER BY id"
    )
    assert cursor.fetchall() == [
        (worker_id, admin_id, worker_id),
        (admin_id, worker_id, admin_id),
    ]

    assert archive_client(admin_id, client_id)

    cursor.execute(
        "SELECT created_by_user_id, updated_by_user_id FROM clients WHERE id = %s",
        (client_id,)
    )
    assert cursor.fetchone() == (worker_id, admin_id)

    cursor.execute(
        "SELECT created_by_user_id, updated_by_user_id FROM services WHERE id = %s",
        (service_id,)
    )
    assert cursor.fetchone() == (admin_id, worker_id)

    # The application can read the user list, but not the password hashes
    connection = connect_as_app()

    with connection, connection.cursor() as app_cursor:
        app_cursor.execute("SELECT id, email, display_name, role, is_active FROM users")
        assert len(app_cursor.fetchall()) == 4


def test_apply_app_permissions(app_database, connect_to_test_postgres, monkeypatch):
    cursor, app_user, connect_as_app = app_database

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    owner_user = get_table_owner(cursor)

    # A real installation uses carelog_migrator. Here the test user owns
    # the tables, so it takes the place of the migration account.
    assert postgres_permissions.MIGRATION_USER == "carelog_migrator"
    monkeypatch.setattr(postgres_permissions, "MIGRATION_USER", owner_user)

    def get_test_connection(database=None, user=None, password=None):
        assert user == owner_user
        assert password == "test-only"
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(postgres_permissions, "get_postgres_connection", get_test_connection)

    # A default privilege that the fix must remove in the same transaction
    cursor.execute(
        sql.SQL(GLOBAL_DEFAULT_PRIVILEGES[0]).format(
            sql.Identifier(owner_user),
            sql.Identifier(app_user),
        )
    )

    with pytest.raises(ValueError):
        postgres_permissions.apply_app_permissions(app_user, database, password="")

    postgres_permissions.apply_app_permissions(app_user, database, password="test-only")

    # The privileges were saved, so a new connection sees them
    postgres_permissions.check_app_permissions(cursor, app_user)
