import os
import subprocess
import sys
from pathlib import Path
from secrets import token_hex
from uuid import uuid4

import pymysql
import pytest
from pymysql.constants import ER

from carelog.database import migrate
from tests.migration_helpers import assert_mysql_error, get_columns, insert_client, insert_service


PROJECT_DIR = Path(__file__).resolve().parents[1]

# The installer functions run against the test socket. Package installation is never called.
INSTALL_DATABASE = """
source ./install.sh
DB_NAME="$CARELOG_TEST_DATABASE"
mysql_admin() {
    mysql --no-defaults --protocol=socket --socket="$CARELOG_TEST_MYSQL_SOCKET" --user=root "$@"
}
test_python() {
    "$CARELOG_TEST_PYTHON" -c '
import os
import sys

import pymysql

from carelog.database import migrate

def connect(database=None, user=None, password=None):
    assert user == "carelog_migrator"
    return pymysql.connect(
        unix_socket=os.environ["CARELOG_TEST_MYSQL_SOCKET"],
        user=user,
        password=password,
        database=os.environ["CARELOG_TEST_DATABASE"],
    )

socket = os.environ["CARELOG_TEST_MYSQL_SOCKET"]
with pymysql.connect(unix_socket=socket, user="root") as admin, admin.cursor() as cursor:
    cursor.execute("SHOW GRANTS FOR carelog_app@localhost")
    assert cursor.fetchall() == (("GRANT USAGE ON *.* TO `carelog_app`@`localhost`",),)
    cursor.execute("SHOW GRANTS FOR carelog_migrator@localhost")
    database = os.environ["CARELOG_TEST_DATABASE"]
    grants = [row[0] for row in cursor.fetchall()]
    assert len(grants) == 2
    assert grants[0] == "GRANT USAGE ON *.* TO `carelog_migrator`@`localhost`"
    privilege_part, scope_part = grants[1].split(" ON ", 1)
    privileges = set(privilege_part.removeprefix("GRANT ").split(", "))
    assert privileges == {"SELECT", "INSERT", "CREATE", "REFERENCES", "ALTER"}
    assert scope_part == f"`{database}`.* TO `carelog_migrator`@`localhost`"

password = sys.stdin.readline().rstrip("\\n")
assert password
if os.getenv("CARELOG_TEST_MIGRATION_FAILURE"):
    raise SystemExit("Simulated migration failure")

# Verify that ALTER is usable, not only listed by SHOW GRANTS.
with pymysql.connect(unix_socket=socket, user="root", database=database, autocommit=True) as admin:
    with admin.cursor() as cursor:
        cursor.execute("CREATE TABLE carelog_alter_probe (id INT PRIMARY KEY)")
        try:
            with pymysql.connect(
                unix_socket=socket,
                user="carelog_migrator",
                password=password,
                database=database,
                autocommit=True,
            ) as migrator:
                with migrator.cursor() as migration_cursor:
                    migration_cursor.execute(
                        "ALTER TABLE carelog_alter_probe ADD COLUMN marker INT"
                    )
            cursor.execute("SHOW COLUMNS FROM carelog_alter_probe LIKE %s", ("marker",))
            assert cursor.fetchone() is not None
        finally:
            cursor.execute("DROP TABLE carelog_alter_probe")

migrate.get_connection = connect
migrate.run_migrations(password=password)
'
}
PYTHON=test_python
trap cleanup EXIT
check_migration_user
check_schema
check_app_permissions
create_database_if_missing
run_migrations
"""


