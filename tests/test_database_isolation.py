import asyncio

import psycopg
import pytest

from carelog.database import postgres_connection, postgres_migrate
from carelog.services import services
from tests.postgres_helpers import start_in_thread
from tests.database_safety import (
    TEST_SERVER_MARKER,
    DatabaseConnectionBlocked,
    UnsafeTestServerError,
    find_server_problems,
    find_settings_problems,
    read_application_target,
    read_test_server_settings,
    verify_test_server,
)


# Regression tests for the database isolation of the test suite. None of
# these tests connects to any database server: the guard and the server
# checks are tested with synthetic settings and a fake connection.


# Synthetic settings. Port 1 is never a PostgreSQL server.
UNREACHABLE_APP_CONFIG = {
    "CARELOG_PG_HOST": "127.0.0.1",
    "CARELOG_PG_PORT": "1",
    "CARELOG_PG_DATABASE": "carelog",
    "CARELOG_PG_USER": "carelog_app",
    "CARELOG_PG_PASSWORD": "not-a-real-password",
}

DEVELOPMENT_TARGET = {
    "host": "127.0.0.1",
    "port": "5433",
    "database": "carelog",
    "user": "carelog_app",
}

DISPOSABLE_SETTINGS = {
    "host": "127.0.0.1",
    "port": 5434,
    "user": "postgres",
    "password": "test-only",
}


def clean_server_state():
    return {
        "databases": ["postgres", "template0", "template1"],
        "roles": ["postgres", "pg_read_all_data"],
        "marker": TEST_SERVER_MARKER,
        "user_tables": 0,
    }


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        if self.rows:
            return self.rows[0]

        return None


class FakeServerConnection:
    # Answers the queries of collect_server_state() from a server state

    def __init__(self, server_state):
        self.server_state = server_state

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        if "pg_class" in query:
            return FakeResult([(self.server_state["user_tables"],)])

        if "shobj_description" in query:
            return FakeResult([(self.server_state["marker"],)])

        if "pg_roles" in query:
            rows = []

            for role in self.server_state["roles"]:
                rows.append((role,))

            return FakeResult(rows)

        if "pg_database" in query:
            rows = []

            for database in self.server_state["databases"]:
                rows.append((database,))

            return FakeResult(rows)

        raise AssertionError(f"Unexpected query: {query}")


class RecordingConnect:
    # A fake connect function that remembers whether it was called

    def __init__(self, server_state):
        self.server_state = server_state
        self.called = False

    def __call__(self, settings):
        self.called = True
        return FakeServerConnection(self.server_state)


# Connection guard


def test_direct_psycopg_connection_is_blocked():
    with pytest.raises(DatabaseConnectionBlocked):
        psycopg.connect(host="127.0.0.1", port=1, dbname="carelog", connect_timeout=1)


def test_connection_class_method_is_blocked():
    with pytest.raises(DatabaseConnectionBlocked):
        psycopg.Connection.connect(host="127.0.0.1", port=1, dbname="carelog")


def test_async_connection_is_blocked():
    async def connect():
        await psycopg.AsyncConnection.connect(host="127.0.0.1", port=1, dbname="carelog")

    with pytest.raises(DatabaseConnectionBlocked):
        asyncio.run(connect())


def test_connection_in_another_thread_is_blocked():
    thread, done, outcome = start_in_thread(
        psycopg.connect, host="127.0.0.1", port=1, dbname="carelog"
    )
    thread.join(timeout=10)

    assert done.is_set()
    assert "result" not in outcome
    assert isinstance(outcome["error"], DatabaseConnectionBlocked)


def test_application_connection_is_blocked_even_with_valid_config(monkeypatch):
    # The real get_postgres_connection() with a complete configuration
    # still cannot open a connection in a test.
    def fake_load_config():
        return UNREACHABLE_APP_CONFIG

    monkeypatch.setattr(postgres_connection, "load_postgres_config", fake_load_config)

    with pytest.raises(DatabaseConnectionBlocked):
        postgres_connection.get_postgres_connection()


def test_unmocked_service_call_is_blocked(monkeypatch):
    # A unit test that forgets to replace the connection of a service
    def fake_load_config():
        return UNREACHABLE_APP_CONFIG

    monkeypatch.setattr(postgres_connection, "load_postgres_config", fake_load_config)

    with pytest.raises(DatabaseConnectionBlocked):
        services.get_services()


