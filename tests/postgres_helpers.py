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


def insert_user(cursor, email="test.user@example.com", role="worker", is_active=True):
    # A test user of a temporary test database. The hash is not a real
    # password hash.
    cursor.execute(
        "INSERT INTO users (email, display_name, password_hash, role, is_active) "
        "VALUES (%s, 'Test User', 'test-only-hash', %s, %s) RETURNING id",
        (email, role, is_active),
    )
    return cursor.fetchone()[0]


def insert_test_users(cursor):
    # The standard test users. Use the returned ids; never assume them.
    # Run with the test user that owns the tables: the application account
    # cannot add users.
    return {
        "admin": insert_user(cursor, "admin.test@example.com", "admin"),
        "worker": insert_user(cursor, "worker.test@example.com", "worker"),
        "other_worker": insert_user(cursor, "other.worker.test@example.com", "worker"),
        "inactive": insert_user(cursor, "inactive.test@example.com", "worker", False),
    }


# Without user_id the rows below are added as in the schema before v014,
# which has no user columns. With user_id the same user is the creator
# and, for a visit, also the worker.


def insert_client(cursor, user_id=None):
    if user_id is None:
        cursor.execute(
            "INSERT INTO clients (first_name, last_name) "
            "VALUES ('Test', 'Client') RETURNING id"
        )
    else:
        cursor.execute(
            "INSERT INTO clients (first_name, last_name, created_by_user_id) "
            "VALUES ('Test', 'Client', %s) RETURNING id",
            (user_id,),
        )

    return cursor.fetchone()[0]


def insert_service(cursor, user_id=None):
    if user_id is None:
        cursor.execute("INSERT INTO services (name) VALUES ('Test service') RETURNING id")
    else:
        cursor.execute(
            "INSERT INTO services (name, created_by_user_id) "
            "VALUES ('Test service', %s) RETURNING id",
            (user_id,),
        )

    return cursor.fetchone()[0]


def insert_visit(cursor, user_id=None):
    client_id = insert_client(cursor, user_id)
    service_id = insert_service(cursor, user_id)

    if user_id is None:
        cursor.execute(
            "INSERT INTO visits (client_id, service_id) VALUES (%s, %s) RETURNING id",
            (client_id, service_id),
        )
    else:
        cursor.execute(
            "INSERT INTO visits (client_id, service_id, user_id, created_by_user_id) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (client_id, service_id, user_id, user_id),
        )

    return cursor.fetchone()[0]


def set_actor(cursor, user_id):
    # Gives the editor of the next change of a note's content, as the
    # application does since v014. Must be run inside a transaction:
    # the value disappears when the transaction ends.
    cursor.execute(
        "SELECT set_config('carelog.actor_user_id', %s, true)",
        (str(user_id),),
    )


def fake_active_user(cursor, actor_user_id):
    # Replaces the user check of a service in tests whose fake cursor
    # cannot run SQL. The user check itself is tested in
    # test_user_validation.py.
    return {"id": actor_user_id, "role": "worker", "is_active": True}


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