@pytest.fixture
def installer_database():
    socket = os.getenv("CARELOG_TEST_MYSQL_SOCKET")
    if os.getenv("CARELOG_TEST_INSTALLER") != "1" or not socket:
        pytest.skip("Set CARELOG_TEST_INSTALLER=1 and a dedicated local MySQL test socket")

    expected_uuid = os.getenv("CARELOG_TEST_MYSQL_SERVER_UUID")
    if not expected_uuid:
        pytest.fail("Set CARELOG_TEST_MYSQL_SERVER_UUID for the dedicated test server")

    database = "carelogtest" + uuid4().hex
    password = "Aa1!" + token_hex(32)
    with pymysql.connect(unix_socket=socket, user="root", autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT @@GLOBAL.server_uuid")
            server_uuid = cursor.fetchone()[0]
            if server_uuid != expected_uuid:
                pytest.fail("Wrong MySQL server: refusing to run installer tests")

            cursor.execute(
                "SELECT COUNT(*) FROM mysql.user "
                "WHERE User IN ('carelog_app', 'carelog_migrator') AND Host = 'localhost'"
            )
            assert cursor.fetchone() == (0,), "The test server already has CareLog accounts"

            cursor.execute(f"CREATE DATABASE `{database}`")
            try:
                cursor.execute("CREATE USER 'carelog_app'@'localhost' IDENTIFIED BY %s", (password,))
                try:
                    connection.select_db(database)
                    os_env = os.environ.copy()
                    os_env["CARELOG_TEST_DATABASE"] = database
                    os_env["CARELOG_TEST_PYTHON"] = sys.executable
                    os_env.pop("CARELOG_TEST_MIGRATION_FAILURE", None)

                    def connect_app():
                        return pymysql.connect(
                            unix_socket=socket,
                            user="carelog_app",
                            password=password,
                            database=database,
                        )

                    yield cursor, os_env, connect_app
                finally:
                    cursor.execute("DROP USER 'carelog_app'@'localhost'")
            finally:
                cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")


def install_database(env):
    return subprocess.run(
        ["bash", "-c", INSTALL_DATABASE],
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def assert_no_migrator(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM mysql.user "
        "WHERE User = 'carelog_migrator' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == (0,)


def assert_business_constraints(cursor):
    cursor.execute("""
        SELECT TABLE_NAME, CONSTRAINT_NAME, ENFORCED
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
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


def test_application_privileges_and_reinstallation(installer_database):
    cursor, env, connect_app = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    result = install_database(env)
    assert result.returncode == 0, result.stderr
    assert migrate.get_applied_versions(cursor) == set(range(1, 9))
    assert_business_constraints(cursor)
    insert_service(cursor)
    client_id = insert_client(cursor)

    # Reinstallation must work with the installer's own table-level grants.
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    assert_no_migrator(cursor)
    assert migrate.get_applied_versions(cursor) == set(range(1, 9))
    assert_business_constraints(cursor)
    assert "personal_identity_code" not in [column[0] for column in get_columns(cursor, "clients")]
    cursor.execute("SELECT first_name FROM clients WHERE id = %s", (client_id,))
    assert cursor.fetchone() == ("Test",)

    with connect_app() as app, app.cursor() as app_cursor:
        app_cursor.execute("SHOW GRANTS")
        for grant, in app_cursor.fetchall():
            assert f"ON `{database}`.*" not in grant
            assert "WITH GRANT OPTION" not in grant

        app_cursor.execute("SELECT name FROM services")
        assert app_cursor.fetchone() == ("Test service",)
        app_cursor.execute(
            "UPDATE services SET default_hourly_rate = 30 WHERE name = 'Test service'"
        )
        assert app_cursor.rowcount == 1
        app_cursor.execute("SELECT id, role FROM users")
        assert app_cursor.fetchall() == ()
        app_cursor.execute(
            "INSERT INTO expenses (expense_date, amount, category) "
            "VALUES ('2026-01-01', 12.50, 'company')"
        )
        expense_id = app_cursor.lastrowid
        app_cursor.execute("UPDATE expenses SET amount = 20 WHERE id = %s", (expense_id,))
        assert app_cursor.rowcount == 1
        app_cursor.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
        assert app_cursor.rowcount == 1

        # v008 must reject invalid values for the application account.
        assert_mysql_error(
            app_cursor, 3819,
            "INSERT INTO expenses (expense_date, amount, category) "
            "VALUES ('2026-01-01', -1, 'company')",
        )

        for sql in (
            "SELECT version FROM schema_migrations",
            "INSERT INTO schema_migrations (version) VALUES (999)",
            "UPDATE schema_migrations SET version = 999 WHERE version = 1",
            "DELETE FROM schema_migrations WHERE version = 1",
            "CREATE TABLE denied (id INT)",
            "ALTER TABLE expenses ADD COLUMN denied INT",
            "DROP TABLE expenses",
            "DELETE FROM services WHERE name = 'Test service'",
            "INSERT INTO users (email, display_name, password_hash, role) "
            "VALUES ('test@example.com', 'Test', 'test-only', 'admin')",
            "DELETE FROM users WHERE id = 1",
            "UPDATE users SET role = 'admin' WHERE id = 1",
            "UPDATE users SET password_hash = 'test-only' WHERE id = 1",
        ):
            assert_mysql_error(app_cursor, ER.TABLEACCESS_DENIED_ERROR, sql)

        assert_mysql_error(
            app_cursor, ER.COLUMNACCESS_DENIED_ERROR, "SELECT password_hash FROM users",
        )


def test_app_privileges_match_permission_matrix(installer_database):
    cursor, env, _ = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    grantee = "'carelog_app'@'localhost'"

    result = install_database(env)
    assert result.returncode == 0, result.stderr

    # Reinstallation must keep exactly the same privileges.
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    # No global privileges: only the USAGE line plus table-level grants.
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    grants = cursor.fetchall()
    assert grants[0] == ("GRANT USAGE ON *.* TO `carelog_app`@`localhost`",)

    # No database-wide privileges on any database.
    cursor.execute(
        "SELECT TABLE_SCHEMA, PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
        "WHERE GRANTEE = %s",
        (grantee,)
    )
    assert cursor.fetchall() == ()

    cursor.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME, PRIVILEGE_TYPE, IS_GRANTABLE "
        "FROM information_schema.TABLE_PRIVILEGES WHERE GRANTEE = %s",
        (grantee,)
    )
    table_privileges = set(cursor.fetchall())

    expected_table_privileges = set()
    permission_matrix = {
        "clients": ["SELECT", "INSERT", "UPDATE"],
        "services": ["SELECT", "INSERT", "UPDATE"],
        "trips": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "visits": ["SELECT", "INSERT", "UPDATE"],
        "visit_notes": ["SELECT", "INSERT", "UPDATE", "DELETE"],
        "expenses": ["SELECT", "INSERT", "UPDATE", "DELETE"],
    }
    for table, privileges in permission_matrix.items():
        for privilege in privileges:
            expected_table_privileges.add((database, table, privilege, "NO"))

    assert table_privileges == expected_table_privileges

    cursor.execute(
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, PRIVILEGE_TYPE, IS_GRANTABLE "
        "FROM information_schema.COLUMN_PRIVILEGES WHERE GRANTEE = %s",
        (grantee,)
    )
    column_privileges = set(cursor.fetchall())

    expected_column_privileges = set()
    for column in ("id", "email", "display_name", "role", "is_active"):
        expected_column_privileges.add((database, "users", column, "SELECT", "NO"))

    assert column_privileges == expected_column_privileges


def test_installation_creates_missing_database(installer_database):
    cursor, env, _ = installer_database
    database = env["CARELOG_TEST_DATABASE"]

    # .env and carelog_app exist, but the database was removed.
    cursor.execute(f"DROP DATABASE `{database}`")

    result = install_database(env)
    assert result.returncode == 0, result.stderr
    assert "creating an empty database" in result.stdout
    assert_no_migrator(cursor)

    cursor.execute(
        "SELECT DEFAULT_CHARACTER_SET_NAME FROM information_schema.SCHEMATA "
        "WHERE SCHEMA_NAME = %s",
        (database,)
    )
    assert cursor.fetchone() == ("utf8mb4",)

    cursor.execute(f"USE `{database}`")
    assert migrate.get_applied_versions(cursor) == set(range(1, 9))


def test_failed_installation_restores_app_and_allows_retry(installer_database):
    cursor, env, connect_app = installer_database

    result = install_database(env)
    assert result.returncode == 0, result.stderr

    env["CARELOG_TEST_MIGRATION_FAILURE"] = "1"

    result = install_database(env)

    assert result.returncode != 0
    assert "Simulated migration failure" in result.stderr
    assert_no_migrator(cursor)
    cursor.execute(
        "SELECT account_locked FROM mysql.user WHERE User = 'carelog_app' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == ("N",)

    with connect_app() as app, app.cursor() as app_cursor:
        app_cursor.execute("SELECT name FROM services")
        assert app_cursor.fetchall() == ()
        assert_mysql_error(
            app_cursor, ER.TABLEACCESS_DENIED_ERROR,
            "SELECT version FROM schema_migrations",
        )

    env.pop("CARELOG_TEST_MIGRATION_FAILURE")
    result = install_database(env)
    assert result.returncode == 0, result.stderr
    assert_no_migrator(cursor)
    assert migrate.get_applied_versions(cursor) == set(range(1, 9))
    assert_business_constraints(cursor)


def test_active_application_session_blocks_reinstallation(installer_database):
    cursor, env, connect_app = installer_database
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    with connect_app() as app, app.cursor() as app_cursor:
        result = install_database(env)

        assert result.returncode != 0
        assert "close its database sessions" in result.stderr
        app_cursor.execute("SELECT name FROM services")

    assert_no_migrator(cursor)
    with connect_app() as app:
        assert app.open


@pytest.mark.parametrize(
    "extra_grant",
    [
        "GRANT PROCESS ON *.* TO 'carelog_app'@'localhost'",
        "GRANT BACKUP_ADMIN ON *.* TO 'carelog_app'@'localhost'",
        "GRANT SELECT ON carelogothertest.* TO 'carelog_app'@'localhost'",
    ],
)
def test_unexpected_grants_require_manual_review(installer_database, extra_grant):
    cursor, env, _ = installer_database
    cursor.execute(extra_grant)
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    previous = cursor.fetchall()

    result = install_database(env)

    assert result.returncode != 0
    assert "Manual review required" in result.stderr
    assert_no_migrator(cursor)
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    assert cursor.fetchall() == previous


@pytest.mark.parametrize(
    "extra_grant",
    [
        "GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO 'carelog_app'@'localhost'",
        "GRANT SELECT ON `{database}`.* TO 'carelog_app'@'localhost' WITH GRANT OPTION",
        "GRANT ALL PRIVILEGES ON `{database}`.* TO 'carelog_app'@'localhost' WITH GRANT OPTION",
        "GRANT SELECT ON `{database}`.`services` TO 'carelog_app'@'localhost' WITH GRANT OPTION",
        "GRANT DELETE ON `{database}`.`services` TO 'carelog_app'@'localhost'",
        "GRANT ALTER ON `{database}`.`clients` TO 'carelog_app'@'localhost'",
        "GRANT SELECT ON `{database}`.`schema_migrations` TO 'carelog_app'@'localhost'",
        "GRANT SELECT ON `{database}`.`users` TO 'carelog_app'@'localhost'",
        "GRANT SELECT (password_hash) ON `{database}`.`users` TO 'carelog_app'@'localhost'",
        "GRANT UPDATE (role) ON `{database}`.`users` TO 'carelog_app'@'localhost'",
    ],
)
def test_excessive_app_privileges_are_rejected_without_changes(installer_database, extra_grant):
    cursor, env, _ = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    cursor.execute(extra_grant.format(database=database))
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    previous = cursor.fetchall()

    result = install_database(env)

    assert result.returncode != 0
    assert "Manual review required" in result.stderr
    assert_no_migrator(cursor)
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    assert cursor.fetchall() == previous
    cursor.execute(
        "SELECT account_locked FROM mysql.user WHERE User = 'carelog_app' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == ("N",)


def test_excessive_privileges_do_not_unlock_locked_account(installer_database):
    cursor, env, _ = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    cursor.execute(f"GRANT ALTER ON `{database}`.`clients` TO 'carelog_app'@'localhost'")
    cursor.execute("ALTER USER 'carelog_app'@'localhost' ACCOUNT LOCK")
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    previous = cursor.fetchall()

    result = install_database(env)

    assert result.returncode != 0
    assert "Manual review required" in result.stderr
    assert_no_migrator(cursor)
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    assert cursor.fetchall() == previous
    cursor.execute(
        "SELECT account_locked FROM mysql.user WHERE User = 'carelog_app' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == ("Y",)


def test_reinstallation_restores_missing_allowed_privilege(installer_database):
    cursor, env, connect_app = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    cursor.execute(f"REVOKE UPDATE ON `{database}`.`clients` FROM 'carelog_app'@'localhost'")
    result = install_database(env)
    assert result.returncode == 0, result.stderr
    assert_no_migrator(cursor)

    with connect_app() as app, app.cursor() as app_cursor:
        app_cursor.execute("SHOW GRANTS")
        assert any("UPDATE" in row[0] and "`clients`" in row[0] for row in app_cursor.fetchall())


def test_inherited_role_requires_manual_review(installer_database):
    cursor, env, _ = installer_database
    cursor.execute("CREATE ROLE 'carelog_permission_test_role'")
    try:
        cursor.execute("GRANT 'carelog_permission_test_role' TO 'carelog_app'@'localhost'")

        result = install_database(env)

        assert result.returncode != 0
        assert "Manual review required" in result.stderr
        assert_no_migrator(cursor)
    finally:
        cursor.execute("DROP ROLE 'carelog_permission_test_role'")


def test_mandatory_role_blocks_installation(installer_database):
    cursor, env, _ = installer_database
    cursor.execute("SELECT @@GLOBAL.mandatory_roles")
    assert cursor.fetchone() == ("",)
    cursor.execute("CREATE ROLE 'carelog_permission_test_role'")
    try:
        cursor.execute("SET GLOBAL mandatory_roles = 'carelog_permission_test_role'")

        result = install_database(env)

        assert result.returncode != 0
        assert "MySQL has mandatory roles" in result.stderr
        assert_no_migrator(cursor)
    finally:
        cursor.execute("SET GLOBAL mandatory_roles = ''")
        cursor.execute("DROP ROLE 'carelog_permission_test_role'")


def test_orphaned_migration_account_is_never_reused(installer_database):
    cursor, env, _ = installer_database
    cursor.execute("CREATE USER 'carelog_migrator'@'localhost' IDENTIFIED BY RANDOM PASSWORD")
    try:
        result = install_database(env)

        assert result.returncode != 0
        assert "Migration account already exists" in result.stderr
        cursor.execute("SHOW GRANTS FOR 'carelog_migrator'@'localhost'")
        assert cursor.fetchall() == (("GRANT USAGE ON *.* TO `carelog_migrator`@`localhost`",),)
    finally:
        cursor.execute("DROP USER 'carelog_migrator'@'localhost'")