def test_failed_mock_still_blocks_connection(monkeypatch):
    # The mock replaces the function in the wrong module. The service
    # module keeps its own reference to the real function, so the mock
    # has no effect, and the guard must stop the connection.
    def fake_connection():
        raise AssertionError("This mock is never used")

    def fake_load_config():
        return UNREACHABLE_APP_CONFIG

    monkeypatch.setattr(postgres_connection, "get_postgres_connection", fake_connection)
    monkeypatch.setattr(postgres_connection, "load_postgres_config", fake_load_config)

    with pytest.raises(DatabaseConnectionBlocked):
        services.get_service(1)


def test_migration_connection_is_blocked(monkeypatch):
    def fake_load_config():
        return UNREACHABLE_APP_CONFIG

    monkeypatch.setattr(postgres_connection, "load_postgres_config", fake_load_config)

    with pytest.raises(DatabaseConnectionBlocked):
        postgres_migrate.run_postgres_migrations(password="not-a-real-password")


def test_blocked_connection_cannot_be_swallowed_by_except_exception():
    def connect_and_hide_errors():
        try:
            psycopg.connect(host="127.0.0.1", port=1, dbname="carelog")
        except Exception:
            return "error hidden"

        return "connected"

    with pytest.raises(DatabaseConnectionBlocked):
        connect_and_hide_errors()


# Test settings


def test_missing_test_user_skips_database_tests():
    assert read_test_server_settings({}) is None


def test_valid_test_settings_are_read():
    settings = read_test_server_settings({
        "CARELOG_TEST_PG_HOST": "127.0.0.1",
        "CARELOG_TEST_PG_PORT": "5434",
        "CARELOG_TEST_PG_USER": "postgres",
        "CARELOG_TEST_PG_PASSWORD": "test-only",
    })

    assert settings == DISPOSABLE_SETTINGS


@pytest.mark.parametrize(
    "environment, message",
    [
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_PORT": "5434"},
         "CARELOG_TEST_PG_HOST"),
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_HOST": "127.0.0.1"},
         "CARELOG_TEST_PG_PORT"),
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_HOST": "127.0.0.1",
          "CARELOG_TEST_PG_PORT": "abc"},
         "number"),
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_HOST": "127.0.0.1",
          "CARELOG_TEST_PG_PORT": "-5434"},
         "number"),
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_HOST": "127.0.0.1",
          "CARELOG_TEST_PG_PORT": "0"},
         "between"),
        ({"CARELOG_TEST_PG_USER": "postgres", "CARELOG_TEST_PG_HOST": "127.0.0.1",
          "CARELOG_TEST_PG_PORT": "65536"},
         "between"),
    ],
)
def test_incomplete_or_invalid_test_settings_are_refused(environment, message):
    with pytest.raises(UnsafeTestServerError, match=message):
        read_test_server_settings(environment)


@pytest.mark.parametrize(
    "variable", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR"]
)
def test_libpq_rerouting_variables_are_refused(variable):
    environment = {
        "CARELOG_TEST_PG_HOST": "127.0.0.1",
        "CARELOG_TEST_PG_PORT": "5434",
        "CARELOG_TEST_PG_USER": "postgres",
        variable: "anything",
    }

    with pytest.raises(UnsafeTestServerError, match=variable):
        read_test_server_settings(environment)


@pytest.mark.parametrize("user", ["carelog_app", "carelog_migrator"])
def test_application_accounts_are_refused_as_test_user(user):
    settings = dict(DISPOSABLE_SETTINGS)
    settings["user"] = user

    problems = find_settings_problems(settings, None)

    assert len(problems) == 1
    assert user in problems[0]


def test_application_target_is_read_without_password(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CARELOG_PG_HOST=127.0.0.1\n"
        "CARELOG_PG_PORT=5433\n"
        "CARELOG_PG_DATABASE=carelog\n"
        "CARELOG_PG_USER=carelog_app\n"
        "CARELOG_PG_PASSWORD=not-a-real-password\n"
    )

    assert read_application_target(env_file) == DEVELOPMENT_TARGET


def test_missing_env_file_gives_no_application_target(tmp_path):
    assert read_application_target(tmp_path / ".env") is None


# Development database


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1"])
def test_development_server_address_is_refused_before_connecting(host):
    settings = dict(DISPOSABLE_SETTINGS)
    settings["host"] = host
    settings["port"] = 5433

    # Even a server that looks disposable is not accepted
    connect = RecordingConnect(clean_server_state())

    with pytest.raises(UnsafeTestServerError, match="application's database server"):
        verify_test_server(settings, DEVELOPMENT_TARGET, connect)

    assert connect.called is False


