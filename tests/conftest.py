import os
from uuid import uuid4

import psycopg
import pytest

from carelog.database.postgres_migrations import (
    v001_users as postgres_v001_users,
    v002_clients as postgres_v002_clients,
    v003_services as postgres_v003_services,
    v004_trips as postgres_v004_trips,
    v005_visits as postgres_v005_visits,
    v006_visit_notes as postgres_v006_visit_notes,
    v007_expenses as postgres_v007_expenses,
    v008_business_constraints as postgres_v008_business_constraints,
    v009_visit_scheduling as postgres_v009_visit_scheduling,
    v010_visit_constraints as postgres_v010_visit_constraints,
    v011_visit_trip_legs as postgres_v011_visit_trip_legs,
)


# PostgreSQL fixtures. Every test gets its own temporary database named
# carelog_test_*, which is dropped after the test. Use a separate,
# disposable PostgreSQL server for these tests.


@pytest.fixture
def connect_to_test_postgres():
    user = os.getenv("CARELOG_TEST_PG_USER")
    if not user:
        pytest.skip("Set CARELOG_TEST_PG_USER to run the PostgreSQL tests")

    # The application and migration accounts must never be used for tests.
    if user == "carelog_app" or user == "carelog_migrator":
        pytest.fail(
            "Do not use carelog_app or carelog_migrator as CARELOG_TEST_PG_USER; "
            "use a separate test user"
        )

    def connect(database="postgres", user=user, password=None, autocommit=False):
        if password is None:
            password = os.getenv("CARELOG_TEST_PG_PASSWORD", "")

        return psycopg.connect(
            host=os.getenv("CARELOG_TEST_PG_HOST", "127.0.0.1"),
            port=int(os.getenv("CARELOG_TEST_PG_PORT", "5432")),
            dbname=database,
            user=user,
            password=password,
            autocommit=autocommit,
            connect_timeout=10,
            options="-c timezone=UTC",
        )

    return connect


@pytest.fixture
def postgres_cursor(connect_to_test_postgres):
    database = f"carelog_test_{uuid4().hex}"
    admin_connection = connect_to_test_postgres(autocommit=True)

    with admin_connection:
        admin_connection.execute(f'CREATE DATABASE "{database}"')

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
def postgres_cursor_with_clients(postgres_cursor):
    # v002 uses the set_updated_at() trigger function created in v001.
    postgres_v001_users.upgrade(postgres_cursor)
    postgres_v002_clients.upgrade(postgres_cursor)
    return postgres_cursor


@pytest.fixture
def postgres_cursor_with_clients_and_services(postgres_cursor_with_clients):
    postgres_v003_services.upgrade(postgres_cursor_with_clients)
    return postgres_cursor_with_clients


@pytest.fixture
def postgres_cursor_with_trips(postgres_cursor_with_clients):
    postgres_v004_trips.upgrade(postgres_cursor_with_clients)
    return postgres_cursor_with_clients


@pytest.fixture
def postgres_cursor_with_visits(postgres_cursor_with_clients_and_services):
    postgres_v005_visits.upgrade(postgres_cursor_with_clients_and_services)
    return postgres_cursor_with_clients_and_services


@pytest.fixture
def postgres_cursor_with_visit_scheduling(postgres_cursor_with_visits):
    postgres_v009_visit_scheduling.upgrade(postgres_cursor_with_visits)
    postgres_v010_visit_constraints.upgrade(postgres_cursor_with_visits)
    return postgres_cursor_with_visits


@pytest.fixture
def postgres_cursor_with_visit_notes(postgres_cursor_with_visit_scheduling):
    postgres_v006_visit_notes.upgrade(postgres_cursor_with_visit_scheduling)
    return postgres_cursor_with_visit_scheduling


@pytest.fixture
def postgres_cursor_with_expenses(postgres_cursor_with_visit_scheduling):
    cursor = postgres_cursor_with_visit_scheduling

    # v008 adds CHECK constraints to all of these tables, including
    # amount > 0 for expenses, so the other tables are created too.
    postgres_v004_trips.upgrade(cursor)
    postgres_v006_visit_notes.upgrade(cursor)
    postgres_v007_expenses.upgrade(cursor)
    postgres_v008_business_constraints.upgrade(cursor)

    return cursor


@pytest.fixture
def postgres_cursor_with_visit_trips(postgres_cursor_with_visit_scheduling):
    postgres_v011_visit_trip_legs.upgrade(postgres_cursor_with_visit_scheduling)
    return postgres_cursor_with_visit_scheduling
