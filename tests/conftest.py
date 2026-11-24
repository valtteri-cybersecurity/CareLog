import os
from uuid import uuid4

import psycopg
import pytest

from carelog.database import postgres_migrate
from tests.postgres_helpers import insert_test_users


# PostgreSQL fixtures. Every test gets its own temporary database named
# carelog_test_*, which is dropped after the test. Use a separate,
# disposable PostgreSQL server for these tests.
#
# - postgres_cursor: an empty database, for the migration tests that
#   build older schema versions themselves.
# - migrated_cursor: the full current schema, for everything else. All
#   migrations are run once per test session into a template database,
#   and every test gets its own copy of it.

# A disposable test server is marked with this comment on its postgres
# database. Set it only on a server whose data may be lost:
# COMMENT ON DATABASE postgres IS 'carelog-disposable-test-server';
TEST_SERVER_MARKER = "carelog-disposable-test-server"


@pytest.fixture(scope="session")
def test_server_settings():
    user = os.getenv("CARELOG_TEST_PG_USER")
    if not user:
        pytest.skip("Set CARELOG_TEST_PG_USER to run the PostgreSQL tests")

    # The application and migration accounts must never be used for tests.
    if user == "carelog_app" or user == "carelog_migrator":
        pytest.exit(
            "Do not use carelog_app or carelog_migrator as CARELOG_TEST_PG_USER; "
            "use a separate test user",
            returncode=1,
        )

    settings = {
        "host": os.getenv("CARELOG_TEST_PG_HOST", "127.0.0.1"),
        "port": int(os.getenv("CARELOG_TEST_PG_PORT", "5432")),
        "user": user,
        "password": os.getenv("CARELOG_TEST_PG_PASSWORD", ""),
    }

    # The tests create and drop databases and accounts, so the server
    # itself is checked once before any test, not only the settings above.
    connection = psycopg.connect(
        host=settings["host"],
        port=settings["port"],
        dbname="postgres",
        user=settings["user"],
        password=settings["password"],
        autocommit=True,
        connect_timeout=10,
    )

    with connection:
        carelog_databases = connection.execute(
            "SELECT COUNT(*) FROM pg_database WHERE datname = 'carelog'"
        ).fetchone()[0]

        carelog_accounts = connection.execute(
            "SELECT COUNT(*) FROM pg_roles "
            "WHERE rolname IN ('carelog_app', 'carelog_migrator')"
        ).fetchone()[0]

        marker = connection.execute(
            "SELECT shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = 'postgres'"
        ).fetchone()[0]

    # The real CareLog server always has these. Stop all tests at once.
    if carelog_databases != 0 or carelog_accounts != 0:
        pytest.exit(
            "The test server has the carelog database or the carelog_app or "
            "carelog_migrator account. Refusing to run tests against the real "
            "CareLog server.",
            returncode=1,
        )

    if marker != TEST_SERVER_MARKER:
        pytest.exit(
            "The test server is not marked as a disposable test server. "
            "See Running Tests in README.md.",
            returncode=1,
        )

    return settings


@pytest.fixture(scope="session")
def connect_to_test_postgres(test_server_settings):
    def connect(database="postgres", user=None, password=None, autocommit=False):
        if user is None:
            user = test_server_settings["user"]

        if password is None:
            password = test_server_settings["password"]

        return psycopg.connect(
            host=test_server_settings["host"],
            port=test_server_settings["port"],
            dbname=database,
            user=user,
            password=password,
            autocommit=autocommit,
            connect_timeout=10,
            options="-c timezone=UTC",
        )

    return connect


def create_test_database(connect_to_test_postgres, template=None):
    # Creates a temporary test database, empty or as a copy of template,
    # yields a cursor to it and drops it afterwards.
    database = f"carelog_test_{uuid4().hex}"
    admin_connection = connect_to_test_postgres(autocommit=True)

    with admin_connection:
        if template is None:
            admin_connection.execute(f'CREATE DATABASE "{database}"')
        else:
            admin_connection.execute(f'CREATE DATABASE "{database}" TEMPLATE "{template}"')

        try:
            # autocommit: every statement of the test is saved at once, so
            # the services see the rows in their own connections.
            connection = connect_to_test_postgres(database=database, autocommit=True)

            with connection, connection.cursor() as test_cursor:
                yield test_cursor

        finally:
            # FORCE closes connections that a failed test left open.
            admin_connection.execute(f'DROP DATABASE "{database}" WITH (FORCE)')


@pytest.fixture
def postgres_cursor(connect_to_test_postgres):
    yield from create_test_database(connect_to_test_postgres)


@pytest.fixture(scope="session")
def migrated_template_database(connect_to_test_postgres):
    # Runs every migration once per test session into a template
    # database, with apply_migrations(), the same function that
    # run_postgres_migrations() uses in production.
    #
    # Three kinds of connections are kept apart:
    # - admin_connection (autocommit): CREATE and DROP DATABASE, which
    #   PostgreSQL does not allow inside a transaction
    # - migration_connection (autocommit off): apply_migrations() runs
    #   each migration in its own transaction
    # - the test cursors of create_test_database() (autocommit)
    database = f"carelog_test_template_{uuid4().hex}"
    admin_connection = connect_to_test_postgres(autocommit=True)

    with admin_connection:
        admin_connection.execute(f'CREATE DATABASE "{database}"')

        try:
            migration_connection = connect_to_test_postgres(database=database, autocommit=False)

            # The connection is closed before the copies are made:
            # PostgreSQL copies a template only when nobody is connected.
            try:
                postgres_migrate.apply_migrations(migration_connection)
            finally:
                migration_connection.close()

            yield database

        finally:
            admin_connection.execute(f'DROP DATABASE "{database}" WITH (FORCE)')


@pytest.fixture
def migrated_cursor(connect_to_test_postgres, migrated_template_database):
    yield from create_test_database(connect_to_test_postgres, migrated_template_database)


@pytest.fixture
def user_ids(migrated_cursor):
    # Test users with the ids that the database gave them
    return insert_test_users(migrated_cursor)


# The fixtures below are kept so that the tests need not be renamed.
# Every one of them now gives the full current schema, so the service
# tests run against the same schema as the application.


@pytest.fixture
def postgres_cursor_with_clients(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_clients_and_services(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_trips(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_visits(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_visit_scheduling(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_visit_notes(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_expenses(migrated_cursor):
    return migrated_cursor


@pytest.fixture
def postgres_cursor_with_visit_trips(migrated_cursor):
    return migrated_cursor
