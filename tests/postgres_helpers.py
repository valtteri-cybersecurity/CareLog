import threading
import time

import psycopg
import pytest


def table_exists(cursor, table):
    cursor.execute(
        """
        SELECT 1
        FROM pg_tables
        WHERE schemaname = current_schema()
          AND tablename = %s
        """,
        (table,),
    )
    return cursor.fetchone() is not None


def get_columns(cursor, table):
    cursor.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return cursor.fetchall()


def assert_postgres_error(cursor, error_class, sql, values=()):
    with pytest.raises(error_class):
        cursor.execute(sql, values)


def insert_client(cursor):
    cursor.execute(
        "INSERT INTO clients (first_name, last_name) "
        "VALUES ('Test', 'Client') RETURNING id"
    )
    return cursor.fetchone()[0]


def insert_service(cursor):
    cursor.execute("INSERT INTO services (name) VALUES ('Test service') RETURNING id")
    return cursor.fetchone()[0]


def insert_visit(cursor):
    client_id = insert_client(cursor)
    service_id = insert_service(cursor)
    cursor.execute(
        "INSERT INTO visits (client_id, service_id) VALUES (%s, %s) RETURNING id",
        (client_id, service_id),
    )
    return cursor.fetchone()[0]


def start_in_thread(function, *args, **kwargs):
    # Runs the service call in its own thread. done is set when the call
    # has returned or raised, and outcome holds the result or the error.
    outcome = {}
    done = threading.Event()

    def run():
        try:
            outcome["result"] = function(*args, **kwargs)
        except Exception as error:
            outcome["error"] = error
        finally:
            done.set()

    thread = threading.Thread(target=run)
    thread.start()

    return thread, done, outcome


def wait_until_waiting_for_lock(cursor, timeout_seconds=10):
    # Waits until a session of this test database waits for a row lock.
    # The time limit stops the test instead of hanging.
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND wait_event_type = 'Lock'
            """
        )

        if cursor.fetchone()[0] > 0:
            return

        time.sleep(0.02)

    pytest.fail("The service call did not wait for the row lock")
