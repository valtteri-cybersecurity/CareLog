
from pymysql.constants import ER

from carelog.database.migrations import v002_clients
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_client,
    table_exists,
)


def test_upgrade_creates_table(cursor):
    assert not table_exists(cursor, "clients")
    v002_clients.upgrade(cursor)
    assert table_exists(cursor, "clients")


def test_table_structure(cursor):
    v002_clients.upgrade(cursor)

    assert get_columns(cursor, "clients") == (
        ("id", "int", "NO", None),
        ("first_name", "varchar(100)", "NO", None),
        ("last_name", "varchar(100)", "NO", None),
        ("phone", "varchar(50)", "YES", None),
        ("email", "varchar(255)", "YES", None),
        ("street_address", "varchar(255)", "YES", None),
        ("postal_code", "varchar(20)", "YES", None),
        ("city", "varchar(100)", "YES", None),
        ("distance_from_home_km", "decimal(10,2)", "YES", None),
        ("archived_at", "datetime", "YES", None),
        ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
    )


def test_table_constraints(cursor):
    v002_clients.upgrade(cursor)
    assert get_primary_key(cursor, "clients") == ["id"]

    client_id = insert_client(cursor)
    assert client_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO clients (id, first_name, last_name, created_at) "
        "VALUES (%s, 'Other', 'Client', CURRENT_TIMESTAMP)",
        (client_id,),
    )

    assert_mysql_error(
        cursor, ER.BAD_NULL_ERROR,
        "INSERT INTO clients (first_name, last_name, created_at) "
        "VALUES ('Test', NULL, CURRENT_TIMESTAMP)",
    )

