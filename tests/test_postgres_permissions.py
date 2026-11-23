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
from carelog.services.visit_notes import (
    add_visit_note,
    get_visit_note_history,
    update_visit_note,
)
from carelog.services.visit_trips import save_visit_trip
from carelog.services.visits import add_planned_visit, cancel_visit, complete_visit
from tests.postgres_helpers import assert_postgres_error


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
def app_database(postgres_cursor, connect_to_test_postgres):
    # A temporary login account in the role of carelog_app. Accounts are
    # shared by the whole server, so the name is random and the account is
    # removed after the test. Use only a disposable test server.
    app_user = f"carelog_test_app_{token_hex(8)}"
    app_password = token_hex(16)

    postgres_cursor.execute("SELECT current_database()")
    database = postgres_cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    for version, table, upgrade in postgres_migrate.MIGRATIONS:
        upgrade(postgres_cursor)

    postgres_migrate.create_migrations_table(postgres_cursor)

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


def test_app_account_cannot_delete_notes_or_expenses(app_database):
    cursor, app_user, connect_as_app = app_database
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        app_cursor.execute(
            "INSERT INTO clients (first_name, last_name) VALUES ('Test', 'Client') RETURNING id"
        )
        client_id = app_cursor.fetchone()[0]
        app_cursor.execute("INSERT INTO services (name) VALUES ('Test service') RETURNING id")
        service_id = app_cursor.fetchone()[0]
        app_cursor.execute(
            "INSERT INTO visits (client_id, service_id) VALUES (%s, %s) RETURNING id",
            (client_id, service_id)
        )
        visit_id = app_cursor.fetchone()[0]

        # SELECT, INSERT and UPDATE still work
        app_cursor.execute(
            "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Muistiinpano') RETURNING id",
            (visit_id,)
        )
        note_id = app_cursor.fetchone()[0]
        app_cursor.execute("UPDATE visit_notes SET content = 'Muutettu' WHERE id = %s", (note_id,))
        app_cursor.execute("SELECT content FROM visit_notes WHERE id = %s", (note_id,))
        assert app_cursor.fetchone()[0] == "Muutettu"

        app_cursor.execute(
            "INSERT INTO expenses (visit_id, expense_date, amount, category) "
            "VALUES (%s, '2026-11-20', 12.50, 'customer') RETURNING id",
            (visit_id,)
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


def test_app_account_cannot_change_note_history(app_database):
    cursor, app_user, connect_as_app = app_database
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        app_cursor.execute(
            "INSERT INTO clients (first_name, last_name) VALUES ('Test', 'Client') RETURNING id"
        )
        client_id = app_cursor.fetchone()[0]
        app_cursor.execute("INSERT INTO services (name) VALUES ('Test service') RETURNING id")
        service_id = app_cursor.fetchone()[0]
        app_cursor.execute(
            "INSERT INTO visits (client_id, service_id) VALUES (%s, %s) RETURNING id",
            (client_id, service_id)
        )
        visit_id = app_cursor.fetchone()[0]
        app_cursor.execute(
            "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Muistiinpano') RETURNING id",
            (visit_id,)
        )
        note_id = app_cursor.fetchone()[0]

        # Editing the note writes one history row through the trigger
        app_cursor.execute("UPDATE visit_notes SET content = 'Muutettu' WHERE id = %s", (note_id,))
        app_cursor.execute(
            "SELECT old_content, new_content, edited_by_user_id "
            "FROM visit_note_history WHERE note_id = %s",
            (note_id,)
        )
        assert app_cursor.fetchall() == [("Muistiinpano", "Muutettu", None)]

        # The application cannot write the history, run the trigger
        # function itself, or remove the trigger.
        forbidden_sql = [
            (
                "INSERT INTO visit_note_history (note_id, old_content, new_content) "
                "VALUES (%s, 'Väärä', 'Väärä')",
                (note_id,),
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


def test_validate_schema_rejects_other_owner_of_note_history_function(app_database):
    cursor, app_user, connect_as_app = app_database
    owner = sql.Identifier(get_table_owner(cursor))

    # An account other than the table owner must not own the function
    # that runs with its owner's rights.
    cursor.execute(
        sql.SQL("ALTER FUNCTION save_visit_note_history() OWNER TO {}").format(
            sql.Identifier(app_user)
        )
    )

    try:
        with pytest.raises(RuntimeError, match="Invalid function owner"):
            postgres_migrate.validate_schema(cursor, set(range(1, 14)))

    finally:
        # The account can be dropped only when it owns nothing
        cursor.execute(
            sql.SQL("ALTER FUNCTION save_visit_note_history() OWNER TO {}").format(owner)
        )

    postgres_migrate.validate_schema(cursor, set(range(1, 14)))


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
    ]

    connection = connect_as_app()

    # autocommit: a failed statement does not stop the next ones
    connection.autocommit = True

    with connection, connection.cursor() as app_cursor:
        for statement in forbidden_sql:
            assert_postgres_error(app_cursor, psycopg.errors.InsufficientPrivilege, statement)

    postgres_migrate.validate_schema(cursor, set(range(1, 14)))


def test_app_account_can_run_services(app_database, monkeypatch):
    cursor, app_user, connect_as_app = app_database
    postgres_permissions.grant_app_permissions(cursor, app_user, get_table_owner(cursor))

    for module in SERVICE_MODULES:
        monkeypatch.setattr(f"{module}.get_postgres_connection", connect_as_app)

    # The services use every granted privilege, including SELECT ... FOR
    # UPDATE, which needs UPDATE, and identity columns without sequence
    # privileges.
    client_id = add_client("Hilma", "Testi")
    assert update_client(client_id, {"city": "Tampere"})

    service_id = add_service("Kauppa-asiointi", default_hourly_rate=Decimal("30.00"))
    assert update_service(service_id, {"description": "Kaupassa käynti"})

    trip_id = add_trip(client_id, "Koti", "Kauppa", Decimal("3.20"))
    assert update_trip(trip_id, {"distance_km": Decimal("3.50")})
    assert delete_trip(trip_id)

    visit_id = add_planned_visit(client_id, service_id, planned_date=date(2026, 11, 20))
    note_id = add_visit_note(visit_id, "Muistiinpano")
    assert update_visit_note(note_id, "Muutettu muistiinpano")

    # The trigger saved the history although the application account
    # may only read the history table.
    history = get_visit_note_history(note_id)
    assert len(history) == 1
    assert history[0]["new_content"] == "Muutettu muistiinpano"

    legs = [{"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")}]
    assert save_visit_trip(visit_id, legs)
    assert complete_visit(visit_id, completed_date=date(2026, 11, 20), duration_minutes=60)

    expense_id = add_expense(date(2026, 11, 20), Decimal("12.50"), "customer", visit_id=visit_id)
    assert update_expense(expense_id, {"amount": Decimal("13.00")})

    other_visit_id = add_planned_visit(client_id, service_id, planned_date=date(2026, 11, 26))
    assert cancel_visit(other_visit_id)

    assert archive_client(client_id)

    # The application can read the user list, but not the password hashes
    connection = connect_as_app()

    with connection, connection.cursor() as app_cursor:
        app_cursor.execute("SELECT id, email, display_name, role, is_active FROM users")
        assert app_cursor.fetchall() == []


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
