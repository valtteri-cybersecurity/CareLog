import os
from uuid import uuid4

import pymysql
import pytest

from carelog.database.migrations import v002_clients, v003_services, v005_visits


@pytest.fixture
def connect_to_test_mysql():
    user = os.getenv("CARELOG_TEST_MYSQL_USER")
    if not user:
        pytest.skip("Set CARELOG_TEST_MYSQL_USER to run the MySQL tests")

    # The application account must never be used for tests.
    if user == "carelog_app":
        pytest.fail("Do not use carelog_app as CARELOG_TEST_MYSQL_USER; use a separate test user")

    def connect(database=None, autocommit=False):
        return pymysql.connect(
            host=os.getenv("CARELOG_TEST_MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("CARELOG_TEST_MYSQL_PORT", "3306")),
            user=user,
            password=os.getenv("CARELOG_TEST_MYSQL_PASSWORD", ""),
            unix_socket=os.getenv("CARELOG_TEST_MYSQL_SOCKET"),
            database=database,
            charset="utf8mb4",
            autocommit=autocommit,
        )

    return connect


@pytest.fixture
def cursor(connect_to_test_mysql):
    database = f"carelog_test_{uuid4().hex}"
    connection = connect_to_test_mysql(autocommit=True)
    with connection, connection.cursor() as test_cursor:
        test_cursor.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'")
        test_cursor.execute(
            f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        try:
            connection.select_db(database)
            yield test_cursor
        finally:
            test_cursor.execute(f"DROP DATABASE `{database}`")


@pytest.fixture
def cursor_with_clients(cursor):
    v002_clients.upgrade(cursor)
    return cursor


@pytest.fixture
def cursor_with_clients_and_services(cursor_with_clients):
    v003_services.upgrade(cursor_with_clients)
    return cursor_with_clients


@pytest.fixture
def cursor_with_visits(cursor_with_clients_and_services):
    v005_visits.upgrade(cursor_with_clients_and_services)
    return cursor_with_clients_and_services
