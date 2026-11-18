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
    assert cursor.fetchall() == (
        ("GRANT USAGE ON *.* TO `carelog_migrator`@`localhost`",),
        (f"GRANT SELECT, INSERT, CREATE, REFERENCES, ALTER ON `{os.environ["CARELOG_TEST_DATABASE"]}`.* TO `carelog_migrator`@`localhost`",),
    )

password = sys.stdin.readline().rstrip("\\n")
assert password
if os.getenv("CARELOG_TEST_MIGRATION_FAILURE"):
    raise SystemExit("Simulated migration failure")
migrate.get_connection = connect
migrate.run_migrations(password=password)
'
}
PYTHON=test_python
trap cleanup EXIT
check_migration_user
check_schema
check_app_permissions
run_migrations
"""


@pytest.fixture
def installer_database():
    socket = os.getenv("CARELOG_TEST_MYSQL_SOCKET")
    if os.getenv("CARELOG_TEST_INSTALLER") != "1" or not socket:
        pytest.skip("Set CARELOG_TEST_INSTALLER=1 and a dedicated local MySQL test socket")

    database = "carelogtest" + uuid4().hex
    password = "Aa1!" + token_hex(32)
    with pymysql.connect(unix_socket=socket, user="root", autocommit=True) as connection:
        with connection.cursor() as cursor:
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
                cursor.execute(f"DROP DATABASE `{database}`")


def install_database(env):
    return subprocess.run(
        ["bash", "-c", INSTALL_DATABASE],
        cwd=PROJECT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def assert_no_migrator(cursor):
    cursor.execute(
        "SELECT COUNT(*) FROM mysql.user "
        "WHERE User = 'carelog_migrator' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == (0,)


def test_application_privileges_and_reinstallation(installer_database):
    cursor, env, connect_app = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    result = install_database(env)
    assert result.returncode == 0, result.stderr
    assert migrate.get_applied_versions(cursor) == {1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12}
    insert_service(cursor)
    client_id = insert_client(cursor)

    # Simulate a database that ran the withdrawn migration before updating.
    cursor.execute("ALTER TABLE clients ADD COLUMN personal_identity_code VARCHAR(11) NULL")
    cursor.execute("DELETE FROM schema_migrations WHERE version = 12")
    migrate.record_migration(cursor, 9)

    cursor.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO 'carelog_app'@'localhost'"
    )
    result = install_database(env)
    assert result.returncode == 0, result.stderr

    assert_no_migrator(cursor)
    assert migrate.get_applied_versions(cursor) == set(range(1, 13))
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

        for sql in (
            "SELECT version FROM schema_migrations",
            "INSERT INTO schema_migrations (version) VALUES (999)",
            "UPDATE schema_migrations SET version = 999 WHERE version = 1",
            "DELETE FROM schema_migrations WHERE version = 1",
            "CREATE TABLE denied (id INT)",
            "ALTER TABLE expenses ADD COLUMN denied INT",
            "DROP TABLE expenses",
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


def test_failed_installation_leaves_app_locked_and_removes_migrator(installer_database):
    cursor, env, _ = installer_database
    database = env["CARELOG_TEST_DATABASE"]
    cursor.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{database}`.* TO 'carelog_app'@'localhost'"
    )
    env["CARELOG_TEST_MIGRATION_FAILURE"] = "1"

    result = install_database(env)

    assert result.returncode != 0
    assert "Simulated migration failure" in result.stderr
    assert_no_migrator(cursor)
    cursor.execute("SHOW GRANTS FOR 'carelog_app'@'localhost'")
    assert cursor.fetchall() == (("GRANT USAGE ON *.* TO `carelog_app`@`localhost`",),)
    cursor.execute(
        "SELECT account_locked FROM mysql.user WHERE User = 'carelog_app' AND Host = 'localhost'"
    )
    assert cursor.fetchone() == ("Y",)


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