def test_development_database_user_is_refused_as_test_user():
    target = dict(DEVELOPMENT_TARGET)
    target["user"] = "carelog_dev_user"
    settings = dict(DISPOSABLE_SETTINGS)
    settings["user"] = "carelog_dev_user"
    connect = RecordingConnect(clean_server_state())

    with pytest.raises(UnsafeTestServerError, match="application's database user"):
        verify_test_server(settings, target, connect)

    assert connect.called is False


def test_development_database_on_test_port_is_refused():
    # The address looks like the test server, but the server has the
    # application's database: for example a wrong port forwarding.
    server_state = clean_server_state()
    server_state["databases"].append("carelog")

    with pytest.raises(UnsafeTestServerError, match="non-test database: carelog"):
        verify_test_server(DISPOSABLE_SETTINGS, DEVELOPMENT_TARGET, RecordingConnect(server_state))


def test_development_database_with_own_name_is_refused():
    target = dict(DEVELOPMENT_TARGET)
    target["database"] = "carelog_dev"
    server_state = clean_server_state()
    server_state["databases"].append("carelog_dev")

    problems = find_server_problems(server_state, target)

    assert problems == ["the server has a non-test database: carelog_dev"]


def test_development_server_marked_by_mistake_is_refused():
    # The marker alone is not enough
    server_state = clean_server_state()
    server_state["databases"].append("carelog")
    server_state["roles"].append("carelog_app")

    problems = find_server_problems(server_state, None)

    assert "the server has a non-test database: carelog" in problems
    assert "the server has the CareLog account carelog_app" in problems


# Production database


def test_production_database_is_refused():
    server_state = clean_server_state()
    server_state["databases"].append("carelog_production")
    server_state["roles"].append("carelog_app")
    server_state["roles"].append("carelog_migrator")
    server_state["marker"] = None

    with pytest.raises(UnsafeTestServerError) as error:
        verify_test_server(DISPOSABLE_SETTINGS, None, RecordingConnect(server_state))

    message = str(error.value)
    assert "not marked as a disposable test server" in message
    assert "non-test database: carelog_production" in message
    assert "carelog_app" in message
    assert "carelog_migrator" in message


def test_production_application_user_from_env_is_refused_on_server():
    target = dict(DEVELOPMENT_TARGET)
    target["user"] = "carelog_prod_app"
    server_state = clean_server_state()
    server_state["roles"].append("carelog_prod_app")

    problems = find_server_problems(server_state, target)

    assert problems == ["the server has the CareLog account carelog_prod_app"]


def test_application_tables_in_postgres_database_are_refused():
    # A server marked by mistake, with the application's tables in the
    # default postgres database and differently named accounts
    server_state = clean_server_state()
    server_state["user_tables"] = 12

    problems = find_server_problems(server_state, None)

    assert problems == ["the postgres database of the server has tables"]


def test_unmarked_server_is_refused():
    server_state = clean_server_state()
    server_state["marker"] = "some other comment"

    with pytest.raises(UnsafeTestServerError, match="not marked"):
        verify_test_server(DISPOSABLE_SETTINGS, None, RecordingConnect(server_state))


# Disposable test server


def test_disposable_test_server_is_accepted():
    connect = RecordingConnect(clean_server_state())

    verify_test_server(DISPOSABLE_SETTINGS, DEVELOPMENT_TARGET, connect)

    assert connect.called is True


def test_disposable_test_server_with_leftover_test_databases_is_accepted():
    server_state = clean_server_state()
    server_state["databases"].append("carelog_test_0123456789abcdef")
    server_state["databases"].append("carelog_test_template_0123456789abcdef")
    server_state["roles"].append("carelog_test_app_0123456789abcdef")

    assert find_server_problems(server_state, DEVELOPMENT_TARGET) == []


def test_verified_test_server_connection_works(connect_to_test_postgres):
    # Runs only against a verified disposable test server. The guard
    # must not stop the fixtures that use the approved server.
    connection = connect_to_test_postgres(autocommit=True)

    with connection:
        marker = connection.execute(
            "SELECT shobj_description(oid, 'pg_database') "
            "FROM pg_database WHERE datname = 'postgres'"
        ).fetchone()[0]

    assert marker == TEST_SERVER_MARKER
