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
