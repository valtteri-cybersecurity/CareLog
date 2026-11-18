import pymysql
import pytest


def table_exists(cursor, table):
    cursor.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND TABLE_TYPE = 'BASE TABLE'
        """,
        (table,),
    )
    return cursor.fetchone() is not None


def get_columns(cursor, table):
    cursor.execute(
        """
        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    return cursor.fetchall()


def get_primary_key(cursor, table):
    cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND CONSTRAINT_NAME = 'PRIMARY'
        ORDER BY ORDINAL_POSITION
        """,
        (table,),
    )
    return [column[0] for column in cursor.fetchall()]


def assert_mysql_error(cursor, error_code, sql, values=()):
    with pytest.raises(pymysql.MySQLError) as error:
        cursor.execute(sql, values)
    assert error.value.args[0] == error_code


def insert_client(cursor):
    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_at) "
        "VALUES ('Test', 'Client', CURRENT_TIMESTAMP)"
    )
    return cursor.lastrowid


def insert_service(cursor):
    cursor.execute("INSERT INTO services (name) VALUES ('Test service')")
    return cursor.lastrowid


def insert_visit(cursor):
    client_id = insert_client(cursor)
    service_id = insert_service(cursor)
    cursor.execute(
        "INSERT INTO visits (client_id, service_id) VALUES (%s, %s)",
        (client_id, service_id),
    )
    return cursor.lastrowid
