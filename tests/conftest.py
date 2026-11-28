import os
from uuid import uuid4

import psycopg
import pytest

from carelog.database import postgres_connection, postgres_migrate
from tests.database_safety import (
    DatabaseConnectionBlocked,
    UnsafeTestServerError,
    read_application_target,
    read_test_server_settings,
    verify_test_server,
)
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


# Connection guard. While the tests run, every way to open a Psycopg
# connection is replaced with a function that refuses. Only the fixtures
# below use the real function, and only after verify_test_server() has
# accepted the server. So a test whose mock of get_postgres_connection
# fails, or that forgets to mock it, can never reach the real database.
#
# The real function is saved here, when conftest.py is imported and
# before the guard is installed in pytest_configure(). Only the
# fixtures of this file may use it.
REAL_PSYCOPG_CONNECT = psycopg.Connection.connect

connection_guard = pytest.MonkeyPatch()


def connection_not_allowed(*args, **kwargs):
    raise DatabaseConnectionBlocked(
        "Database connection blocked in tests. Use the PostgreSQL test "
        "fixtures, which connect only to a verified disposable test server."
    )


def classmethod_connection_not_allowed(cls, *args, **kwargs):
    connection_not_allowed()


def pytest_configure(config):
    # Installed before the test modules are imported, so even code that
    # runs at import time cannot connect.
    connection_guard.setattr(psycopg, "connect", connection_not_allowed)
    connection_guard.setattr(
        psycopg.Connection, "connect", classmethod(classmethod_connection_not_allowed)
    )
    connection_guard.setattr(
        psycopg.AsyncConnection, "connect", classmethod(classmethod_connection_not_allowed)
    )


def pytest_unconfigure(config):
    connection_guard.undo()


def connect_to_server_check_database(settings):
    return REAL_PSYCOPG_CONNECT(
        host=settings["host"],
        port=settings["port"],
        dbname="postgres",
        user=settings["user"],
        password=settings["password"],
        autocommit=True,
        connect_timeout=10,
    )


@pytest.fixture(scope="session")
def test_server_settings():
    try:
        settings = read_test_server_settings(os.environ)
    except UnsafeTestServerError as error:
        pytest.exit(f"Invalid PostgreSQL test settings: {error}", returncode=1)

    if settings is None:
        pytest.skip("Set CARELOG_TEST_PG_USER to run the PostgreSQL tests")

    # The application's own database from .env, so that the tests can
    # refuse it. Only the address, database and user are read.
    try:
        application_target = read_application_target(postgres_connection.ENV_FILE)
    except (OSError, ValueError) as error:
        pytest.exit(f"Could not read the application settings: {error}", returncode=1)

    # The tests create and drop databases and accounts, so the server
    # itself is checked once before any test, not only the settings.
    # Any problem stops all tests at once.
    try:
        verify_test_server(settings, application_target, connect_to_server_check_database)
    except UnsafeTestServerError as error:
        pytest.exit(
            f"Refusing to run tests against this PostgreSQL server: {error}. "
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

        return REAL_PSYCOPG_CONNECT(
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
